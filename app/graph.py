"""LangGraph 双脑编排（见 docs/technical-design.md 第 2 节）。

为什么用状态图而非 if-else（§7.1）：
- 显式 State + 节点 + 条件边，复杂多步流程可控可回溯；
- 天然表达「环」——Text2SQL 自校验重试是带环流程（exec_sql ⇄ fix_sql ⇄ verify_sql）；
- 支持「澄清-续问」——clarify 节点反问后结束本轮（→END）；用户的补充作为带 history 的**新一轮请求**
  进来，intent_router 借 history 理解指代后重新路由（**对话级澄清**，状态持久化在 message 表/前端会话）；
- 支持「并行 join」——hybrid 并行跑两个脑链，compose 合并；
- 可观测——每个节点把决策/SQL/检索/重试写入 State.trace。

> 关于「图级挂起/恢复」（面试高频追问）：LangGraph 提供 checkpointer（MemorySaver/PostgresSaver）+ interrupt()
> 做真正的图内断点恢复。本项目**刻意没用**——澄清是对话级的（状态已落 message 表 + 前端会话），再叠一层
> LangGraph 检查点是重复持久化，且 SSE 流式下管理恢复点复杂度高、收益低。**何时该上**：若要做图内多轮
> 挂起（如分步收集多个查询槽位、Human-in-the-loop 审批），再引入 checkpointer + thread_id=conversation_id。

状态流转（§7.5）：
  sql    → schema_link → gen_sql → exec_sql → verify_sql → chart → insight → compose
             exec 失败且可重试 ─┐        ┌─ verify 拒绝且可重试
                                └→ fix_sql ─→ exec_sql
             任一重试耗尽 → insight（诚实降级）
  rag    → rag_retrieve → rag_answer → compose
  hybrid → 上述两条分支并行，compose(defer=True) 只执行一次
  clarify / chat → 对应节点 → END
"""
import json as _json
import logging
import operator
import re
import threading
from typing import Annotated, TypedDict

from langgraph.graph import StateGraph, START, END

from .llm import chat
from .config import MAX_SQL_RETRY
from .schema_linking import link_schema
from .sql_guard import ensure_safe, with_limit, UnsafeSQLError
from .db import run_query
from .text2sql import (
    DOMAIN,
    FEWSHOT,
    SYS as SQL_SYS,
    _brand_entity_hint,
    _exact_brand_names,
    _extract_sql,
)
from .charts import recommend_chart

_log = logging.getLogger("cheshijing.graph")


# ============================================================ State（§7.2）
class AgentState(TypedDict, total=False):
    question: str                        # 当前问题
    history: list                        # 多轮上下文（原始消息列表）
    user_id: int                         # RAG 多租户隔离用
    # —— NLU 输出（新增）——
    intent: str                          # sql / rag / hybrid / clarify / chat
    confidence: float                    # 意图置信度 0-1
    entities: dict                       # 本轮提取实体 {brands,models,time,metrics,energy_types}
    active_entities: dict                # 跨轮累积实体记忆（会话级）
    uses_history_entities: bool          # 本轮是否确实含指代/省略，需要继承历史实体
    normalized_question: str            # LLM 规范化后的问题（实体补全/消歧）
    # —— 业务状态 ——
    clarify_question: str               # 需澄清时的反问
    linked_schema: str                  # Schema Linking 结果
    sql: str                            # 生成的 SQL
    cols: list                          # 结果列
    rows: list                          # 结果行
    sql_error: str                      # 执行/校验错误
    retry_count: int                    # 已重试次数
    sql_verified: bool                  # 语义自校验结果
    chunks: list                        # RAG 归并后的父块上下文
    citations: list                     # 引用
    has_answer: bool                    # RAG 是否有依据
    chart: dict                         # 图表描述符
    insight: str                        # 洞察归因
    rag_answer: str                     # 知识脑答案
    final_answer: str                   # 汇总答案
    degraded: bool                      # SQL 重试耗尽降级标记
    no_data: bool                       # SQL 执行成功但结果集为空（不强制覆盖 intent）
    task_id: str                        # 无数据时启动的智能采集任务
    trace: Annotated[list, operator.add]  # 每步留痕（并行分支用 add 合并）


def _t(node, **kw):
    return {"node": node, **kw}


# ============================================================ 实体记忆工具函数
_KNOWN_BRANDS = frozenset([
    "比亚迪", "特斯拉", "理想", "蔚来", "小鹏", "零跑", "哪吒", "问界", "极氪", "小米",
    "吉利", "长安", "奇瑞", "长城", "五菱", "广汽", "埃安", "深蓝", "腾势", "奔驰",
    "宝马", "奥迪", "丰田", "本田", "大众", "福特", "日产", "上汽", "北汽", "东风",
    "红旗", "领克", "欧拉", "岚图", "智己", "阿维塔", "启源", "银河", "极越",
])
_KNOWN_MODELS = [
    "Model Y", "Model 3", "SU7", "L6", "L7", "L9", "MEGA", "海鸥", "海豚",
    "宏光MINIEV", "秦PLUS", "汉EV", "唐EV", "宋PLUS", "宋Pro", "海洋网", "护卫舰",
    "星愿", "极氪001", "极氪007", "问界M7", "问界M9", "理想ONE",
]


def _extract_entities_from_text(text: str) -> dict:
    """轻量关键词扫描历史消息，提取已提及的品牌/车系（不调LLM）。"""
    tl = text.lower()
    brands = [b for b in _KNOWN_BRANDS if b in text]
    models = [m for m in _KNOWN_MODELS if m.lower() in tl]
    return {"brands": brands[:5], "models": models[:5]}


def _merge_entities(existing: dict, new_entities: dict) -> dict:
    """把本轮实体合并进累积记忆（去重，每类最多保留8个最近值）。"""
    merged = {}
    keys = ("brands", "models", "time", "metrics", "energy_types")
    for k in keys:
        seen = list(existing.get(k) or [])
        for v in (new_entities.get(k) or []):
            if v and v not in seen:
                seen.append(v)
        merged[k] = seen[-8:]
    return merged


def _build_active_entities_from_history(history: list) -> dict:
    """从历史消息提取累积实体（会话开始时初始化用）。"""
    combined = " ".join((m.get("content") or "") for m in history)
    return _extract_entities_from_text(combined)


_CONTEXT_REFERENCE_MARKERS = (
    "它", "这辆", "那辆", "这款", "那款", "该车", "该品牌", "这个品牌",
    "那个品牌", "上述", "上面", "前面", "前者", "后者", "这个结论",
    "这个数据", "继续", "进一步", "再看", "换成", "按月拆开", "对比去年",
)


def _needs_history_context(question: str) -> bool:
    """Only inherit conversation entities for explicit pronouns or elliptical follow-ups."""
    q = (question or "").strip()
    if not q:
        return False
    if any(marker in q for marker in _CONTEXT_REFERENCE_MARKERS):
        return True
    if q.startswith(("那", "那么", "然后")) or q.endswith(("呢", "又如何", "怎么样呢")):
        return True
    # Very short follow-ups such as “销量怎么样” or “价格多少” are elliptical.
    return len(q) <= 10 and bool(re.search(r"(销量|价格|排名|口碑|趋势).*(多少|如何|怎样|怎么样)?[？?]?$", q))


def _filter_entities_to_question(entities: dict, question: str) -> dict:
    """Drop brand/model values hallucinated from history for a standalone question."""
    q_lower = (question or "").lower()
    filtered = dict(entities or {})
    for key in ("brands", "models"):
        filtered[key] = [
            value for value in (filtered.get(key) or [])
            if str(value).lower() in q_lower
        ]
    return filtered


# ============================================================ 对话上下文构建
def _history_block(state) -> str:
    """
    构建对话上下文块，注入两层信息：
    1. 实体记忆（本会话已识别品牌/车系）——解决「那辆车」「它」跨轮指代
    2. 近期消息摘要——解决追问语境
    """
    if state.get("uses_history_entities") is False:
        return ""

    h = state.get("history") or []
    active = state.get("active_entities") or {}

    parts = []

    # 层1：结构化实体记忆（最高价值，LLM 可直接引用）
    entity_lines = []
    if active.get("brands"):
        entity_lines.append(f"  · 本会话已提及品牌：{', '.join(active['brands'])}")
    if active.get("models"):
        entity_lines.append(f"  · 本会话已提及车系：{', '.join(active['models'])}")
    if active.get("time"):
        entity_lines.append(f"  · 本会话已提及时间：{', '.join(active['time'])}")
    if active.get("energy_types"):
        entity_lines.append(f"  · 本会话已提及能源类型：{', '.join(active['energy_types'])}")
    if entity_lines:
        parts.append("【实体记忆】（代词/省略时必须从此处补全实体）\n" + "\n".join(entity_lines))

    # 层1.5：长期记忆（从 history 中提取 system 角色的 memory_block）
    for m in h:
        if m.get("role") == "system" and m.get("content"):
            parts.append(m["content"].strip())

    # 层2：最近消息（截断，只保留语义上有用的部分）
    user_msgs = [m for m in h if m.get("role") != "system"]
    if user_msgs:
        lines = []
        for m in user_msgs[-8:]:
            role = "用户" if m.get("role") == "user" else "助手"
            c = (m.get("content") or "").strip().replace("\n", " ")[:300]
            if c:
                lines.append(f"{role}：{c}")
        if lines:
            parts.append("【近期对话】\n" + "\n".join(lines))

    if not parts:
        return ""

    return (
        "\n\n".join(parts) + "\n\n"
        "指令：若本轮问题含代词（「那辆车」「它」「那个品牌」「上面那个」）或省略了实体，"
        "必须从实体记忆中补全，不要询问用户。\n\n"
    )


# ── Backwards-compat shims (test_graph.py imports these) ──────────────────────
from .nlu import get_cfg as _get_nlu_cfg


def _get_config_list(key):
    return _get_nlu_cfg().get(key, [])


try:
    _greetings = _get_config_list("greeting_prefixes")
    _GREETING_PREFIXES = tuple(_greetings) if _greetings is not None else (
        "你好", "您好", "早安", "晚安", "早上好", "再见", "拜拜")
    _no_data = _get_config_list("no_data_signals")
    _NO_DATA_SIGNALS = frozenset(_no_data) if _no_data is not None else frozenset([
        "未查询到", "没有找到", "未检索到", "no data", "not found", "no results",
        "no records", "0条结果", "不在覆盖范围", "不在数据库", "未在知识库中检索到"])
except Exception:
    _GREETING_PREFIXES = ("你好", "您好", "早安", "晚安", "早上好", "再见", "拜拜")
    _NO_DATA_SIGNALS = frozenset([
        "未查询到", "没有找到", "未检索到", "no data", "not found", "no results",
        "no records", "0条结果", "不在覆盖范围", "不在数据库", "未在知识库中检索到"])


def _classify_intent(question: str, context_block: str) -> dict:
    """Shim: delegates to nlu.classify(). Kept for test_graph.py compatibility."""
    from .nlu import classify as _nlu_classify
    return _nlu_classify(question=question, context_block=context_block)


def _build_clarify_question_from_slots(slots: list) -> str:
    base = "您的问题信息不够完整，需要补充以下内容才能给出准确答案：\n\n"
    if slots:
        base += "\n".join(f"· {s}" for s in slots) + "\n\n"
    base += (
        "示例完整问法：\n"
        "✓「2025年纯电销量Top10」\n"
        "✓「比亚迪各车系今年销量对比」\n"
        "✓「理想L6和小米SU7谁卖得多」"
    )
    return base


# ============================================================ 多轮改写（Query Rewrite）

_REWRITE_SYS = """\
你是多轮对话改写器。将用户的新消息改写为一句独立、完整的问题（不依赖上下文即可理解）。

规则：
1. 补全省略的实体（品牌/车系/时间）——从对话历史中找到被省略的主语/宾语
2. 解析代词（"它""那个""这个品牌"）为具体实体
3. 保留用户原始意图中的新维度（月份/趋势/对比/口碑等）
4. 如果问题已经完整独立，原样返回

特殊情况——纯元信息追问：
- 用户只是在问上一条回答本身的属性（时间范围、数据来源、计算方式、为什么是这个数）
- 不需要查数据库/检索文档就能回答
- 例："这是几几年的""怎么算的""数据来源是哪""为什么是这个数"
- 此时 is_meta=true，rewritten 保持原文

只输出 JSON：{"rewritten": "改写后的完整问题", "is_meta": false}"""


def _rewrite_query(question: str, history: list) -> dict:
    """多轮改写：将省略/代词问题改写为独立完整问题，或识别为纯元信息追问。"""
    last_msgs = []
    for m in history[-6:]:
        role = "用户" if m.get("role") == "user" else "助手"
        last_msgs.append(f"{role}：{(m.get('content') or '')[:300]}")
    context = "\n".join(last_msgs)
    try:
        raw = chat([
            {"role": "system", "content": _REWRITE_SYS},
            {"role": "user", "content": f"对话历史：\n{context}\n\n新消息：{question}"},
        ], temperature=0.0)
        s, e = raw.find("{"), raw.rfind("}") + 1
        if s >= 0 and e > s:
            parsed = _json.loads(raw[s:e])
            return {
                "rewritten": parsed.get("rewritten", question),
                "is_meta": bool(parsed.get("is_meta", False)),
            }
    except Exception:
        pass
    return {"rewritten": question, "is_meta": False}


# ============================================================ 意图路由节点
def intent_router(state: AgentState):
    """意图路由：委托给 nlu.classify()，保留跨轮实体记忆更新。"""
    q = state["question"]
    history = state.get("history") or []
    uses_history = bool(history and _needs_history_context(q))

    # 只有明确含指代/省略时才改写。完整独立问题必须与旧主题隔离。
    if uses_history:
        rw = _rewrite_query(q, history)
        if rw["is_meta"]:
            return {
                "intent": "chat",
                "_is_followup": True,
                "confidence": 0.9,
                "entities": {},
                "active_entities": state.get("active_entities") or {},
                "uses_history_entities": True,
                "normalized_question": q,
                "retry_count": 0,
                "trace": [_t("intent_router", intent="chat", path="meta_question",
                             rewritten=q)],
            }
        q = rw["rewritten"]

    active_ents = state.get("active_entities") or _build_active_entities_from_history(history)
    ctx = _history_block({
        **state,
        "active_entities": active_ents,
        "uses_history_entities": uses_history,
    }) if uses_history else ""

    last_assistant = ""
    for m in reversed(history):
        if m.get("role") == "assistant":
            last_assistant = (m.get("content") or "")[:300]
            break

    result = _classify_intent(q, ctx)

    intent = result["intent"]
    entities = result.get("entities") or {}
    if not uses_history:
        entities = _filter_entities_to_question(entities, q)
    source = result.get("source", "")

    # No-data guard: last assistant had no-data signal → override sql/hybrid → rag
    if uses_history and any(sig in last_assistant for sig in _NO_DATA_SIGNALS):
        if intent in ("sql", "hybrid"):
            intent = "rag"
            result["confidence"] = min(result.get("confidence", 0.8), 0.7)

    # Slot completeness: is_complete=False + sql/hybrid → clarify
    is_complete = result.get("is_complete", True)
    if intent in ("sql", "hybrid") and not is_complete:
        intent = "clarify"

    # Topic switches replace active memory; true follow-ups accumulate it.
    new_active = _merge_entities(active_ents if uses_history else {}, entities)

    # Build trace: distinguish greeting fast-path from LLM-classified
    if source == "layer1_greeting":
        trace_entry = _t("intent_router", intent=intent, path="greeting_precheck")
        confidence = result.get("confidence", 1.0)
    else:
        confidence = result.get("confidence", 0.8)
        llm_classified = bool(
            result.get(
                "llm_calls",
                1 if not source else int(source == "layer2_llm"),
            )
        )
        trace_entry = _t("intent_router",
                         intent=intent,
                         confidence=round(confidence, 2),
                         entities=entities,
                         is_complete=result.get("is_complete", True),
                         nlu_source=source or "unknown",
                         nlu_latency_ms=result.get("nlu_latency_ms"),
                         nlu_llm_calls=result.get("llm_calls"),
                         llm_classified=llm_classified)

    upd: dict = {
        "intent": intent,
        "confidence": confidence,
        "entities": entities,
        "active_entities": new_active,
        "uses_history_entities": uses_history,
        "normalized_question": result.get("normalized_question", q),
        "retry_count": 0,
        "trace": [trace_entry],
    }
    if intent == "clarify":
        upd["clarify_question"] = _build_clarify_question_from_slots(result.get("missing_slots") or [])
    return upd


_FOLLOWUP_SYS = (
    "你是汽车数据助手。用户在追问上一条回答的细节（时间范围、数据来源、计算方式等）。"
    "请根据对话历史直接回答，不要重新查数据。简洁、直接。"
)


def chitchat(state: AgentState):
    """问候/闲聊/追问 → 有历史且 is_followup=True→LLM回答；否则模板。"""
    history = state.get("history") or []
    q = state.get("question", "")
    if history and state.get("_is_followup"):
        msgs = [{"role": "system", "content": _FOLLOWUP_SYS}]
        for m in history[-6:]:
            msgs.append({"role": m.get("role", "user"), "content": (m.get("content") or "")[:500]})
        msgs.append({"role": "user", "content": q})
        answer = chat(msgs, temperature=0.3)
        return {"final_answer": answer, "trace": [_t("chitchat", mode="followup")]}
    return {"final_answer":
            "我是「车市镜」——专注新能源汽车销量数据分析与行业知识问答的助手，暂时只聊车市相关的话题～\n"
            "你可以这样问我：\n"
            "· 数据：『2025年纯电销量 Top10』『比亚迪各车系今年卖了多少』\n"
            "· 解读：『小米SU7 口碑怎么样』『最近的购车补贴政策怎么说』",
            "trace": [_t("chitchat")]}


def clarify(state: AgentState):
    """信息不足反问，挂起等用户（→ END）。"""
    return {"final_answer": state.get("clarify_question", "请补充更多信息。"),
            "trace": [_t("clarify")]}


def schema_link(state: AgentState):
    """语义 Schema Linking（§4.1）：实体感知 + 中文语义描述，比原版关键词匹配准确。"""
    entities = state.get("entities") or {}
    # 优先用规范化后的问题做 schema linking（实体已被 LLM 补全）
    q = state.get("normalized_question") or state["question"]
    schema = link_schema(q, entities=entities)
    return {"linked_schema": schema, "trace": [_t("schema_link",
            tables_chars=len(schema), entities_used=bool(entities))]}


def _entity_injection(entities: dict) -> str:
    """把 NLU 提取的实体注入到 SQL 生成提示，减少 LLM 幻造列名/实体。"""
    if not entities:
        return ""
    lines = ["本轮已识别实体（SQL WHERE 条件中必须使用这些实体，不得遗漏）："]
    if entities.get("brands"):
        lines.append(f"  · 品牌：{', '.join(entities['brands'])}")
    if entities.get("models"):
        lines.append(f"  · 车系：{', '.join(entities['models'])}")
    if entities.get("time"):
        lines.append(f"  · 时间：{', '.join(entities['time'])}")
    if entities.get("energy_types"):
        lines.append(f"  · 能源类型：{', '.join(entities['energy_types'])}")
    if entities.get("metrics"):
        lines.append(f"  · 指标：{', '.join(entities['metrics'])}")
    return "\n".join(lines) + "\n\n"


def _gen_sql_messages(state):
    entities = state.get("entities") or {}
    entity_ctx = _entity_injection(entities)
    # 使用规范化问题（实体已被补全，更有助于 SQL 生成）
    q = state.get("normalized_question") or state["question"]
    return [
        {"role": "system", "content": SQL_SYS},
        {"role": "user", "content": (
            f"{DOMAIN}\n\n{_brand_entity_hint(q)}{entity_ctx}{FEWSHOT}\n"
            f"可用表结构:\n{state['linked_schema']}\n\n"
            f"{_history_block(state)}Q: {q}\nSQL:"
        )},
    ]


def gen_sql(state: AgentState):
    """生成 SQL（§4.2/4.3）。"""
    sql = _extract_sql(chat(_gen_sql_messages(state), temperature=0.0))
    return {"sql": sql, "trace": [_t("gen_sql", sql=sql)]}


def exec_sql(state: AgentState):
    """护栏校验 + 只读执行（§4.4）。成功写 cols/rows，失败写 sql_error。"""
    try:
        safe = with_limit(ensure_safe(state["sql"]))
        cols, rows = run_query(safe)
        return {"sql": safe, "cols": cols, "rows": rows, "sql_error": None,
                "trace": [_t("exec_sql", ok=True, rows=len(rows))]}
    except (UnsafeSQLError, Exception) as e:
        return {"sql_error": str(e), "trace": [_t("exec_sql", ok=False, error=str(e)[:120])]}


def fix_sql(state: AgentState):
    """把错误回喂模型修正 SQL（自校验重试环，§4.5）。"""
    msgs = _gen_sql_messages(state) + [
        {"role": "assistant", "content": state.get("sql", "")},
        {"role": "user", "content": f"上面的 SQL 执行报错：{state['sql_error']}\n请修正后只输出一条 SELECT。"},
    ]
    sql = _extract_sql(chat(msgs, temperature=0.0))
    n = state.get("retry_count", 0) + 1
    return {"sql": sql, "retry_count": n, "trace": [_t("fix_sql", attempt=n, sql=sql)]}


_VERIFY_SYS = (
    "你是 SQL 审核员。给你一个『自然语言问题』和这条 SQL『实际查询结果(列+前几行)』，"
    "判断结果是否真的回答了问题——重点看：过滤口径(品牌/车系/时间/能源类型)有没有错、"
    "聚合维度对不对、是不是答非所问。结果为空但问题本身合理(可能就是没数据)也算 ok=true。"
    "只输出 JSON：{\"ok\": true/false, \"reason\": \"简短中文原因\"}，不要解释、不要代码块。"
)


def _has_meaningful_rows(rows: list | None) -> bool:
    """Treat aggregate-only NULL rows as empty while preserving COUNT(*) = 0."""
    if not rows:
        return False
    for row in rows:
        if isinstance(row, dict):
            values = row.values()
        elif isinstance(row, (list, tuple)):
            values = row
        else:
            values = (row,)
        if any(value is not None for value in values):
            return True
    return False


def _validate_sql_shape(
    question: str, sql: str, cols: list | None = None, rows: list | None = None
) -> tuple[bool, str]:
    """Deterministic semantic checks for common 'executable but wrong' SQL shapes."""
    from sqlglot import exp, parse_one

    q = (question or "").strip()
    try:
        tree = parse_one(sql, read="sqlite")
    except Exception as exc:
        return False, f"SQL 无法解析：{exc}"

    top_match = re.search(r"(?i)top\s*(\d+)", q) or re.search(r"前\s*(\d+)", q)
    if not top_match:
        top_match = re.search(r"(?:最高|最多)(?:的)?\s*(\d+)", q)
    if top_match:
        requested = int(top_match.group(1))
        if tree.args.get("order") is None:
            return False, f"Top{requested} 查询缺少 ORDER BY 排序"
        aggregates = list(tree.find_all(exp.AggFunc))
        if aggregates and tree.args.get("group") is None:
            return False, f"Top{requested} 聚合查询缺少 GROUP BY 维度"
        limit_node = tree.args.get("limit")
        try:
            actual_limit = int(limit_node.expression.this) if limit_node else None
        except (AttributeError, TypeError, ValueError):
            actual_limit = None
        if actual_limit is None or actual_limit > requested:
            return False, f"Top{requested} 查询的 LIMIT 必须不大于 {requested}"

    sql_lower = (sql or "").lower()
    sql_compact = re.sub(r"\s+", "", sql_lower)
    for brand_name in _exact_brand_names(q):
        brand_filter = re.compile(
            rf"(?:\b\w+\.)?brand_name\s*(?:like|=)\s*"
            rf"['\"]%?{re.escape(brand_name.lower())}%?['\"]",
            flags=re.I,
        )
        brand_in = re.compile(
            rf"(?:\b\w+\.)?brand_name\s+in\s*\([^)]*"
            rf"['\"]{re.escape(brand_name.lower())}['\"]",
            flags=re.I,
        )
        if not brand_filter.search(sql_lower) and not brand_in.search(sql_lower):
            return (
                False,
                f"完整品牌“{brand_name}”必须整体过滤 dim_brand.brand_name，"
                "不能拆成母品牌与车系关键词",
            )
    energy_requirements = {
        "纯电": ("纯电", 1),
        "插混": ("插混", 2),
        "增程": ("增程", 3),
    }
    mentioned_energy = [
        (label, literal, code)
        for label, (literal, code) in energy_requirements.items()
        if label in q
    ]
    asks_overall_series_winner = (
        "品牌" not in q
        and any(token in q for token in ("销量第一", "销量最高", "卖得最多"))
        and not mentioned_energy
    )
    if asks_overall_series_winner:
        where_sql = str(tree.args.get("where") or "").lower()
        if re.search(r"(?:\b\w+\.)?rank\s*=\s*1\b", where_sql):
            return (
                False,
                "rank=1 只是能源类型分区冠军；未指定能源类型的销量冠军"
                "必须按 volume 或 SUM(volume) 全局降序",
            )
        if tree.args.get("order") is None:
            return False, "全市场销量冠军查询必须按销量降序"
        limit_node = tree.args.get("limit")
        try:
            winner_limit = int(limit_node.expression.this) if limit_node else None
        except (AttributeError, TypeError, ValueError):
            winner_limit = None
        if winner_limit != 1:
            return False, "全市场销量冠军查询必须 LIMIT 1"
    # 单动力类型问题必须有精确过滤。多动力类型问题由下面的分组/多列规则
    # 约束，不能把合法的 IN (1,2,3) 误判成“缺少纯电过滤”。
    if len(mentioned_energy) == 1:
        label, literal, code = mentioned_energy[0]
        has_numeric_filter = bool(
            re.search(rf"new_energy_type={code}(?!\d)", sql_compact)
            or re.search(
                rf"new_energy_typein\([^)]*(?<!\d){code}(?!\d)",
                sql_compact,
            )
        )
        if literal.lower() not in sql_lower and not has_numeric_filter:
            return False, f"问题要求{label}口径，但 SQL 没有对应过滤条件"

    for year in re.findall(r"20\d{2}", q):
        if year not in sql:
            return False, f"问题要求 {year} 年，但 SQL 没有对应时间过滤"

    cumulative = any(token in q for token in ("累计销量", "总销量", "一共卖了", "总共卖了"))
    asks_breakdown = any(token in q for token in (
        "各车系", "分别", "对比", "谁", "排行", "排名", "Top", "top", "前十", "每个",
        "各动力类型", "各有", "哪个品牌", "哪家品牌", "最高", "最多", "趋势",
    ))
    if cumulative and not asks_breakdown:
        if tree.args.get("group") is not None or len(cols or []) > 1:
            return False, "累计销量要求单一汇总值，不应按车系/品牌分组返回多列"
        explicit_time = bool(
            re.search(r"20\d{2}|今年|去年|前年|本月|上月|近\d+[年月]", q)
        )
        where_sql = str(tree.args.get("where") or "").lower()
        if not explicit_time and re.search(
            r"(?:\byear\b|\bmonth\b|\bdate_id\b|\bym\b)", where_sql
        ):
            return False, "未指定时间的累计销量应覆盖全部数据，不应额外限定时间"

    monthly_trend = any(token in q for token in ("每月", "按月", "月度趋势"))
    if monthly_trend:
        group_sql = str(tree.args.get("group") or "").lower()
        order_sql = str(tree.args.get("order") or "").lower()
        has_month_dimension = any(
            token in group_sql for token in ("ym", "month", "date_id")
        )
        if not has_month_dimension:
            return False, "按月趋势必须按 dim_date.ym（或 month/date_id）分组"
        if not any(token in order_sql for token in ("ym", "month", "date_id")):
            return False, "按月趋势必须按时间字段排序"

    asks_brand_winner = (
        ("哪个品牌" in q or "哪家品牌" in q)
        and any(token in q for token in ("最高", "最多", "第一"))
    )
    if asks_brand_winner:
        select_sql = " ".join(str(expr).lower() for expr in tree.expressions)
        if "brand_name" not in select_sql:
            return False, "品牌冠军查询必须返回品牌名，不能只返回最大销量值"
        if tree.args.get("group") is None or tree.args.get("order") is None:
            return False, "品牌冠军查询必须按品牌聚合并按销量排序"
        limit_node = tree.args.get("limit")
        try:
            winner_limit = int(limit_node.expression.this) if limit_node else None
        except (AttributeError, TypeError, ValueError):
            winner_limit = None
        if winner_limit != 1:
            return False, "品牌冠军查询必须 LIMIT 1"

    low_price = re.search(r"指导价(?:低于|小于)\s*(\d+(?:\.\d+)?)\s*万?", q)
    if low_price and "guide_price_max" not in sql_lower:
        return False, "整车系指导价低于阈值必须使用 guide_price_max"
    high_price = re.search(r"指导价\s*(\d+(?:\.\d+)?)\s*万?以上", q)
    if high_price and "guide_price_min" not in sql_lower:
        return False, "整车系指导价高于阈值必须使用 guide_price_min"

    if any(token in q for token in ("排名上升", "排名下降", "优于上期", "较上期")):
        if "last_rank" not in sql_lower:
            return False, "排名变化查询必须使用 last_rank"
        has_comparison = bool(re.search(
            r"(?:\brank\b\s*[<>]\s*[\w.]*last_rank|"
            r"last_rank\s*[<>]\s*[\w.]*\brank\b)",
            sql_lower,
        ))
        if not has_comparison:
            return False, "排名变化查询必须比较 rank 与 last_rank"

    if (
        "各动力类型" in q
        or len(mentioned_energy) >= 2
        and any(token in q for token in ("各", "分别", "与", "对比"))
    ):
        has_energy_group = (
            tree.args.get("group") is not None
            and "new_energy_type" in str(tree.args.get("group")).lower()
        )
        if not has_energy_group and len(cols or []) < 2:
            return False, "多动力类型对比必须按 new_energy_type 分组或返回多个聚合列"

    if rows is not None and top_match and len(rows) == 1 and requested > 1:
        return False, f"Top{requested} 查询只返回 1 行，疑似聚合维度错误"

    return True, ""


def verify_sql(state: AgentState):
    """Text2SQL 语义自校验（§4.6）：SQL 能跑通≠语义对。把『能跑但答非所问』纳入闭环。
    FAIL-OPEN：开关关闭 / 无数据 / 已无重试预算 / 校验自身异常 —— 一律放行，绝不比不校验更差。"""
    from .config import SEMANTIC_CHECK
    rows = state.get("rows") or []
    # 开关关 / 空结果无可核对时放行。预算耗尽时仍执行确定性护栏，
    # 只跳过 LLM 审核；否则最后一次错误 SQL 会被当成正确结果出图。
    if not SEMANTIC_CHECK or not _has_meaningful_rows(rows):
        return {"sql_verified": True, "trace": [_t("verify_sql", checked=False)]}
    exhausted = state.get("retry_count", 0) >= MAX_SQL_RETRY
    shape_ok, shape_reason = _validate_sql_shape(
        state.get("normalized_question") or state.get("question", ""),
        state.get("sql", ""),
        state.get("cols") or [],
        rows,
    )
    if not shape_ok:
        failure = {
            "sql_verified": False,
            "sql_error": f"SQL 语义结构不匹配：{shape_reason}。请修正 SQL。",
            "trace": [_t("verify_sql", ok=False, deterministic=True,
                         exhausted=exhausted, reason=shape_reason[:100])],
        }
        if exhausted:
            failure.update({"rows": [], "cols": [], "degraded": True})
        return failure

    if not state.get("uses_history_entities", False):
        from .nlu import _get_keyword_brands
        q = state.get("normalized_question") or state.get("question", "")
        sql_text = state.get("sql", "")
        stale_brands = [
            brand for brand in _get_keyword_brands()
            if brand in sql_text and brand not in q
        ]
        if stale_brands:
            reason = f"SQL 引入了当前问题未提及的品牌：{', '.join(stale_brands[:3])}"
            failure = {
                "sql_verified": False,
                "sql_error": f"{reason}。请移除历史主题污染后重写 SQL。",
                "trace": [_t("verify_sql", ok=False, deterministic=True,
                             exhausted=exhausted, reason=reason)],
            }
            if exhausted:
                failure.update({"rows": [], "cols": [], "degraded": True})
            return failure

    if exhausted:
        return {
            "sql_verified": True,
            "trace": [_t("verify_sql", checked=True, deterministic=True,
                         llm_skipped="retry_budget_exhausted")],
        }

    try:
        out = chat([
            {"role": "system", "content": _VERIFY_SYS},
            {"role": "user", "content": f"问题：{state['question']}\nSQL：{state.get('sql', '')}\n"
                                        f"列：{state.get('cols')}\n结果(前5行)：{str(rows[:5])}"}],
            temperature=0.0)
        import json as _json
        m = _json.loads(out[out.find("{"):out.rfind("}") + 1])
        if bool(m.get("ok", True)):
            return {"sql_verified": True, "trace": [_t("verify_sql", ok=True)]}
        # 语义不匹配 → 把「为什么不匹配」当错误回喂 fix_sql 重生成（复用现成重试环）
        return {"sql_verified": False,
                "sql_error": f"结果未正确回答问题：{m.get('reason', '口径/过滤/聚合可能有误')}。请修正 SQL。",
                "trace": [_t("verify_sql", ok=False, reason=str(m.get("reason"))[:80])]}
    except Exception as e:  # FAIL-OPEN：校验出任何问题都放行正常结果
        return {"sql_verified": True, "trace": [_t("verify_sql", error=str(e)[:80])]}


def chart(state: AgentState):
    """规则引擎产出图表描述符（§8）。无数据则跳过。"""
    rows = state.get("rows", [])
    if not _has_meaningful_rows(rows):
        return {"chart": None, "trace": [_t("chart", skipped="no_rows")]}
    spec = recommend_chart(state.get("cols", []), rows, state["question"])
    return {"chart": spec, "trace": [_t("chart", default_type=(spec or {}).get("default_type"))]}


_INSIGHT_SYS = ("你是商业分析顾问。根据问题与查询结果给出：1)一句话结论 2)简要归因 3)1-2 条建议。"
                "只依据给定数据，不编造数字。中文简洁。"
                "重要：结论中必须明确标注数据的时间范围（如'2024年全年''2024-2026年'），"
                "不要让用户看完结论还不知道数据是什么时候的。")


def insight(state: AgentState):
    """洞察归因；无数据/重试耗尽/LLM 降级三条路径。"""
    rows = state.get("rows", []) or []
    cols = state.get("cols", []) or []

    # 路径A：SQL 重试耗尽
    has_rows = _has_meaningful_rows(rows)
    if state.get("sql_error") and not has_rows:
        return {"degraded": True,
                "insight": "抱歉，这个问题我多次尝试都没能生成可用的查询，可能是口径不清或超出当前数据范围。"
                           "可换个问法或缩小范围（如指定车系/月份）。",
                "trace": [_t("insight", degraded=True)]}

    # 路径B：SQL 执行成功但结果为空
    if not has_rows:
        q = state.get("question", "")
        empty_hint = (
            "当前筛选条件下没有匹配记录（可能是时间超出数据范围、"
            "车型尚未覆盖或该口径暂无数据）。"
        )

        # Step 1: 先查 RAG 知识库 — 之前 pipeline 采集的数据可能已经存在
        try:
            from .rag import retrieve as R
            rag_chunks = R.hybrid_recall(state.get("user_id", 0), q)
            if rag_chunks:
                top, used_rr = R.rerank(q, rag_chunks)
                evidence_ok, _ = R.evidence_is_sufficient(top, used_rr, q)
                if top and evidence_ok:
                    blocks = R.merge_parents(top)
                    res = R.generate(q, blocks)
                    if res.get("has_answer"):
                        return {"no_data": True,
                                "insight": f"📊 知识库匹配结果：\n\n{res['answer']}",
                                "citations": res.get("citations", []),
                                "trace": [_t("insight", empty_result=True, mode="rag_fallback",
                                             rag_chunks=len(rag_chunks))]}
        except Exception:
            pass

        # Step 2: RAG 没命中 → 触发 pipeline 采集
        import secrets
        task_id = "agent_" + secrets.token_hex(8)
        try:
            from .agent_pipeline import enqueue_pipeline
            queued = enqueue_pipeline(
                task_id=task_id,
                original_question=q,
                original_user_id=state.get("user_id", 0),
            )
            if queued.get("accepted"):
                mode = queued.get("mode", "background")
                eta = "30 秒到 2 分钟" if mode == "celery" else "约 1 到 3 分钟"
                return {"no_data": True,
                        "task_id": task_id,
                        "insight": f"数据库暂无相关数据。{empty_hint}"
                                   f"已启动智能数据采集（任务ID：{task_id[:12]}…），预计需要 {eta}。\n"
                                   f"页面会持续显示任务进度，完成后可直接查看采集结论。",
                        "trace": [_t("insight", empty_result=True, task_id=task_id,
                                     mode=mode)]}

            _log.warning("Collection queue unavailable for %s: %s",
                         task_id, queued.get("error", "unknown"))
            return {
                "no_data": True,
                "insight": f"数据库暂无相关数据。{empty_hint}"
                           "智能采集服务暂不可用，请确认 Redis/Celery 已启动后重试；"
                           "当前请求没有在后台偷偷同步执行。",
                "trace": [_t("insight", empty_result=True,
                             mode="queue_unavailable")],
            }
        except Exception as exc:
            _log.warning("Collection enqueue failed for %s: %s", task_id, exc)
            return {"no_data": True,
                    "insight": f"数据库暂无相关数据。{empty_hint}"
                               "智能采集服务暂不可用，请稍后重试。",
                    "trace": [_t("insight", empty_result=True,
                                 mode="queue_error", error=str(exc)[:100])]}

    # 路径C：正常结果 → LLM 生成洞察
    txt = chat([{"role": "system", "content": _INSIGHT_SYS},
                {"role": "user", "content": f"问题：{state['question']}\n列：{cols}\n"
                                            f"数据(前20行)：{str(rows[:20])}"}],
               temperature=0.3)
    return {"insight": txt, "trace": [_t("insight", chars=len(txt))]}


def rag_retrieve(state: AgentState):
    """知识脑：混合召回 + 重排 + 父块归并（§5.4）。"""
    from .rag import retrieve as R
    children = R.hybrid_recall(state["user_id"], state["question"])
    if not children:
        return {"chunks": [], "trace": [_t("rag_retrieve", recall=0)]}
    top, used_rr = R.rerank(state["question"], children)
    top_score = top[0]["score_final"] if top else 0.0
    evidence_ok, evidence_reason = R.evidence_is_sufficient(
        top, used_rr, state["question"]
    )
    if not evidence_ok:
        return {
            "chunks": [],
            "trace": [_t(
                "rag_retrieve",
                recall=len(children),
                reason=evidence_reason,
                top_score=round(top_score, 3),
                reranker=used_rr,
            )],
        }
    blocks = R.merge_parents(top)
    return {"chunks": blocks,
            "trace": [_t("rag_retrieve", recall=len(children), parents=len(blocks),
                         reranker=used_rr, top_score=round(top_score, 3))]}


def rag_answer(state: AgentState):
    """知识脑：带引用生成 + 防幻觉（§5.5）。"""
    from .rag import retrieve as R
    blocks = state.get("chunks") or []
    if not blocks:
        return {"rag_answer": R.NO_ANSWER, "citations": [], "has_answer": False,
                "trace": [_t("rag_answer", has_answer=False)]}
    res = R.generate(state["question"], blocks)
    return {"rag_answer": res["answer"], "citations": res["citations"],
            "has_answer": res["has_answer"], "trace": [_t("rag_answer", has_answer=res["has_answer"],
                                                          citations=len(res["citations"]))]}


def compose(state: AgentState):
    """汇总：把 数据结论(图表+洞察) 与 文档佐证(带引用答案) 拼成统一回答（§7.6）。任一脑缺失则优雅降级。"""
    parts = []
    # 数据脑：只有有真实数据时才标注【数据分析】
    if state.get("insight"):
        has_data = bool(state.get("rows"))
        prefix = "【数据分析】" if (has_data and state.get("rag_answer")) else ""
        parts.append(prefix + state["insight"])
    if state.get("rag_answer"):
        parts.append(("【文档佐证】" if parts else "") + state["rag_answer"])
    final = "\n\n".join(p for p in parts if p) or "未能生成回答。"
    return {"final_answer": final, "trace": [_t("compose",
            has_chart=bool(state.get("chart")), has_citations=bool(state.get("citations")))]}


# ============================================================ 条件路由（§7.5）
def route_intent(state: AgentState):
    intent = state["intent"]
    if intent == "sql":
        return "schema_link"
    if intent == "rag":
        return "rag_retrieve"
    if intent == "hybrid":
        return ["schema_link", "rag_retrieve"]    # 并行 fan-out（两个脑链同时跑）
    if intent == "chat":
        return "chitchat"
    return "clarify"


def route_exec(state: AgentState):
    if not state.get("sql_error"):
        return "verify_sql"                         # 成功 → 先语义自校验（再出图）
    if state.get("retry_count", 0) < MAX_SQL_RETRY:
        return "fix_sql"                            # 失败可重试 → 修正环
    return "insight"                                # 重试耗尽 → 降级（insight 节点出降级话术）


def route_verify(state: AgentState):
    if state.get("sql_verified", True):
        return "chart"                              # 语义 OK → 出图
    if state.get("retry_count", 0) >= MAX_SQL_RETRY:
        return "insight"                            # 确定性护栏仍失败 → 诚实降级，不输出错误图表
    return "fix_sql"                                # 语义不匹配 → 回 fix_sql 重生成


# ============================================================ 建图
def build_graph():
    g = StateGraph(AgentState)
    for fn in (intent_router, clarify, chitchat, schema_link, gen_sql, exec_sql, fix_sql, verify_sql,
               chart, insight, rag_retrieve, rag_answer):
        g.add_node(fn.__name__, fn)
    # compose 是「并行 join」节点：defer=True 让它延到所有在途分支(数据脑链+知识脑链)都完成才跑一次，
    # 避免 hybrid 下两条链长度不一导致 compose 被触发两次（§7.6 合并语义）。
    g.add_node("compose", compose, defer=True)

    g.add_edge(START, "intent_router")
    g.add_conditional_edges("intent_router", route_intent,
                            ["schema_link", "rag_retrieve", "clarify", "chitchat"])
    # 数据脑链
    g.add_edge("schema_link", "gen_sql")
    g.add_edge("gen_sql", "exec_sql")
    g.add_conditional_edges("exec_sql", route_exec, ["verify_sql", "fix_sql", "insight"])
    g.add_conditional_edges(
        "verify_sql", route_verify, ["chart", "fix_sql", "insight"]
    )                                               # 语义校验 → 出图 / 回修 / 耗尽降级
    g.add_edge("fix_sql", "exec_sql")               # 重试环（执行报错 + 语义不匹配 共用）
    g.add_edge("chart", "insight")
    g.add_edge("insight", "compose")
    # 知识脑链
    g.add_edge("rag_retrieve", "rag_answer")
    g.add_edge("rag_answer", "compose")
    # 收口
    g.add_edge("compose", END)
    g.add_edge("clarify", END)
    g.add_edge("chitchat", END)
    return g.compile()


_GRAPH = None
_GRAPH_LOCK = threading.Lock()


def _get_graph():
    """懒初始化 + 双重检查锁定：并发安全，build_graph() 只执行一次。"""
    global _GRAPH
    if _GRAPH is None:
        with _GRAPH_LOCK:
            if _GRAPH is None:
                _GRAPH = build_graph()
    return _GRAPH


def run_agent(question: str, user_id: int, history: list = None) -> dict:
    """对外入口：跑图，返回最终 State（含 final_answer / chart / citations / trace）。"""
    init = {"question": question, "user_id": user_id, "history": history or [], "trace": []}
    return _get_graph().invoke(init)


def stream_agent(question: str, user_id: int, history: list = None):
    """流式跑图：用 LangGraph `.stream(values)` 逐超步产出**累积 State 快照**。
    供 SSE 层在某节点完成、对应字段一出现就立刻推事件（渐进反馈，告别『等 5-10s 一次性全出』）。
    最后一个 yield 的快照即最终 State。"""
    init = {"question": question, "user_id": user_id, "history": history or [], "trace": []}
    for snapshot in _get_graph().stream(init, stream_mode="values"):
        yield snapshot
