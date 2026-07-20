"""5层企业级 NLU 引擎。

Layer 1: 规则预筛（问候/超纲快速通道，不调 LLM）
Layer 2: LLM 意图分类（单一任务，few-shot 向量检索增强）
Layer 3: 实体抽取（独立 LLM 调用，单一任务）
Layer 4: 槽位完整性检查（规则，来自 YAML）
Layer 5: 业务规则覆盖（来自 YAML，业务同学可维护）
"""
import json
import threading
from pathlib import Path

import numpy as np
import yaml

from .config import NLU_CONFIG_PATH
from .llm import chat
from .rag.embed import embed_query, embed_passages

_cfg_lock = threading.Lock()
_cfg = None

_few_shot_lock = threading.Lock()
_few_shot_embeddings = None   # np.ndarray shape (N, embed_dim)
_few_shot_examples = None     # list[dict]


def _load_config() -> dict:
    global _cfg
    with _cfg_lock:
        if _cfg is not None:
            return _cfg
        path = Path(NLU_CONFIG_PATH)
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        _cfg = (raw or {}).get("nlu", {})
    # Embed few-shot examples outside _cfg_lock to avoid blocking all threads
    _init_few_shot(_cfg)
    return _cfg


def _init_few_shot(cfg: dict) -> None:
    """Pre-embed few-shot examples into in-memory numpy array. Uses _few_shot_lock."""
    global _few_shot_embeddings, _few_shot_examples
    with _few_shot_lock:
        if _few_shot_embeddings is not None:
            return
        examples = cfg.get("few_shot_examples") or []
        if not examples:
            return
        texts = [e.get("question", "") for e in examples if e.get("question")]
        vecs = embed_passages(texts)
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
    if len(q) <= 8 and any(q.startswith(g) for g in greetings):
        return {"intent": "chat", "confidence": 1.0, "source": "layer1_greeting"}

    no_data_signals = cfg.get("no_data_signals", [])
    if last_assistant and any(sig in last_assistant for sig in no_data_signals):
        return {"force_rag": True}

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


# ── Layer 2: LLM 意图分类（单一任务）─────────────────────────────────────────

_CLASSIFY_SYS = """\
你是新能源汽车市场情报系统的意图分类器。只做分类，不做实体提取。返回严格 JSON（无其他文字）。

JSON 格式：
{"intent":"sql|rag|hybrid|chat|clarify","confidence":0.95,"top2_intent":"rag","top2_confidence":0.08}

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
"""


def layer2_classify(question: str, context_block: str = "", force_rag: bool = False) -> dict:
    """单任务 LLM 分类 + few-shot 增强。FAIL-SAFE：异常返回 clarify。"""
    try:
        few_shot = _retrieve_few_shot(question)
        prompt = _build_few_shot_block(few_shot)
        if context_block:
            prompt += context_block + "\n\n"
        prompt += question

        raw = chat([
            {"role": "system", "content": _CLASSIFY_SYS},
            {"role": "user", "content": prompt},
        ], temperature=0.0)
        s, e = raw.find("{"), raw.rfind("}") + 1
        if s < 0 or e <= s:
            raise ValueError("no JSON in response")
        r = json.loads(raw[s:e])
        intent = r.get("intent", "clarify")
        if intent not in ("sql", "rag", "hybrid", "chat", "clarify"):
            intent = "clarify"
        if force_rag and intent in ("sql", "hybrid"):
            intent = "rag"
        return {
            "intent": intent,
            "confidence": min(1.0, max(0.0, float(r.get("confidence", 0.8)))),
            "top2_intent": r.get("top2_intent", ""),
            "top2_confidence": float(r.get("top2_confidence") or 0.0),
            "source": "layer2_llm",
        }
    except Exception:
        return {"intent": "clarify", "confidence": 0.5,
                "top2_intent": "", "top2_confidence": 0.0,
                "source": "layer2_fallback"}


# ── Layer 3: 实体抽取（独立 LLM 调用）────────────────────────────────────────

_ENTITY_SYS = """\
你是实体提取器，只做实体提取和规范化，不做意图判断。从新能源汽车问题中提取实体，返回严格 JSON（无其他文字）。

JSON 格式：
{"brands":[],"models":[],"time":[],"metrics":[],"energy_types":[],"normalized_question":"规范化后的问题"}

规范化规则：su7/SU7不变, byd/BYD→比亚迪, 今年→2026年, 去年→2025年, 前年→2024年
只从当前问题提取实体，忽略历史记录中的实体。
"""


def layer3_extract_entities(question: str, context_block: str = "") -> dict:
    """独立 LLM 实体抽取。FAIL-SAFE：异常返回空实体 + 原始问题。"""
    prompt = (context_block + "\n\n" if context_block else "") + question
    empty = {"brands": [], "models": [], "time": [], "metrics": [],
             "energy_types": [], "normalized_question": question}
    try:
        raw = chat([
            {"role": "system", "content": _ENTITY_SYS},
            {"role": "user", "content": prompt},
        ], temperature=0.0)
        s, e = raw.find("{"), raw.rfind("}") + 1
        if s < 0 or e <= s:
            return empty
        r = json.loads(raw[s:e])
        return {
            "brands": r.get("brands") or [],
            "models": r.get("models") or [],
            "time": r.get("time") or [],
            "metrics": r.get("metrics") or [],
            "energy_types": r.get("energy_types") or [],
            "normalized_question": r.get("normalized_question") or question,
        }
    except Exception:
        return empty


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
    """Deterministic keyword scan for brand/model/time entities.
    Used as fallback when LLM entity extraction returns empty results.
    Brands loaded from config (nlu.yaml keyword_brands) for easy extension.
    """
    result = {"brands": [], "models": [], "time": [], "metrics": [], "energy_types": []}
    brands = _get_keyword_brands()
    for brand in brands:
        if brand in question:
            result["brands"].append(brand)
    for model in _KEYWORD_MODELS:
        if model.lower() in question.lower():
            result["models"].append(model)
    for time_word in _KEYWORD_TIME:
        if time_word in question:
            result["time"].append(time_word)
    return result


def classify(
    question: str,
    history: list = None,
    context_block: str = "",
    last_assistant: str = "",
) -> dict:
    """5层 NLU 完整流程。

    Returns dict with keys:
        intent, confidence, entities, is_complete, missing_slots,
        normalized_question, source
    """
    _ = history  # reserved for future multi-turn use; context_block already built by caller

    # Layer 1
    l1 = layer1_prefilter(question, last_assistant)
    if l1 and "intent" in l1:
        return {"intent": l1["intent"], "confidence": l1["confidence"],
                "entities": {}, "is_complete": True, "missing_slots": [],
                "normalized_question": question, "source": l1["source"]}
    force_rag = bool(l1 and l1.get("force_rag"))

    # Layer 2
    l2 = layer2_classify(question, context_block, force_rag=force_rag)

    # Confidence gate → clarify if ambiguous
    if not _confidence_gate(l2):
        return {"intent": "clarify", "confidence": l2["confidence"],
                "entities": {}, "is_complete": False,
                "missing_slots": ["问题意图不明确，请描述得更具体"],
                "normalized_question": question, "source": "confidence_gate"}

    # Layer 3 (only for data-related intents)
    if l2["intent"] in ("sql", "rag", "hybrid"):
        l3 = layer3_extract_entities(question, context_block)
        # Fallback: if LLM entity extraction returned empty brands, use keyword scan
        if not any(l3.get(k) for k in ("brands", "models", "time", "metrics", "energy_types")):
            kw_entities = _keyword_entity_scan(question)
            if any(kw_entities.get(k) for k in ("brands", "models", "time")):
                l3 = {**l3, **kw_entities}
    else:
        l3 = {"brands": [], "models": [], "time": [], "metrics": [],
              "energy_types": [], "normalized_question": question}

    # Layer 5 (before completeness check so forced rag skips slot check)
    # Only apply business rules to data intents, not chat/clarify
    if l2["intent"] in ("sql", "hybrid", "rag"):
        final_intent = layer5_business_rules(l2["intent"], question)
    else:
        final_intent = l2["intent"]

    # Layer 4
    is_complete, missing = layer4_check_completeness(final_intent, l3, question)
    if not is_complete and final_intent in ("sql", "hybrid"):
        final_intent = "clarify"

    return {
        "intent": final_intent,
        "confidence": l2["confidence"],
        "entities": {k: l3[k] for k in ("brands", "models", "time", "metrics", "energy_types")},
        "is_complete": is_complete or final_intent not in ("sql", "hybrid"),
        "missing_slots": missing,
        "normalized_question": l3.get("normalized_question", question),
        "source": l2["source"],
    }
