"""LangGraph 双脑编排（PRD-2 §7）：用状态图把 数据脑(Text2SQL) 与 知识脑(RAG) 真正编排起来。

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
  intent_router ─┬─ sql    → schema_link → gen_sql → exec_sql ─┬─成功→ chart → insight ┐
                 │                                   ▲          ├─失败可重试→ fix_sql ─┘(回 exec_sql)
                 │                                   └──────────┴─失败耗尽→ insight(降级)
                 ├─ rag    → rag_retrieve → rag_answer ───────────────────────────────┐
                 ├─ hybrid → [schema_link 链 ∥ rag_retrieve 链]（并行）                │
                 └─ clarify→ clarify → END                                            ▼
                                              insight / rag_answer ───────────────→ compose → END
"""
import json as _json
import operator
import threading
from typing import Annotated, TypedDict

from langgraph.graph import StateGraph, START, END

from .llm import chat
from .config import MAX_SQL_RETRY
from .schema_linking import link_schema
from .sql_guard import ensure_safe, with_limit, UnsafeSQLError
from .db import run_query
from .text2sql import DOMAIN, FEWSHOT, SYS as SQL_SYS, _extract_sql
from .charts import recommend_chart


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


# ============================================================ 对话上下文构建
def _history_block(state) -> str:
    """
    构建对话上下文块，注入两层信息：
    1. 实体记忆（本会话已识别品牌/车系）——解决「那辆车」「它」跨轮指代
    2. 近期消息摘要——解决追问语境
    """
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

    # 多轮改写：有历史时先改写问题，识别元信息追问 or 补全省略实体
    if history:
        rw = _rewrite_query(q, history)
        if rw["is_meta"]:
            return {
                "intent": "chat",
                "_is_followup": True,
                "confidence": 0.9,
                "entities": {},
                "active_entities": state.get("active_entities") or {},
                "normalized_question": q,
                "retry_count": 0,
                "trace": [_t("intent_router", intent="chat", path="meta_question",
                             rewritten=q)],
            }
        q = rw["rewritten"]

    active_ents = state.get("active_entities") or _build_active_entities_from_history(history)
    ctx = _history_block({**state, "active_entities": active_ents})

    last_assistant = ""
    for m in reversed(history):
        if m.get("role") == "assistant":
            last_assistant = (m.get("content") or "")[:300]
            break

    result = _classify_intent(q, ctx)

    intent = result["intent"]
    entities = result.get("entities") or {}
    source = result.get("source", "")

    # No-data guard: last assistant had no-data signal → override sql/hybrid → rag
    if any(sig in last_assistant for sig in _NO_DATA_SIGNALS):
        if intent in ("sql", "hybrid"):
            intent = "rag"
            result["confidence"] = min(result.get("confidence", 0.8), 0.7)

    # Slot completeness: is_complete=False + sql/hybrid → clarify
    is_complete = result.get("is_complete", True)
    if intent in ("sql", "hybrid") and not is_complete:
        intent = "clarify"

    new_active = _merge_entities(active_ents, entities)

    # Build trace: distinguish greeting fast-path from LLM-classified
    if source == "layer1_greeting":
        trace_entry = _t("intent_router", intent=intent, path="greeting_precheck")
        confidence = result.get("confidence", 1.0)
    else:
        confidence = result.get("confidence", 0.8)
        trace_entry = _t("intent_router",
                         intent=intent,
                         confidence=round(confidence, 2),
                         entities=entities,
                         is_complete=result.get("is_complete", True),
                         llm_classified=True)

    upd: dict = {
        "intent": intent,
        "confidence": confidence,
        "entities": entities,
        "active_entities": new_active,
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
            f"{DOMAIN}\n\n{entity_ctx}{FEWSHOT}\n"
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


def verify_sql(state: AgentState):
    """Text2SQL 语义自校验（§4.6）：SQL 能跑通≠语义对。把『能跑但答非所问』纳入闭环。
    FAIL-OPEN：开关关闭 / 无数据 / 已无重试预算 / 校验自身异常 —— 一律放行，绝不比不校验更差。"""
    from .config import SEMANTIC_CHECK
    rows = state.get("rows") or []
    # 不校验的情形：开关关 / 空结果(无可核对) / 重试预算已耗尽(再判也回不了 fix_sql)
    if not SEMANTIC_CHECK or not rows or state.get("retry_count", 0) >= MAX_SQL_RETRY:
        return {"sql_verified": True, "trace": [_t("verify_sql", checked=False)]}
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
    if not rows:
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
    if state.get("sql_error") and not rows:
        return {"degraded": True,
                "insight": "抱歉，这个问题我多次尝试都没能生成可用的查询，可能是口径不清或超出当前数据范围。"
                           "可换个问法或缩小范围（如指定车系/月份）。",
                "trace": [_t("insight", degraded=True)]}

    # 路径B：SQL 执行成功但结果为空
    if not rows:
        q = state.get("question", "")
        all_text = q
        for m in (state.get("history") or []):
            all_text += " " + (m.get("content") or "")
        all_text += " " + (state.get("sql") or "")
        brand_hint = ""
        from .nlu import _get_keyword_brands
        for word in _get_keyword_brands():
            if word in all_text:
                brand_hint = f"「{word}」可能不在当前数据库覆盖范围内（目前覆盖 101 个品牌，以国产新能源为主）。"
                break

        # Step 1: 先查 RAG 知识库 — 之前 pipeline 采集的数据可能已经存在
        try:
            from .rag import retrieve as R
            from .config import RERANK_SCORE_MIN
            rag_chunks = R.hybrid_recall(state.get("user_id", 0), q)
            if rag_chunks:
                top, used_rr = R.rerank(q, rag_chunks)
                # Score filter: only apply when real reranker is available
                # RRF scores are ~0.01-0.03, reranker scores are 0-1
                score_ok = True
                if used_rr and top:
                    score_ok = top[0].get("score_final", 0) >= RERANK_SCORE_MIN
                if top and score_ok:
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
        pipeline_result = None

        try:
            from .agent_pipeline import run_pipeline_task
            if run_pipeline_task is None:
                raise ImportError("Celery not available")
            run_pipeline_task.delay(task_id=task_id, original_question=q,
                                    original_user_id=state.get("user_id", 0))
            return {"no_data": True,
                    "task_id": task_id,
                    "insight": f"数据库暂无相关数据。{brand_hint}"
                               f"已启动智能数据采集（任务ID：{task_id[:12]}…），预计需要 30 秒到 2 分钟。\n"
                               f"采集完成后将自动为您重新查询，请稍候…",
                    "trace": [_t("insight", empty_result=True, task_id=task_id, mode="async")]}
        except Exception:
            pass

        # Sync fallback: run pipeline and USE the result directly
        try:
            from .agent_pipeline import run_pipeline
            pipeline_result = run_pipeline(task_id, q, state.get("user_id", 0))
        except Exception:
            pass

        if pipeline_result and pipeline_result.get("status") == "completed":
            final_answer = pipeline_result.get("final_answer", "")
            if final_answer and "数据采集完成" not in final_answer:
                return {"no_data": True,
                        "task_id": task_id,
                        "insight": f"📊 智能数据采集结果：\n\n{final_answer}",
                        "trace": [_t("insight", empty_result=True, task_id=task_id, mode="sync_ok")]}
            return {"no_data": True,
                    "task_id": task_id,
                    "insight": f"数据库暂无相关数据。{brand_hint}"
                               f"已尝试在线搜索但未找到足够可靠的数据。建议：\n"
                               f"1. 换个更具体的品牌/车系名称\n"
                               f"2. 尝试更宽泛的问题（如 '2025年纯电销量Top10'）",
                    "trace": [_t("insight", empty_result=True, task_id=task_id, mode="sync_insufficient")]}

        return {"no_data": True, "insight": f"未查询到相关数据。{brand_hint}请尝试：\n"
                       f"1. 换一个品牌或车系名称（如 '比亚迪'、'小米SU7'）\n"
                       f"2. 问更宽泛的问题（如 '2025年纯电销量Top10'）",
                "trace": [_t("insight", empty_result=True)]}

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
    from .config import RERANK_SCORE_MIN
    if used_rr and top_score < RERANK_SCORE_MIN:
        return {"chunks": [], "trace": [_t("rag_retrieve", recall=len(children), low_score=round(top_score, 3))]}
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
    return "fix_sql"                                # 语义不匹配 → 回 fix_sql 重生成（verify 已确认仍有预算）


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
    g.add_conditional_edges("verify_sql", route_verify, ["chart", "fix_sql"])  # 语义校验 → 出图 / 回修
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
