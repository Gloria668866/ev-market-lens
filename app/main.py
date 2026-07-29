"""FastAPI 入口（架构与 SSE 事件协议见 docs/technical-design.md）：
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
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import select, text as sql_text
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from .graph import run_agent, stream_agent
from .db import engine as bi_engine          # 只读分析库（车型报价直接查）
from .auth import router as auth_router, get_current_user, get_current_user_detached
from .database import SessionLocal, app_engine, get_db, init_db
from .models import User, Conversation, Message, SavedInsight, SharedInsight, MemoryEpisode
from .memory import schedule_extraction, build_memory_block
from .capacity import ASK_SLOTS as _ASK_SLOTS
from .usage_limits import (
    enforce_request_interval,
    reserve_question_slot,
    validate_question,
)

from .config import (
    CORS_ALLOW_ORIGINS,
    DAILY_QUESTION_LIMIT,
    ASK_MAX_CONCURRENCY,
    EMBED_DIM,
    EMBED_MODEL_NAME,
    JWT_SECRET,
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MODEL,
    PIPELINE_LOCAL_FALLBACK,
    RAG_BACKEND,
    RERANK_MODEL_NAME,
    IS_PRODUCTION,
)

logger = logging.getLogger("cheshijing")
_ASK_EXECUTOR = ThreadPoolExecutor(
    max_workers=ASK_MAX_CONCURRENCY,
    thread_name_prefix="agent-ask",
)


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
# RAG 知识库路由（上传/列表/删除/问答）。
# 生产或显式选择 PG 后端时，导入失败必须阻止启动；否则会出现 /ready 假健康但核心接口 404。
KB_ROUTER_LOADED = False
try:
    from .kb import router as kb_router
    app.include_router(kb_router)
    KB_ROUTER_LOADED = True
except Exception as _e:  # noqa: BLE001
    if IS_PRODUCTION or RAG_BACKEND == "pg":
        raise RuntimeError("RAG kb route failed to load in required mode") from _e
    logger.warning(f"RAG kb route not loaded (missing deps or PG not started): {_e}")


def _startup():
    import os as _os
    _env = _os.getenv("APP_ENV", "development").lower()
    _is_prod = _env in ("production", "prod")
    _admin_password = _os.getenv("ADMIN_PASSWORD", "admin123")
    if _is_prod and not _configured_secret_ready(_admin_password, min_length=12):
        raise SystemExit("❌ 生产环境 ADMIN_PASSWORD 为空、过短或仍是公开占位值")
    if not _configured_secret_ready(JWT_SECRET, min_length=32):
        if _is_prod:
            raise SystemExit("❌ 生产环境 JWT_SECRET 为空、过短或仍是公开占位值")
        logger.warning("JWT_SECRET 仍是默认弱密钥！上线/演示前务必设置随机强密钥")
    if _is_prod and not _llm_config_ready():
        raise SystemExit("❌ 生产环境缺少有效 LLM_API_KEY，或仍在使用 REPLACE 占位值")

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
    if _admin_password == "admin123":
        logger.warning("管理员默认密码仍是 admin123！上线/公开演示前请在 .env 设置 ADMIN_PASSWORD。")
    # 配置自检：base_url 与 model 跨厂商不一致 = 静默连错 API（O7：qwen 默认值 + deepseek base 的坑）。
    _base, _model = LLM_BASE_URL.lower(), LLM_MODEL.lower()
    _provider = next((p for p in ("deepseek", "dashscope", "moonshot", "openai", "siliconflow") if p in _base), None)
    if _provider == "deepseek" and "deepseek" not in _model:
        logger.warning(f"LLM 配置可能不匹配：LLM_BASE_URL 指向 DeepSeek，但 LLM_MODEL='{LLM_MODEL}'（非 deepseek-*）。请核对 .env。")
    elif _provider == "dashscope" and not (_model.startswith("qwen") or _model.startswith("qwq")):
        logger.warning(f"LLM 配置可能不匹配：LLM_BASE_URL 指向 DashScope/通义，但 LLM_MODEL='{LLM_MODEL}'。请核对 .env。")


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    _startup()
    yield


# FastAPI lifespan replaces deprecated @app.on_event("startup") while preserving
# the existing router construction order.
app.router.lifespan_context = _lifespan


class Ask(BaseModel):
    question: str
    conversation_id: int | None = None  # 可选：续接已有会话；缺省则新建


def _model_artifact_available(name: str) -> bool:
    """Cheap local artifact validation without materializing model tensors.

    A path-only check marked the previously truncated BGE file as healthy.
    safetensors.safe_open validates the header and tensor offsets against the
    file length, which catches that corruption while keeping the normal health
    probe inexpensive.
    """
    if str(name).startswith(("BAAI/", "AI-ModelScope/")):
        return True  # remote id; deep=true verifies the first real inference
    model_file = Path(name) / "model.safetensors"
    if not model_file.is_file():
        return False
    try:
        from safetensors import safe_open
        with safe_open(str(model_file), framework="pt", device="cpu") as handle:
            return bool(list(handle.keys()))
    except Exception:
        logger.warning("Invalid model artifact: %s", model_file, exc_info=True)
        return False


def _deep_model_health() -> tuple[bool, bool]:
    """Run one real embedding and reranking inference for startup readiness."""
    try:
        from .rag import embed
        vector = embed.embed_query("新能源汽车市场健康检查")
        embed_ok = vector is not None and len(vector) == EMBED_DIM
    except Exception:
        logger.warning("Deep health: embedding inference failed", exc_info=True)
        embed_ok = False
    try:
        scores = embed.rerank_scores(
            "新能源汽车市场健康检查",
            ["新能源汽车市场健康检查"],
        )
        reranker_ok = bool(scores) and 0.0 <= float(scores[0]) <= 1.0
    except Exception:
        logger.warning("Deep health: reranker inference failed", exc_info=True)
        reranker_ok = False
    return embed_ok, reranker_ok


_deep_health_cache_lock = threading.Lock()
_deep_health_cache: tuple[float, tuple[bool, bool]] | None = None
_DEEP_HEALTH_TTL_SECONDS = 300


def _cached_deep_model_health() -> tuple[bool, bool]:
    """Bound anonymous deep probes to one real inference per five minutes/process."""
    global _deep_health_cache
    import time

    now = time.monotonic()
    with _deep_health_cache_lock:
        if (
            _deep_health_cache is not None
            and now - _deep_health_cache[0] < _DEEP_HEALTH_TTL_SECONDS
        ):
            return _deep_health_cache[1]
        result = _deep_model_health()
        _deep_health_cache = (now, result)
        return result


def _llm_config_ready(api_key: str | None = None) -> bool:
    """Reject empty/template credentials without making a paid provider request."""
    value = (LLM_API_KEY if api_key is None else api_key).strip()
    if not value:
        return False
    lowered = value.lower()
    return not any(marker in lowered for marker in ("replace", "changeme", "your_provider_key"))


def _configured_secret_ready(value: str | None, min_length: int) -> bool:
    candidate = (value or "").strip()
    if len(candidate) < min_length:
        return False
    lowered = candidate.lower()
    return not any(
        marker in lowered
        for marker in ("replace", "changeme", "change_me", "insecure", "admin123")
    )


def _health_payload(deep: bool = False) -> dict:
    """Collect dependency readiness; ``deep=true`` performs real model inference."""
    analysis_db_ok = False
    try:
        with bi_engine.connect() as conn:
            conn.execute(sql_text("SELECT 1"))
            conn.execute(sql_text(
                "SELECT brand_id, brand_name FROM dim_brand LIMIT 0"
            ))
            conn.execute(sql_text(
                "SELECT series_id, brand_id, series_name FROM dim_series LIMIT 0"
            ))
            conn.execute(sql_text(
                "SELECT date_id, year, month FROM dim_date LIMIT 0"
            ))
            sales_probe = conn.execute(sql_text(
                "SELECT series_id, date_id, volume FROM fact_sales_rank LIMIT 1"
            ))
            if sales_probe.first() is None:
                raise RuntimeError("fact_sales_rank is empty")
            conn.execute(sql_text(
                "SELECT series_id, date_id, guide_price_min FROM fact_price LIMIT 0"
            ))
            conn.execute(sql_text(
                "SELECT series_id, date_id, score FROM fact_review LIMIT 0"
            ))
        analysis_db_ok = True
    except Exception:
        logger.warning("Health probe: analysis database unavailable", exc_info=True)

    app_db_ok = False
    try:
        with app_engine.connect() as conn:
            conn.execute(sql_text("SELECT 1"))
            conn.execute(sql_text(
                "SELECT id, username, role, disabled, token_version "
                "FROM users LIMIT 0"
            ))
            conn.execute(sql_text(
                "SELECT id, user_id FROM conversation LIMIT 0"
            ))
            conn.execute(sql_text(
                "SELECT id, conversation_id, user_id, result_meta "
                "FROM message LIMIT 0"
            ))
            conn.execute(sql_text(
                "SELECT id, user_id, conversation_id FROM memory_episode LIMIT 0"
            ))
        app_db_ok = True
    except Exception:
        logger.warning("Health probe: application database unavailable", exc_info=True)

    rag_store_ok = True
    object_store_ok = True
    embedding_store_compatible = True
    embedding_store_stats: dict = {}
    if RAG_BACKEND == "pg":
        try:
            from .rag import pg
            with pg.conn() as conn:
                conn.execute("SELECT 1")
                conn.execute(
                    "SELECT id, user_id, status FROM kb_document LIMIT 0"
                )
                conn.execute(
                    "SELECT chunk_id, doc_id, user_id, embedding, "
                    "embedding_model_version, embedding_dim "
                    "FROM kb_chunk LIMIT 0"
                )
                conn.execute("SELECT '[0,0]'::vector <=> '[0,0]'::vector")
            embedding_store_stats = pg.embedding_compatibility_stats()
            embedding_store_compatible = (
                embedding_store_stats.get("column_dim") == EMBED_DIM
                and embedding_store_stats.get("compatible", 0)
                == embedding_store_stats.get("retrievable", 0)
                and embedding_store_stats.get("missing", 0) == 0
                and embedding_store_stats.get("legacy", 0) == 0
                and embedding_store_stats.get("mismatched", 0) == 0
            )
        except Exception:
            rag_store_ok = False
            embedding_store_compatible = False
            logger.warning("Health probe: pgvector store unavailable", exc_info=True)
        try:
            from .rag import store
            object_store_ok = store.client().bucket_exists(store.MINIO_BUCKET_UPLOADS)
        except Exception:
            object_store_ok = False
            logger.warning("Health probe: object store unavailable", exc_info=True)
    else:
        try:
            from .rag import local_store
            embedding_store_stats = local_store.embedding_compatibility_stats()
            embedding_store_compatible = (
                embedding_store_stats.get("compatible", 0)
                == embedding_store_stats.get("retrievable", 0)
                and embedding_store_stats.get("missing", 0) == 0
                and embedding_store_stats.get("legacy", 0) == 0
                and embedding_store_stats.get("mismatched", 0) == 0
            )
        except Exception:
            rag_store_ok = False
            embedding_store_compatible = False
            logger.warning(
                "Health probe: local RAG store unavailable",
                exc_info=True,
            )

    try:
        from .agent_tools import search_provider_status

        web_search_status = search_provider_status()
        web_search_official_api = bool(
            web_search_status.get("official_api_ready")
        )
    except Exception:
        web_search_status = {
            "official_api_ready": False,
            "mode": "status_unavailable",
            "error": "search provider status unavailable",
        }
        web_search_official_api = False
        logger.warning("Health probe: search provider status unavailable", exc_info=True)
    # Local development may intentionally exercise the HTML fallback without
    # buying an API key. Production must not advertise the unreliable fallback
    # as a ready research capability.
    web_search_ready = web_search_official_api or not IS_PRODUCTION

    try:
        from .agent_pipeline import _redis_available
        redis_ok = _redis_available()
    except Exception:
        redis_ok = False

    embed_ok = _model_artifact_available(EMBED_MODEL_NAME)
    reranker_ok = _model_artifact_available(RERANK_MODEL_NAME)
    llm_config_ok = _llm_config_ready()
    if deep and embed_ok and reranker_ok:
        embed_ok, reranker_ok = _cached_deep_model_health()

    queue_mode = "celery" if redis_ok else (
        "local_background" if PIPELINE_LOCAL_FALLBACK else "unavailable"
    )
    ready = (
        analysis_db_ok
        and app_db_ok
        and KB_ROUTER_LOADED
        and rag_store_ok
        and embedding_store_compatible
        and object_store_ok
        and web_search_ready
        and llm_config_ok
        and embed_ok
        and queue_mode != "unavailable"
    )
    return {
        "ok": True,
        "ready": ready,
        "status": "healthy" if ready and reranker_ok else "degraded",
        "services": {
            "analysis_db": analysis_db_ok,
            "application_db": app_db_ok,
            "kb_router": KB_ROUTER_LOADED,
            "rag_backend": RAG_BACKEND,
            "rag_store": rag_store_ok,
            "embedding_store_compatible": embedding_store_compatible,
            "embedding_store": embedding_store_stats,
            "reindex_required": (
                embedding_store_stats.get("missing", 0)
                + embedding_store_stats.get("legacy", 0)
                + embedding_store_stats.get("mismatched", 0)
            ) > 0,
            "object_store": object_store_ok,
            "web_search_official_api": web_search_official_api,
            "web_search": web_search_status,
            "llm_config": llm_config_ok,
            "embedding": embed_ok,
            "reranker": reranker_ok,
            "redis": redis_ok,
            "collection_queue": queue_mode,
            "model_probe": "inference" if deep else "artifact",
        },
    }


@app.get("/health")
def health(deep: bool = False):
    """Liveness/diagnostics endpoint; always responds so operators can inspect failures."""
    return _health_payload(deep)


@app.get("/ready")
def readiness(deep: bool = False):
    """Readiness endpoint: return 503 unless every required dependency is healthy."""
    payload = _health_payload(deep)
    status_code = 200 if payload["ready"] and payload["status"] == "healthy" else 503
    return JSONResponse(status_code=status_code, content=payload)


# ---------------------------------------------------------------- 落库
def _row_arrays(state) -> list:
    """结果集 dict 行 → 按列序的数组行（§9.1 rows 事件要数组）。"""
    cols = state.get("cols") or []
    return [[r.get(c) for c in cols] for r in (state.get("rows") or [])]


_PERSISTED_TRACE_FIELDS = frozenset({
    "node",
    "intent",
    "path",
    "confidence",
    "nlu_source",
    "nlu_latency_ms",
    "nlu_llm_calls",
    "llm_classified",
    "attempt",
    "valid",
    "reason",
    "error",
    "degraded",
    "has_evidence",
    "evidence_count",
    "duration_ms",
})


def _trace_for_history(trace: list[dict]) -> list[dict]:
    """Keep diagnostic decisions without persisting prompts, rows or payloads."""
    return [
        {
            key: value
            for key, value in item.items()
            if key in _PERSISTED_TRACE_FIELDS
        }
        for item in trace
        if isinstance(item, dict)
    ]


def _persist_answer(
    db: Session,
    user_id: int,
    state: dict,
    conversation_id: int,
) -> tuple[int, int]:
    """Append the assistant result to a previously reserved user question."""
    conv = db.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user_id:
        raise RuntimeError("reserved conversation is missing or belongs to another user")
    meta = {
        "columns": state.get("cols") or [],
        "rows": _row_arrays(state),
        "chart": state.get("chart"),
        "citations": state.get("citations") or [],
        "intent": state.get("intent"),
        "trace": _trace_for_history(state.get("trace") or []),
        "task_id": state.get("task_id"),
    }
    assistant = Message(
        conversation_id=conv.id, user_id=user_id, role="assistant",
        content=(state.get("final_answer") or "")[:4000],
        intent=state.get("intent"), sql_text=state.get("sql"),
        result_meta=json.dumps(meta, ensure_ascii=False, default=str),
    )
    db.add(assistant)
    db.commit()

    if state.get("task_id"):
        from .agent_pipeline import link_task_message
        link_task_message(
            state["task_id"],
            user_id=user_id,
            conversation_id=conv.id,
            assistant_message_id=assistant.id,
        )

    # 有条件调度后台记忆提取（有界线程池、进程内去重）
    msg_count = db.query(Message).filter_by(conversation_id=conv.id).count()
    schedule_extraction(user_id, conv.id, msg_count)

    return conv.id, assistant.id


# ---------------------------------------------------------------- 问答
@app.post("/api/ask_sync")
def ask_sync(body: Ask, user: User = Depends(get_current_user_detached)):
    """同步返回完整结果（调试用）。"""
    question = validate_question(body.question)
    enforce_request_interval(user.id)
    if not _ASK_SLOTS.acquire(blocking=False):
        raise HTTPException(
            503,
            f"当前分析任务已满（最多 {ASK_MAX_CONCURRENCY} 个并发），请稍后重试",
        )
    try:
        # Keep application DB sessions shorter than the potentially slow Agent
        # run, exactly as the SSE path does.
        with SessionLocal() as setup_db:
            history = _load_history(setup_db, user, body.conversation_id)
            conv_id, _ = reserve_question_slot(
                setup_db,
                user.id,
                question,
                body.conversation_id,
                limit=DAILY_QUESTION_LIMIT,
            )
            try:
                mem_block = build_memory_block(setup_db, user.id, question)
                if mem_block:
                    history = [{"role": "system", "content": mem_block}] + history
            except Exception:
                pass

        state = run_agent(question, user.id, history=history)
        with SessionLocal() as persist_db:
            conv_id, msg_id = _persist_answer(
                persist_db,
                user.id,
                state,
                conv_id,
            )
        return {
            "intent": state.get("intent"), "sql": state.get("sql"),
            "columns": state.get("cols") or [], "rows": _row_arrays(state),
            "chart": state.get("chart"), "answer": state.get("final_answer"),
            "citations": state.get("citations") or [], "has_answer": state.get("has_answer", True),
            "conversation_id": conv_id, "msg_id": msg_id,
            "trace": [t.get("node") for t in (state.get("trace") or [])],
        }
    finally:
        _ASK_SLOTS.release()


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
async def ask(body: Ask, user: User = Depends(get_current_user_detached)):
    """SSE（§9.1）：stage(accepted) → intent → [sql] → [rows] → [chart] → insight(逐段 delta) → [citation...] → done。
    **渐进推送**：用 LangGraph 流式跑图，某节点一完成、对应字段一出现就立刻推事件（不再等整图跑完一次性全出）。
    纯 RAG 无 sql/rows/chart，只有 insight(答案)+citation；出错推 error。"""
    # 在构建记忆块和启动 worker 前拒绝无效/超额请求，避免恶意长输入先消耗
    # embedding/数据库资源。HTTP 4xx 也比“200 后再推 SSE error”更便于网关计量。
    question = validate_question(body.question)
    enforce_request_interval(user.id)

    if not _ASK_SLOTS.acquire(blocking=False):
        raise HTTPException(
            503,
            f"当前分析任务已满（最多 {ASK_MAX_CONCURRENCY} 个并发），请稍后重试",
        )

    try:
        # All application-DB work finishes before EventSourceResponse is
        # returned.  No SQLAlchemy Session is retained by the long-lived stream.
        with SessionLocal() as setup_db:
            history = _load_history(setup_db, user, body.conversation_id)
            conv_id, _ = reserve_question_slot(
                setup_db,
                user.id,
                question,
                body.conversation_id,
                limit=DAILY_QUESTION_LIMIT,
            )
            try:
                mem_block = build_memory_block(setup_db, user.id, question)
                if mem_block:
                    history = [{"role": "system", "content": mem_block}] + history
            except Exception:
                pass
    except Exception:
        _ASK_SLOTS.release()
        raise

    q: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    stop_event = threading.Event()

    def _async_put(item):
        try:
            loop.call_soon_threadsafe(q.put_nowait, item)
        except RuntimeError:
            # Event loop already closed after disconnect/shutdown.
            return

    def _bounded_worker():
        try:
            _run_agent_worker(
                question,
                user.id,
                history,
                _async_put,
                stop_event,
            )
        finally:
            _ASK_SLOTS.release()

    try:
        _ASK_EXECUTOR.submit(_bounded_worker)
    except Exception:
        _ASK_SLOTS.release()
        raise HTTPException(503, "分析线程池暂不可用，请稍后重试")

    async def gen():
        yield {"event": "stage", "data": json.dumps(
            {"stage": "accepted", "message": "已接收，正在分析问题…"}, ensure_ascii=False)}

        # 有界线程池中的同步 LangGraph 通过线程安全队列桥接回事件循环。
        _last_intent = None
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
            if snap.get("task_id") and "collection" not in emitted:
                emitted.add("collection")
                yield {"event": "collection", "data": json.dumps(
                    {"task_id": snap["task_id"], "status": "queued"},
                    ensure_ascii=False)}
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
            stop_event.set()   # 客户端断连或正常结束，通知 worker 尽快停止

        if err is not None:
            yield {"event": "error", "data": json.dumps(
                {"code": "AGENT_ERROR", "message": "处理失败，请换种问法或缩小范围。"}, ensure_ascii=False)}
            logger.error(f"[ask] stream_agent 失败 user={user.id} q={question[:80]!r}: {err}",
                         exc_info=err)
            return

        # 用户问题已在启动模型前原子预扣并落库；这里用新的短 Session 只追加
        # assistant 结果。若客户端中途断连，问题仍计入配额，避免断连绕过成本保护；
        # 尚未完成的 assistant 不伪造写入。
        with SessionLocal() as persist_db:
            conv_id_done, msg_id = _persist_answer(
                persist_db,
                user.id,
                final,
                conv_id,
            )
        if "insight" not in emitted:  # 极端兜底：没有任何 final_answer 也让前端正常结束
            yield {"event": "insight", "data": json.dumps({"delta": "（无内容）"}, ensure_ascii=False)}
        yield {"event": "done", "data": json.dumps(
            {"msg_id": msg_id, "conversation_id": conv_id_done, "has_answer": final.get("has_answer", True), "intent": final.get("intent")},
            ensure_ascii=False)}

    return EventSourceResponse(gen(), ping=15)


# ---------------------------------------------------------------- oh-my-openagent 进度
@app.get("/api/tasks/{task_id}/stream")
async def task_stream(task_id: str, user: User = Depends(get_current_user_detached)):
    """SSE：订阅采集任务的进度事件。
    事件类型：stage（{stage, status, preview}）、done、error。
    前端用 task_id 订阅后逐阶段渲染进度条。
    """
    import asyncio as _asyncio
    from .agent_pipeline import _get_progress as get_progress

    initial = get_progress(task_id)
    if initial is None or int(initial.get("user_id", -1)) != user.id:
        # 404 avoids revealing whether another user's task id exists.
        raise HTTPException(404, "任务不存在")

    async def gen():
        last_stage = None
        deadline = _asyncio.get_event_loop().time() + 900  # 15 min for multi-stage collection
        poll_interval = 1.0

        while _asyncio.get_event_loop().time() < deadline:
            progress = get_progress(task_id)
            if progress is None:
                yield {"event": "error", "data": json.dumps(
                    {"message": "任务状态已过期", "task_id": task_id},
                    ensure_ascii=False)}
                return
            if int(progress.get("user_id", -1)) != user.id:
                yield {"event": "error", "data": json.dumps(
                    {"message": "任务不可访问", "task_id": task_id},
                    ensure_ascii=False)}
                return

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
    db.query(MemoryEpisode).filter(
        MemoryEpisode.conversation_id == conv_id,
    ).delete(synchronize_session=False)
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
        f"WHERE {' AND '.join(where)} "
        "GROUP BY b.brand_name, s.series_id, s.series_name, s.segment, s.endurance_km "
        f"ORDER BY {col} {direction} LIMIT :limit"
    )
    count_sql = (
        "SELECT COUNT(DISTINCT s.series_id) "
        "FROM fact_price p JOIN dim_series s ON s.series_id=p.series_id "
        "JOIN dim_brand b ON b.brand_id=s.brand_id "
        f"WHERE {' AND '.join(where)}"
    )
    with bi_engine.connect() as conn:
        total = int(conn.execute(
            sql_text(count_sql),
            {k: v for k, v in params.items() if k != "limit"},
        ).scalar_one())
        rows = [dict(r._mapping) for r in conn.execute(sql_text(sql), params)]
    return {"count": total, "returned": len(rows), "items": [
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
