"""FastAPI 入口（接口清单见 PRD-2 §10；SSE 事件协议见 §9.1）：
- /api/auth/register|login|me            鉴权（app/auth.py）
- POST /api/ask        (SSE)             双脑问答，按 §9.1 推 intent/sql/rows/chart/insight/citation/done/error
- POST /api/ask_sync                     同步返回完整结果（调试）
- GET  /api/history                      当前用户会话列表
- GET  /api/history/{conv_id}            会话消息（还原含图表/引用的历史会话）
- POST /api/kb/upload | GET /api/kb/list | DELETE /api/kb/{doc_id} | POST /api/kb/ask  （app/kb.py）

鉴权与隔离（§17.3）：除 /health 与 /api/auth/* 外，业务接口都 Depends(get_current_user)；
落库/查询一律带当前用户 user_id —— A 看不到 B 的会话与知识库。
编排：/api/ask 走 LangGraph 双脑状态图（app/graph.run_agent，§7），不再用旧的线性 analyze。
"""
import asyncio
import json
import logging
import secrets
import threading

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import select, text as sql_text
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from .graph import run_agent, stream_agent
from .db import engine as bi_engine          # 只读分析库（车型报价直接查）
from .auth import router as auth_router, get_current_user
from .database import get_db, init_db
from .models import User, Conversation, Message, SavedInsight, SharedInsight
from .memory import schedule_extraction, build_memory_block

from .config import CORS_ALLOW_ORIGINS, JWT_SECRET, LLM_BASE_URL, LLM_MODEL

logger = logging.getLogger("cheshijing")
MAX_QUESTION_LEN = 2000     # 单次提问字符上限（防滥用/超长输入拖死 LLM）
MIN_QUESTION_LEN = 1
_user_last_call: dict[int, float] = {}   # user_id → 上次调用时间戳（速率限制）


def _run_agent_worker(question: str, user_id: int, history: list,
                      put: callable, stop: threading.Event) -> None:
    """Worker 线程：逐快照推给 SSE 事件循环。
    每次快照前检查 stop event，断连时由 gen() 的 finally 块设置，worker 立即退出。
    抽成独立函数便于单元测试，不依赖 asyncio event loop。
    """
    try:
        for snap in stream_agent(question, user_id, history):
            if stop.is_set():
                break
            put(("snap", snap))
    except Exception as e:  # noqa: BLE001
        put(("err", e))
    finally:
        put(("end", None))
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(title="车市镜 · 新能源车市情报 Agent")
# CORS：dev 默认放行全部；生产用 CORS_ALLOW_ORIGINS 收紧到正式域名（§17/§18）。
# 用 Bearer token 鉴权（非 cookie），故 "*" 时不需 credentials（浏览器禁止 * + credentials 同用）。
app.add_middleware(CORSMiddleware, allow_origins=CORS_ALLOW_ORIGINS,
                   allow_methods=["*"], allow_headers=["*"],
                   allow_credentials=(CORS_ALLOW_ORIGINS != ["*"]))
app.include_router(auth_router)
from .admin import router as admin_router          # 管理员后台（用户管理）
app.include_router(admin_router)
# RAG 知识库路由（上传/列表/删除/问答）。延迟导入避免无 RAG 依赖时启动失败。
try:
    from .kb import router as kb_router
    app.include_router(kb_router)
except Exception as _e:  # noqa: BLE001
    logger.warning(f"RAG kb route not loaded (missing deps or PG not started): {_e}")


@app.on_event("startup")
def _startup():
    init_db()  # 幂等建应用层表 + 轻量迁移（补 users.role/disabled 列）
    # 确保有管理员账号（演示开箱即用；ADMIN_USERNAME/ADMIN_PASSWORD 可在 .env 配置）。
    from .auth import bootstrap_admin
    from .database import SessionLocal
    _db = SessionLocal()
    try:
        action, uname = bootstrap_admin(_db)
        logger.info(f"[admin] 管理员账号 '{uname}': {action}")
    finally:
        _db.close()
    import os as _os
    _env = _os.getenv("APP_ENV", "development").lower()
    _is_prod = _env in ("production", "prod")
    if _os.getenv("ADMIN_PASSWORD", "admin123") == "admin123":
        logger.warning("管理员默认密码仍是 admin123！上线/公开演示前请在 .env 设置 ADMIN_PASSWORD。")
    # P1 FIX: 生产环境弱密钥直接拒绝启动，而不是仅 warning
    if JWT_SECRET == "dev-insecure-change-me":
        if _is_prod:
            raise SystemExit("❌ 生产环境不允许使用默认 JWT_SECRET！请在 .env 设置强密钥（openssl rand -hex 32）")
        logger.warning("JWT_SECRET 仍是默认弱密钥！上线/演示前务必在 .env 设置随机强密钥（如 openssl rand -hex 32）")
    # 配置自检：base_url 与 model 跨厂商不一致 = 静默连错 API（O7：qwen 默认值 + deepseek base 的坑）。
    _base, _model = LLM_BASE_URL.lower(), LLM_MODEL.lower()
    _provider = next((p for p in ("deepseek", "dashscope", "moonshot", "openai", "siliconflow") if p in _base), None)
    if _provider == "deepseek" and "deepseek" not in _model:
        logger.warning(f"LLM 配置可能不匹配：LLM_BASE_URL 指向 DeepSeek，但 LLM_MODEL='{LLM_MODEL}'（非 deepseek-*）。请核对 .env。")
    elif _provider == "dashscope" and not (_model.startswith("qwen") or _model.startswith("qwq")):
        logger.warning(f"LLM 配置可能不匹配：LLM_BASE_URL 指向 DashScope/通义，但 LLM_MODEL='{LLM_MODEL}'。请核对 .env。")


class Ask(BaseModel):
    question: str
    conversation_id: int | None = None  # 可选：续接已有会话；缺省则新建


@app.get("/health")
def health():
    return {"ok": True}


# ---------------------------------------------------------------- 落库
def _row_arrays(state) -> list:
    """结果集 dict 行 → 按列序的数组行（§9.1 rows 事件要数组）。"""
    cols = state.get("cols") or []
    return [[r.get(c) for c in cols] for r in (state.get("rows") or [])]


def _persist(db: Session, user: User, question: str, state: dict,
             conversation_id: int | None) -> tuple[int, int]:
    """把一轮问答落库到当前用户名下；assistant 消息存 result_meta（图表/列行/引用），供历史还原。"""
    conv = None
    if conversation_id is not None:
        conv = db.get(Conversation, conversation_id)
        if conv is None or conv.user_id != user.id:    # 只能续接自己的会话
            conv = None
    if conv is None:
        conv = Conversation(user_id=user.id, title=question[:40])
        db.add(conv)
        db.flush()
    db.add(Message(conversation_id=conv.id, user_id=user.id, role="user", content=question))
    meta = {
        "columns": state.get("cols") or [],
        "rows": _row_arrays(state),
        "chart": state.get("chart"),
        "citations": state.get("citations") or [],
        "intent": state.get("intent"),
        "trace": [t.get("node") for t in (state.get("trace") or [])],
    }
    assistant = Message(
        conversation_id=conv.id, user_id=user.id, role="assistant",
        content=(state.get("final_answer") or "")[:4000],
        intent=state.get("intent"), sql_text=state.get("sql"),
        result_meta=json.dumps(meta, ensure_ascii=False, default=str),
    )
    db.add(assistant)
    db.commit()

    # 有条件调度后台记忆提取（有界线程池、进程内去重）
    msg_count = db.query(Message).filter_by(conversation_id=conv.id).count()
    schedule_extraction(user.id, conv.id, msg_count)

    return conv.id, assistant.id


# ---------------------------------------------------------------- 问答
@app.post("/api/ask_sync")
def ask_sync(body: Ask, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """同步返回完整结果（调试用）。"""
    if not body.question or not body.question.strip():
        raise HTTPException(400, "问题不能为空")
    if len(body.question) > MAX_QUESTION_LEN:
        raise HTTPException(400, f"问题过长，请控制在{MAX_QUESTION_LEN}字符以内")
    history = _load_history(db, user, body.conversation_id)
    # 注入长期记忆到上下文（fail-open：异常时跳过，不影响主流程）
    try:
        mem_block = build_memory_block(db, user.id, body.question)
        if mem_block:
            history = [{"role": "system", "content": mem_block}] + history
    except Exception:
        pass
    state = run_agent(body.question, user.id, history=history)
    conv_id, msg_id = _persist(db, user, body.question, state, body.conversation_id)
    return {
        "intent": state.get("intent"), "sql": state.get("sql"),
        "columns": state.get("cols") or [], "rows": _row_arrays(state),
        "chart": state.get("chart"), "answer": state.get("final_answer"),
        "citations": state.get("citations") or [], "has_answer": state.get("has_answer", True),
        "conversation_id": conv_id, "msg_id": msg_id,
        "trace": [t.get("node") for t in (state.get("trace") or [])],
    }


def _insight_pieces(text: str, n: int = 24):
    for i in range(0, len(text), n):
        yield text[i:i + n]


def _load_history(db: Session, user: User, conversation_id: int | None, limit: int = 10) -> list:
    """取本会话最近几轮消息作多轮上下文（仅自己的会话）。供 Agent 理解『那丰田呢』这类指代。"""
    if conversation_id is None:
        return []
    conv = db.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user.id:
        return []
    msgs = db.scalars(
        select(Message).where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc()).limit(limit)
    ).all()
    return [{"role": m.role, "content": m.content or ""} for m in reversed(msgs)]


@app.post("/api/ask")
async def ask(body: Ask, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """SSE（§9.1）：stage(accepted) → intent → [sql] → [rows] → [chart] → insight(逐段 delta) → [citation...] → done。
    **渐进推送**：用 LangGraph 流式跑图，某节点一完成、对应字段一出现就立刻推事件（不再等整图跑完一次性全出）。
    纯 RAG 无 sql/rows/chart，只有 insight(答案)+citation；出错推 error。"""
    history = _load_history(db, user, body.conversation_id)  # O3 多轮上下文
    # 注入长期记忆（fail-open：异常时跳过，不影响主流程）
    try:
        mem_block = build_memory_block(db, user.id, body.question)
        if mem_block:
            history = [{"role": "system", "content": mem_block}] + history
    except Exception:
        pass

    async def gen():
        # 速率限制：按 user.id 追踪上次调用时间，0.5s 内重复请求拒绝
        import time as _time
        _now = _time.time()
        if _now - _user_last_call.get(user.id, 0) < 0.5:
            yield {"event": "error", "data": json.dumps({"code": "RATE_LIMITED", "message": "请稍后再试，间隔 0.5 秒"}, ensure_ascii=False)}
            return
        _user_last_call[user.id] = _now
        if not body.question or not body.question.strip():
            yield {"event": "error", "data": json.dumps({"code": "EMPTY", "message": "问题不能为空"}, ensure_ascii=False)}
            return
        yield {"event": "stage", "data": json.dumps(
            {"stage": "accepted", "message": "已接收，正在分析问题…"}, ensure_ascii=False)}

        # 同步流式图丢到工作线程跑，用线程安全队列把每个「累积 State 快照」桥接回事件循环。
        q: asyncio.Queue = asyncio.Queue(); _last_intent = None
        loop = asyncio.get_running_loop()
        _stop = threading.Event()

        def _async_put(item):
            loop.call_soon_threadsafe(q.put_nowait, item)

        threading.Thread(
            target=_run_agent_worker,
            args=(body.question, user.id, history, _async_put, _stop),
            daemon=True,
        ).start()

        emitted: set = set()
        final: dict = {}
        err = None
        # P0 FIX: 无超时时 LLM 挂起会永久占用协程槽，高并发下耗尽事件循环
        # 300s = LLM_TIMEOUT(60) × MAX_RETRIES(2) × 最多6次调用，给足余量
        _Q_TIMEOUT = 300
        try:
          while True:
            try:
                kind, payload = await asyncio.wait_for(q.get(), timeout=_Q_TIMEOUT)
            except asyncio.TimeoutError:
                yield {"event": "error", "data": json.dumps(
                    {"code": "TIMEOUT", "message": "处理超时，请稍后重试。"}, ensure_ascii=False)}
                return
            if kind == "err":
                err = payload
                break
            if kind == "end":
                break
            snap = payload
            final = snap
            # 字段一出现就推，每种事件只推一次（渐进反馈的关键）
            if snap.get("intent") and snap.get("intent") != _last_intent:
                _last_intent = snap.get("intent")
                yield {"event": "intent", "data": json.dumps(
                    {"intent": snap.get("intent"), "confidence": None}, ensure_ascii=False)}
            # SQL/rows/chart: only emit when rows exist (SQL空结果走RAG回退时不展示无意义的SQL)
            if snap.get("rows") and "rows" not in emitted:
                if snap.get("sql") and "sql" not in emitted:
                    emitted.add("sql")
                    yield {"event": "sql", "data": json.dumps({"sql_text": snap["sql"]}, ensure_ascii=False)}
                emitted.add("rows")
                yield {"event": "rows", "data": json.dumps(
                    {"columns": snap.get("cols") or [], "rows": _row_arrays(snap)},
                    ensure_ascii=False, default=str)}
            if snap.get("chart") and "chart" not in emitted:
                emitted.add("chart")
                yield {"event": "chart", "data": json.dumps(snap["chart"], ensure_ascii=False)}
            if snap.get("final_answer") and "insight" not in emitted:
                emitted.add("insight")
                for piece in _insight_pieces(snap.get("final_answer") or "（无内容）"):
                    yield {"event": "insight", "data": json.dumps({"delta": piece}, ensure_ascii=False)}
                    await asyncio.sleep(0)
            if snap.get("citations") and "citations" not in emitted:
                emitted.add("citations")
                for c in snap.get("citations") or []:
                    yield {"event": "citation", "data": json.dumps(c, ensure_ascii=False, default=str)}

        finally:
            _stop.set()   # 客户端断连（GeneratorExit）或正常结束，均通知 worker 停止

        if err is not None:
            yield {"event": "error", "data": json.dumps(
                {"code": "AGENT_ERROR", "message": "处理失败，请换种问法或缩小范围。"}, ensure_ascii=False)}
            logger.error(f"[ask] stream_agent 失败 user={user.id} q={body.question[:80]!r}: {err}",
                         exc_info=err)
            return

        # 落库（拿到完整最终 State 后）
        # P1 NOTE: GeneratorExit（断连）发生在 yield 时，finally 之后的代码不执行，
        # 故断连时本行不运行。如需断连也落库，可在 finally 中加 try/_persist，
        # 但需要额外状态跟踪（conv_id、is_persisted flag）。当前 trade-off：
        # 断连丢失本轮数据 vs 代码复杂度 + 可能重复写入，选前者（历史显示已有数据）。
        conv_id, msg_id = _persist(db, user, body.question, final, body.conversation_id)
        if "insight" not in emitted:  # 极端兜底：没有任何 final_answer 也让前端正常结束
            yield {"event": "insight", "data": json.dumps({"delta": "（无内容）"}, ensure_ascii=False)}
        yield {"event": "done", "data": json.dumps(
            {"msg_id": msg_id, "conversation_id": conv_id, "has_answer": final.get("has_answer", True), "intent": final.get("intent")},
            ensure_ascii=False)}

    return EventSourceResponse(gen(), ping=15)


# ---------------------------------------------------------------- oh-my-openagent 进度
@app.get("/api/tasks/{task_id}/stream")
async def task_stream(task_id: str, user: User = Depends(get_current_user)):
    """SSE：订阅采集任务的进度事件。
    事件类型：stage（{stage, status, preview}）、done、error。
    前端用 task_id 订阅后逐阶段渲染进度条。
    """
    import asyncio as _asyncio
    from .agent_pipeline import _get_progress as get_progress

    async def gen():
        last_stage = None
        deadline = _asyncio.get_event_loop().time() + 180  # 3 min max
        poll_interval = 1.0

        while _asyncio.get_event_loop().time() < deadline:
            progress = get_progress(task_id)
            if progress is None:
                yield {"event": "stage", "data": json.dumps(
                    {"stage": "queued", "status": "pending", "message": "任务已提交，等待执行…"},
                    ensure_ascii=False)}
                await _asyncio.sleep(poll_interval)
                continue

            stage = progress.get("stage", "unknown")
            status = progress.get("status", "unknown")

            # Push event when stage changes
            if stage != last_stage:
                last_stage = stage
                yield {"event": "stage", "data": json.dumps(progress, ensure_ascii=False, default=str)}

            if stage == "done":
                yield {"event": "done", "data": json.dumps(
                    {"final_answer": progress.get("final_answer", ""), "task_id": task_id},
                    ensure_ascii=False)}
                return

            if status == "failed" or stage == "error":
                yield {"event": "error", "data": json.dumps(
                    {"message": progress.get("error", "采集任务失败"), "task_id": task_id},
                    ensure_ascii=False)}
                return

            await _asyncio.sleep(poll_interval)

        # Timeout
        yield {"event": "error", "data": json.dumps(
            {"message": "采集任务超时，请稍后重试", "task_id": task_id},
            ensure_ascii=False)}

    return EventSourceResponse(gen(), ping=15)


# ---------------------------------------------------------------- 历史会话
@app.get("/api/history")
def history(user: User = Depends(get_current_user), db: Session = Depends(get_db),
            limit: int = 50, offset: int = 0):
    """当前用户的会话列表（只返回自己的，按时间倒序，支持分页避免 OOM）。"""
    limit = min(max(int(limit), 1), 200)   # 1-200，防滥用
    convs = db.scalars(
        select(Conversation).where(Conversation.user_id == user.id)
        .order_by(Conversation.created_at.desc())
        .limit(limit).offset(max(int(offset), 0))
    ).all()
    return {"conversations": [
        {"id": c.id, "title": c.title, "created_at": c.created_at.isoformat() if c.created_at else None}
        for c in convs
    ]}


@app.get("/api/history/{conv_id}")
def history_detail(conv_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """按会话取消息，还原对话（含图表/引用）。只能看自己的（隔离）。"""
    conv = db.get(Conversation, conv_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(404, "会话不存在")
    msgs = db.scalars(
        select(Message).where(Message.conversation_id == conv_id).order_by(Message.created_at)
    ).all()
    out = []
    for m in msgs:
        # P0 FIX: 旧版写入/DB升级/写入中断时 result_meta 可能不是合法 JSON，
        # 裸 json.loads 会让整个接口 500，用户所有历史会话全部无法访问
        try:
            meta = json.loads(m.result_meta) if m.result_meta else None
        except (ValueError, TypeError):
            meta = None
        out.append({"role": m.role, "content": m.content, "intent": m.intent,
                    "chart": (meta or {}).get("chart"), "columns": (meta or {}).get("columns"),
                    "rows": (meta or {}).get("rows"), "citations": (meta or {}).get("citations")})
    return {"conversation_id": conv_id, "title": conv.title, "messages": out}


@app.delete("/api/history/{conv_id}")
def history_delete(conv_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """删除会话（连同其消息），按 user_id 校验归属——只能删自己的。"""
    conv = db.get(Conversation, conv_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(404, "会话不存在")
    db.query(Message).filter(Message.conversation_id == conv_id).delete(synchronize_session=False)
    db.delete(conv)
    db.commit()
    return {"conversation_id": conv_id, "deleted": True}


# ---------------------------------------------------------------- 收藏看板
_PAYLOAD_MAX = 65536   # 64KB：正常图表快照 < 3KB，此限制足够宽松且防 OOM 攻击


class InsightIn(BaseModel):
    title: str | None = None
    question: str | None = None
    intent: str | None = None
    payload: str | None = Field(default=None, max_length=_PAYLOAD_MAX)


def _insight_out(it: SavedInsight) -> dict:
    return {"id": it.id, "title": it.title, "question": it.question, "intent": it.intent,
            "payload": it.payload, "created_at": it.created_at.isoformat() if it.created_at else None}


@app.get("/api/insights")
def insights_list(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """当前用户的收藏洞察（按时间倒序）。"""
    rows = db.scalars(
        select(SavedInsight).where(SavedInsight.user_id == user.id).order_by(SavedInsight.created_at.desc())
    ).all()
    return {"insights": [_insight_out(it) for it in rows]}


@app.post("/api/insights")
def insights_create(body: InsightIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """收藏一条洞察快照到当前用户名下。"""
    it = SavedInsight(user_id=user.id, title=(body.title or "")[:255],
                      question=body.question, intent=body.intent, payload=body.payload)
    db.add(it)
    db.commit()
    db.refresh(it)
    return _insight_out(it)


@app.delete("/api/insights/{insight_id}")
def insights_delete(insight_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """移出看板（按 user_id 校验归属，只能删自己的）。"""
    it = db.get(SavedInsight, insight_id)
    if it is None or it.user_id != user.id:
        raise HTTPException(404, "收藏不存在")
    db.delete(it)
    db.commit()
    return {"id": insight_id, "deleted": True}


# ---------------------------------------------------------------- 一键分享
class ShareIn(BaseModel):
    title: str | None = None
    question: str | None = None
    intent: str | None = None
    payload: str | None = Field(default=None, max_length=_PAYLOAD_MAX)


@app.post("/api/share")
def share_create(body: ShareIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """生成只读公开分享，返回 token（前端拼成 /s/{token}）。"""
    token = secrets.token_urlsafe(9)
    sh = SharedInsight(token=token, user_id=user.id, title=(body.title or "")[:255],
                       question=body.question, intent=body.intent, payload=body.payload)
    db.add(sh)
    db.commit()
    return {"token": token}


@app.get("/api/public/share/{token}")
def share_public(token: str, db: Session = Depends(get_db)):
    """公开读取分享快照——**不需要登录**（这是对外的营销落地数据源）。"""
    sh = db.scalar(select(SharedInsight).where(SharedInsight.token == token))
    if sh is None:
        raise HTTPException(404, "分享不存在或已过期")
    return {"title": sh.title, "question": sh.question, "intent": sh.intent,
            "payload": sh.payload, "created_at": sh.created_at.isoformat() if sh.created_at else None}


# ---------------------------------------------------------------- 车型报价
_PRICE_SORT = {"price": "pmax", "brand": "brand", "series": "series"}


@app.get("/api/prices")
def prices(q: str = "", brand: str = "", sort: str = "price", order: str = "desc",
           limit: int = 80, user: User = Depends(get_current_user)):
    """车型报价：查 fact_price + dim_series + dim_brand（懂车帝实采）。支持搜索/品牌过滤/排序。
    排序列与方向都走白名单，搜索用绑定参数（防注入）。"""
    col = _PRICE_SORT.get(sort, "pmax")
    direction = "ASC" if str(order).lower() == "asc" else "DESC"
    where = ["p.guide_price_max IS NOT NULL"]
    params = {"limit": min(max(int(limit), 1), 300)}
    if q:
        where.append("(b.brand_name LIKE :kw OR s.series_name LIKE :kw)"); params["kw"] = f"%{q}%"
    if brand:
        where.append("b.brand_name = :brand"); params["brand"] = brand
    sql = (
        "SELECT b.brand_name AS brand, s.series_name AS series, s.segment AS segment, s.endurance_km AS endurance, "
        "MAX(p.guide_price_min) AS pmin, MAX(p.guide_price_max) AS pmax, "
        "MAX(p.price_text) AS price_text, MAX(p.descender_price) AS descender "
        "FROM fact_price p JOIN dim_series s ON s.series_id=p.series_id JOIN dim_brand b ON b.brand_id=s.brand_id "
        f"WHERE {' AND '.join(where)} GROUP BY s.series_id ORDER BY {col} {direction} LIMIT :limit"
    )
    with bi_engine.connect() as conn:
        rows = [dict(r._mapping) for r in conn.execute(sql_text(sql), params)]
    return {"count": len(rows), "items": [
        {"brand": r["brand"], "series": r["series"], "segment": r["segment"], "endurance": r["endurance"],
         "min": r["pmin"], "max": r["pmax"], "priceText": r["price_text"], "descender": r["descender"] or 0}
        for r in rows]}


@app.get("/api/prices/brands")
def price_brands(user: User = Depends(get_current_user)):
    """有报价的品牌列表（前端筛选下拉用）。"""
    sql = ("SELECT DISTINCT b.brand_name AS brand FROM fact_price p "
           "JOIN dim_series s ON s.series_id=p.series_id JOIN dim_brand b ON b.brand_id=s.brand_id "
           "WHERE p.guide_price_max IS NOT NULL ORDER BY b.brand_name")
    with bi_engine.connect() as conn:
        return {"brands": [r[0] for r in conn.execute(sql_text(sql))]}
