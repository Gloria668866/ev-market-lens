"""NLU：本地实体扫描与确定性规则主路，单次 typed LLM 兜底。

纯寒暄和高确定性业务模式不调用模型；其余问题最多一次性返回意图、
置信度、实体和规范化问题，再经 Pydantic、逐字段合并、槽位与业务规则
校验。完整口径见 ``docs/technical-design.md`` 第 3 节。
"""
import json
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Literal

import numpy as np
import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import NLU_CONFIG_PATH
from .llm import chat
from .rag.embed import embed_query, embed_passages

_cfg_lock = threading.Lock()
_cfg = None

_few_shot_lock = threading.Lock()
_few_shot_embeddings = None   # np.ndarray shape (N, embed_dim)
_few_shot_examples = None     # list[dict]
_few_shot_initialized = False

IntentName = Literal["sql", "rag", "hybrid", "chat", "clarify"]
_ENTITY_FIELDS = ("brands", "models", "time", "metrics", "energy_types")


class NluModelPayload(BaseModel):
    """Validated contract for the single fallback model call."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    intent: IntentName = "clarify"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    top2_intent: Literal["", "sql", "rag", "hybrid", "chat", "clarify"] = ""
    top2_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    brands: list[str] = Field(default_factory=list, max_length=16)
    models: list[str] = Field(default_factory=list, max_length=16)
    time: list[str] = Field(default_factory=list, max_length=16)
    metrics: list[str] = Field(default_factory=list, max_length=16)
    energy_types: list[str] = Field(default_factory=list, max_length=16)
    normalized_question: str = ""

    @field_validator(*_ENTITY_FIELDS, mode="before")
    @classmethod
    def entity_fields_must_be_arrays(cls, value):
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("entity field must be a JSON array")
        return value

    @field_validator(*_ENTITY_FIELDS)
    @classmethod
    def normalize_entity_values(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        for value in values:
            if not isinstance(value, str):
                raise ValueError("entity values must be strings")
            cleaned = value.strip()
            if cleaned and cleaned not in result:
                result.append(cleaned)
        return result


def _load_config() -> dict:
    global _cfg
    with _cfg_lock:
        if _cfg is not None:
            return _cfg
        path = Path(NLU_CONFIG_PATH)
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        _cfg = (raw or {}).get("nlu", {})
    return _cfg


def _init_few_shot(cfg: dict) -> None:
    """Pre-embed few-shot examples into in-memory numpy array. Uses _few_shot_lock."""
    global _few_shot_embeddings, _few_shot_examples, _few_shot_initialized
    with _few_shot_lock:
        if _few_shot_initialized:
            return
        _few_shot_initialized = True
        examples = cfg.get("few_shot_examples") or []
        if not examples:
            return
        texts = [e.get("question", "") for e in examples if e.get("question")]
        try:
            vecs = embed_passages(texts)
        except Exception:
            # Few-shot retrieval is an optimisation, never a startup/runtime
            # availability dependency.
            return
        if vecs:
            _few_shot_embeddings = np.array(vecs, dtype=np.float32)
            _few_shot_examples = examples


def get_cfg() -> dict:
    if _cfg is None:
        _load_config()
    return _cfg


# ── Layer 1: 规则预筛 ──────────────────────────────────────────────────────────

def layer1_prefilter(question: str, last_assistant: str = "") -> dict | None:
    """规则命中返回意图 dict，未命中返回 None。
    返回 {"force_rag": True} 表示上轮无数据，Layer 2 需覆盖 sql/hybrid。"""
    cfg = get_cfg()
    greetings = cfg.get("greeting_prefixes", [])
    q = question.strip()
    greeting_suffixes = {"", "呀", "啊", "哦", "哈", "呢", "哇"}
    greeting_only = False
    for greeting in greetings:
        if not q.startswith(greeting):
            continue
        tail = q[len(greeting):].strip(" \t\r\n，,。.!！?？~～")
        if tail in greeting_suffixes:
            greeting_only = True
            break
    if greeting_only:
        return {"intent": "chat", "confidence": 1.0, "source": "layer1_greeting"}

    no_data_signals = cfg.get("no_data_signals", [])
    if last_assistant and any(sig in last_assistant for sig in no_data_signals):
        return {"force_rag": True}

    return None


def deterministic_intent_hint(question: str, context_block: str = "") -> str | None:
    """Return an intent only for lexically unambiguous business patterns.

    This small semantic gate stabilizes common product queries before the LLM
    confidence gate. It deliberately leaves short generic phrases such as
    ``销量排名`` to the normal clarify path.
    """
    cfg = get_cfg().get("deterministic_hints", {})
    q = question.strip()

    if not context_block and q in set(cfg.get("vague_phrases", [])):
        return "clarify"

    # Deictic references without conversation context cannot be resolved.
    # Match a shape rather than memorising individual evaluation sentences:
    # “这个/那个/它/哪个 + 看看/好/行不行/值得/分析…”.
    has_unresolved_reference = bool(
        re.search(r"(?:这个|那个|它|哪个|哪辆|哪款|这几个)", q)
        and re.search(r"(?:看看|好(?:不好)?|行不行|靠谱|值得|入手|分析|选哪个)", q)
    )
    has_explicit_business_request = any(
        word.lower() in q.lower()
        for word in (
            *cfg.get("structured_keywords", []),
            *cfg.get("knowledge_keywords", []),
        )
    )
    if (
        not context_block
        and has_unresolved_reference
        and not has_explicit_business_request
    ):
        return "clarify"

    # “买什么车合适”若没有预算、用途、能源类型等约束，系统无法给出
    # 可验证的推荐。先追问，避免把宽泛购车咨询误当成知识库检索。
    asks_purchase_recommendation = any(
        phrase in q for phrase in cfg.get("underspecified_purchase_phrases", [])
    ) or bool(re.search(r"(?:推荐|选|买).{0,6}(?:一款|什么|哪个|哪款)?车", q))
    has_purchase_scope = bool(re.search(r"\d+(?:\.\d+)?\s*万", q)) or any(
        word in q for word in cfg.get("purchase_scope_keywords", [])
    )
    if (
        not context_block
        and asks_purchase_recommendation
        and not has_purchase_scope
    ):
        return "clarify"

    # Some numeric-looking metrics are explicitly outside the analysis schema
    # (charging infrastructure, exports, penetration, regulations, etc.).
    # Route them to knowledge retrieval before the confidence gate; if the same
    # question also asks for supported sales/price facts, it is genuinely hybrid.
    forced_knowledge = any(
        any(keyword in q for keyword in rule.get("if_contains", []))
        and rule.get("force_intent") == "rag"
        for rule in get_cfg().get("business_rules", [])
    )
    supported_database_fact = any(
        keyword.lower() in q.lower()
        for keyword in (
            "销量", "销售量", "卖了", "卖得", "排名", "销量榜",
            "指导价", "价格", "价位", "口碑评分",
        )
    )
    if forced_knowledge:
        return "hybrid" if supported_database_fact else "rag"

    knowledge = any(word in q for word in cfg.get("knowledge_keywords", []))
    structured = any(word.lower() in q.lower() for word in cfg.get("structured_keywords", []))

    if knowledge and structured:
        # “报告怎么评价销量/价格”是在问文档内容，不应仅因出现结构化指标就误路由
        # 到 hybrid。只有同一句还明确要求查实际数据时才需要双脑。
        document_framed = any(word in q for word in cfg.get("document_source_keywords", []))
        asks_database_result = any(
            word.lower() in q.lower()
            for word in cfg.get("database_request_keywords", [])
        )
        if document_framed and not asks_database_result:
            return "rag"
        return "hybrid"
    if knowledge:
        return "rag"

    # Clearly unrelated small-talk is a stable zero-call path, but only when
    # the sentence contains no automotive/business signal.  This keeps
    # “午饭吃什么” deterministic without swallowing questions such as
    # “天气如何影响新能源汽车销量”.
    off_topic = any(
        word in q for word in cfg.get("off_topic_chat_keywords", [])
    )
    automotive_domain = any(
        word.lower() in q.lower()
        for word in cfg.get("automotive_domain_keywords", [])
    )
    if off_topic and not automotive_domain and not structured:
        return "chat"

    # A structured keyword alone is not enough: "销量排名" still lacks scope.
    # Numeric price/time constraints, an explicit analytic operation, or a
    # filter represented by the current schema make it executable.
    has_numeric_scope = bool(
        re.search(r"\d+(?:\.\d+)?\s*(?:万|年|月|到|至|-)", q)
        or re.search(r"(?:前|top\s*)\d+", q, flags=re.IGNORECASE)
    )
    has_operation = any(word in q for word in cfg.get("sql_operation_keywords", []))
    local_entities = _keyword_entity_scan(q)
    has_schema_filter = any(
        local_entities.get(field)
        for field in ("brands", "models", "time", "energy_types")
    ) or bool(
        re.search(
            r"(?:微型|小型|紧凑型|中型|中大型|大型)?(?:SUV|轿车|MPV)",
            q,
            flags=re.IGNORECASE,
        )
    )
    if structured and (has_numeric_scope or has_operation or has_schema_filter):
        return "sql"
    return None


# ── Layer 4: 槽位完整性检查 ───────────────────────────────────────────────────

def layer4_check_completeness(intent: str, entities: dict, question: str) -> tuple[bool, list]:
    """仅检查 sql/hybrid；其他意图直接返回 (True, [])。"""
    if intent not in ("sql", "hybrid"):
        return True, []

    cfg = get_cfg()
    slot_rules = cfg.get("slot_rules", {})
    requires = [k for k in slot_rules.get("sql_requires_one_of", []) if k != "explicit_metric"]
    metric_kw = slot_rules.get("explicit_metric_keywords", [])

    has_entity = any(entities.get(k) for k in requires)
    has_metric_kw = any(kw in question for kw in metric_kw)

    if has_entity or has_metric_kw:
        return True, []
    return False, ["请补充：品牌（如比亚迪）、车系（如SU7）、时间（如2025年）或具体指标（如Top10）"]


# ── Layer 5: 业务规则覆盖 ─────────────────────────────────────────────────────

def layer5_business_rules(intent: str, question: str) -> str:
    """按配置规则覆盖意图。只允许纠正 sql → rag；hybrid/rag/chat/clarify 不降级。"""
    if intent != "sql":
        return intent
    cfg = get_cfg()
    for rule in cfg.get("business_rules", []):
        if any(kw in question for kw in rule.get("if_contains", [])):
            return rule.get("force_intent", intent)
    return intent


# ── 置信度门控 ────────────────────────────────────────────────────────────────

def _confidence_gate(cls: dict) -> bool:
    """置信度不足或 top1/top2 差距太小 → 返回 False（触发 clarify）。"""
    cfg = get_cfg()
    threshold = float(cfg.get("confidence_threshold", 0.70))
    gap_min = float(cfg.get("ambiguity_gap", 0.15))

    if cls.get("confidence", 0) < threshold:
        return False
    top2 = cls.get("top2_confidence", 0.0)
    if (cls["confidence"] - top2) < gap_min:
        return False
    return True


# ── Few-shot 向量检索 ──────────────────────────────────────────────────────────

def _retrieve_few_shot(question: str, top_k: int = 3) -> list:
    """余弦相似度检索 in-memory few-shot；模型不可用或未加载返回 []。"""
    if (
        (_few_shot_embeddings is None or _few_shot_examples is None)
        and not _few_shot_initialized
    ):
        _init_few_shot(get_cfg())
    if _few_shot_embeddings is None or _few_shot_examples is None:
        return []
    qvec = embed_query(question)
    if qvec is None:
        return []
    q = np.array(qvec, dtype=np.float32)
    sims = _few_shot_embeddings @ q          # 已归一化，点积=余弦相似度
    top_idx = np.argsort(sims)[::-1][:top_k]
    return [_few_shot_examples[i] for i in top_idx]


def _build_few_shot_block(examples: list) -> str:
    if not examples:
        return ""
    lines = ["参考示例："]
    for ex in examples:
        q_text = ex.get("question", "")
        i_text = ex.get("intent", "")
        if q_text and i_text:
            lines.append(f'  问题: "{q_text}" → intent: {i_text}')
    return "\n".join(lines) + "\n\n"


# ── Layer 2: 单次结构化 LLM 兜底 ─────────────────────────────────────────────

_NLU_SYS = """\
你是新能源汽车市场情报系统的 NLU。一次完成意图分类、实体提取和问题规范化。
只返回严格 JSON（无 Markdown、无解释）。

JSON 格式：
{"intent":"sql|rag|hybrid|chat|clarify","confidence":0.95,
 "top2_intent":"rag","top2_confidence":0.08,
 "brands":[],"models":[],"time":[],"metrics":[],"energy_types":[],
 "normalized_question":"规范化后的问题"}

意图定义：
- sql: 需要查**本系统结构化数据库**的数据。数据库仅覆盖：各品牌/车系月度销量排名、指导价、口碑评分。只有能从这些表中直接计算出来的问题才属于 sql。
- rag: 需要从文档/研报/政策检索的问题。包括但不限于：行业宏观数据（充电桩数量、出口数据、市场渗透率）、技术趋势（800V/固态电池/智驾）、政策法规、行业分析报告内容、不在本数据库中的统计数据。
- hybrid: 既需要数据库中的销量/价格数据，又需要文档中的分析/解读/特征描述。典型模式：「哪些品牌销量领先，它们各自有什么特征」「XX销量如何，为什么」。
- chat: 问候/闲聊/完全无关新能源汽车市场
- clarify: 问题模糊/缺少必要实体/无法确定查询口径

关键判断规则：
- 数据库中**没有**的数据（充电桩、出口量、充电次数、市场渗透率、保有量、产量）→ 必须走 rag
- 问「趋势」但不涉及具体品牌/车系销量数字 → rag
- 问「XX销量」+「为什么/特征/分析」→ hybrid
- 仅问品牌/车系的销量、价格、排名数字 → sql
- 涉及销量的「占比」「比重」「份额」可从数据库直接计算 → sql
- 问候后只有品牌/车系名、没有具体问题（如「你好比亚迪」）→ clarify

实体规范化：
- brands/models/time/metrics/energy_types 必须始终为字符串数组
- su7/SU7 保持 SU7；byd/BYD → 比亚迪
- 今年 → 2026年，去年 → 2025年，前年 → 2024年
- 只从当前问题提取实体；历史仅用于理解指代，不得凭空添加实体
"""


def _json_object(raw: str) -> dict:
    """Extract one JSON object from a model response."""
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start < 0 or end <= start:
        raise ValueError("no JSON object in response")
    value = json.loads(raw[start:end])
    if not isinstance(value, dict):
        raise ValueError("NLU response is not a JSON object")
    return value


def layer2_analyze(question: str, context_block: str = "", force_rag: bool = False) -> dict:
    """One validated LLM call for classification and entity extraction.

    FAIL-SAFE: network, JSON and schema errors all become ``clarify``.  This is
    the only model seam used by ``classify``; common deterministic paths make
    zero NLU model calls.
    """
    try:
        few_shot = _retrieve_few_shot(question)
        prompt = _build_few_shot_block(few_shot)
        if context_block:
            prompt += context_block + "\n\n"
        prompt += question

        raw = chat([
            {"role": "system", "content": _NLU_SYS},
            {"role": "user", "content": prompt},
        ], temperature=0.0)
        parsed = NluModelPayload.model_validate(_json_object(raw))
        result = parsed.model_dump()
        intent = result["intent"]
        if force_rag and intent in ("sql", "hybrid"):
            intent = "rag"
        result.update(intent=intent, source="layer2_llm")
        if not result.get("normalized_question"):
            result["normalized_question"] = question
        return result
    except Exception:
        # Keep one uniform fail-closed contract.  The broad catch also covers
        # provider/network failures from chat().
        return {
            "intent": "clarify",
            "confidence": 0.5,
            "top2_intent": "",
            "top2_confidence": 0.0,
            **{field: [] for field in _ENTITY_FIELDS},
            "normalized_question": question,
            "source": "layer2_fallback",
        }


def layer2_classify(question: str, context_block: str = "", force_rag: bool = False) -> dict:
    """Compatibility view over the single-call analysis seam."""
    result = layer2_analyze(question, context_block, force_rag)
    return {
        key: result[key]
        for key in ("intent", "confidence", "top2_intent", "top2_confidence", "source")
    }


def layer3_extract_entities(question: str, context_block: str = "") -> dict:
    """Compatibility view; the main pipeline no longer makes a second call."""
    result = layer2_analyze(question, context_block)
    return {
        **{field: result[field] for field in _ENTITY_FIELDS},
        "normalized_question": result.get("normalized_question") or question,
    }


# ── Public API ─────────────────────────────────────────────────────────────────

# Brand/entity keyword scan — deterministic fallback when LLM entity extraction misses entities
# Default list used if config doesn't have keyword_brands
_DEFAULT_BRANDS = frozenset([
    "比亚迪", "特斯拉", "理想", "蔚来", "小鹏", "零跑", "哪吒", "问界", "极氪", "小米",
    "吉利", "长安", "奇瑞", "长城", "五菱", "广汽", "埃安", "深蓝", "腾势", "奔驰",
    "宝马", "奥迪", "丰田", "本田", "大众", "福特", "日产", "上汽", "北汽", "东风",
    "红旗", "领克", "欧拉", "岚图", "智己", "阿维塔", "启源", "银河", "极越",
])


def _get_keyword_brands() -> frozenset:
    """Load keyword brands from config, fallback to hardcoded defaults."""
    cfg = get_cfg()
    cfg_brands = cfg.get("keyword_brands")
    if cfg_brands:
        return frozenset(cfg_brands)
    return _DEFAULT_BRANDS


# Public alias for other modules (e.g. graph.py brand_hint)
_KEYWORD_BRANDS = _DEFAULT_BRANDS

_KEYWORD_MODELS = frozenset([
    "Model Y", "Model 3", "SU7", "L6", "L7", "L9", "MEGA", "海鸥", "海豚",
    "宏光MINIEV", "秦PLUS", "汉EV", "唐EV", "宋PLUS", "宋Pro", "护卫舰",
    "星愿", "极氪001", "极氪007", "问界M7", "问界M9", "理想ONE", "GLC",
    "X5", "Q5", "A6L", "凯美瑞", "雅阁", "帕萨特",
])

_KEYWORD_TIME = frozenset([
    "2025", "2024", "2023", "2026", "2022", "2021", "2020", "2019",
    "今年", "去年", "前年", "本月", "上月", "上个月", "这个月",
])


def _keyword_entity_scan(question: str) -> dict:
    """Deterministic, per-field entity extraction.

    Local matches are always merged with model output rather than only used
    when every model field is empty.  That prevents a partially-correct model
    response (time found, brand missed) from discarding reliable dictionary
    evidence.
    """
    result = {"brands": [], "models": [], "time": [], "metrics": [], "energy_types": []}
    brands = _get_keyword_brands()
    for brand in sorted(brands, key=len, reverse=True):
        if brand in question:
            result["brands"].append(brand)
    for model in sorted(_KEYWORD_MODELS, key=len, reverse=True):
        if model.lower() in question.lower():
            result["models"].append(model)

    for absolute in re.findall(r"20\d{2}(?:年(?:\d{1,2}月)?)?", question):
        normalized = absolute if absolute.endswith(("年", "月")) else f"{absolute}年"
        if normalized not in result["time"]:
            result["time"].append(normalized)
    current_year = datetime.now().year
    relative_time = {
        "今年": f"{current_year}年",
        "去年": f"{current_year - 1}年",
        "前年": f"{current_year - 2}年",
        "本月": "本月",
        "这个月": "本月",
        "上月": "上月",
        "上个月": "上月",
    }
    for time_word in sorted(_KEYWORD_TIME, key=len, reverse=True):
        if time_word in question:
            normalized = relative_time.get(
                time_word,
                f"{time_word}年" if time_word.isdigit() and len(time_word) == 4 else time_word,
            )
            if normalized not in result["time"]:
                result["time"].append(normalized)

    cfg = get_cfg()
    for metric in cfg.get("entity_metric_keywords", []):
        if metric.lower() in question.lower() and metric not in result["metrics"]:
            result["metrics"].append(metric)
    for canonical, aliases in (cfg.get("entity_energy_keywords") or {}).items():
        if any(str(alias).lower() in question.lower() for alias in aliases):
            result["energy_types"].append(canonical)
    return result


def _merge_entity_sources(local: dict, model: dict) -> dict:
    """Merge trusted local lexicon hits with validated model entities."""
    merged: dict[str, list[str]] = {}
    for field in _ENTITY_FIELDS:
        values: list[str] = []
        for source in (local, model):
            for value in source.get(field, []) or []:
                if isinstance(value, str):
                    cleaned = value.strip()
                    if cleaned and cleaned not in values:
                        values.append(cleaned)
        merged[field] = values[:16]
    return merged


def classify(
    question: str,
    history: list = None,
    context_block: str = "",
    last_assistant: str = "",
) -> dict:
    """Layered NLU with zero model calls on deterministic paths and one otherwise.

    Returns dict with keys:
        intent, confidence, entities, is_complete, missing_slots,
        normalized_question, source
    """
    _ = history  # reserved for future multi-turn use; context_block already built by caller
    started = time.perf_counter()

    def finish(payload: dict, *, llm_calls: int) -> dict:
        payload["llm_calls"] = llm_calls
        payload["nlu_latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
        return payload

    local_entities = _keyword_entity_scan(question)

    # Layer 1
    l1 = layer1_prefilter(question, last_assistant)
    if l1 and "intent" in l1:
        return finish({
            "intent": l1["intent"],
            "confidence": l1["confidence"],
            "entities": local_entities,
            "is_complete": True,
            "missing_slots": [],
            "normalized_question": question,
            "source": l1["source"],
        }, llm_calls=0)
    force_rag = bool(l1 and l1.get("force_rag"))

    # Layer 2
    hint = None if force_rag else deterministic_intent_hint(question, context_block)
    if hint == "clarify":
        return finish({
            "intent": "clarify",
            "confidence": 1.0,
            "entities": local_entities,
            "is_complete": False,
            "missing_slots": ["缺少明确对象或问题，请补充你想分析的车型、指标或背景"],
            "normalized_question": question,
            "source": "deterministic_hint",
        }, llm_calls=0)
    if hint:
        l2 = {
            "intent": hint,
            "confidence": 1.0,
            "top2_intent": "",
            "top2_confidence": 0.0,
            "source": "deterministic_hint",
            **{field: [] for field in _ENTITY_FIELDS},
            "normalized_question": question,
        }
        llm_calls = 0
    else:
        l2 = layer2_analyze(question, context_block, force_rag=force_rag)
        llm_calls = 1

    # Confidence gate → clarify if ambiguous
    if not _confidence_gate(l2):
        return finish({
            "intent": "clarify",
            "confidence": l2["confidence"],
            "entities": local_entities,
            "is_complete": False,
            "missing_slots": ["问题意图不明确，请描述得更具体"],
            "normalized_question": question,
            "source": "confidence_gate",
        }, llm_calls=llm_calls)

    model_entities = {field: l2.get(field, []) for field in _ENTITY_FIELDS}
    entities = _merge_entity_sources(local_entities, model_entities)

    # Layer 5 (before completeness check so forced rag skips slot check)
    # Only apply business rules to data intents, not chat/clarify
    if l2["intent"] in ("sql", "hybrid", "rag"):
        final_intent = layer5_business_rules(l2["intent"], question)
    else:
        final_intent = l2["intent"]

    # A greeting plus a recognised business entity is not pure small talk.  If
    # no actual question was expressed, ask for scope instead of silently
    # routing to chat ("你好比亚迪").
    if final_intent == "chat" and any(entities.get(k) for k in ("brands", "models")):
        final_intent = "clarify"
        source = "mixed_greeting_guard"
    else:
        source = l2["source"]

    # Layer 4
    is_complete, missing = layer4_check_completeness(final_intent, entities, question)
    if not is_complete and final_intent in ("sql", "hybrid"):
        final_intent = "clarify"
    if final_intent == "clarify" and not missing:
        missing = ["请说明你想查询销量、价格，还是了解政策、口碑或行业分析"]

    return finish({
        "intent": final_intent,
        "confidence": l2["confidence"],
        "entities": entities,
        "is_complete": False if final_intent == "clarify" else is_complete,
        "missing_slots": missing,
        "normalized_question": l2.get("normalized_question") or question,
        "source": source,
    }, llm_calls=llm_calls)
