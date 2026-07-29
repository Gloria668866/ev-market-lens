"""知识库 API：上传 → 入库 → 列表/状态 → 软删除 → 问答。
【全部需登录，按 user_id 隔离；公共种子库（user_id=NULL）对所有人可见】

存储后端按 config.RAG_BACKEND 切换：
- 'local'（默认）：SQLite+numpy 本地向量库（local_store），上传走**同步**解析+BGE 向量化（免 Celery/MinIO/PG）；
- 'pg'：PostgreSQL+pgvector（pg），上传"轻返回+重后台"投 Celery 异步解析。
两后端接口一致，故下面的 list/status/delete/ask 不分叉。
"""
import logging
import os
import json

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException

logger = logging.getLogger("cheshijing")
from pydantic import BaseModel
from .auth import get_current_user_detached
from .capacity import ASK_SLOTS as _ASK_SLOTS
from .database import SessionLocal
from .models import Message, User
from .config import ASK_MAX_CONCURRENCY, RAG_BACKEND
from .usage_limits import (
    enforce_request_interval,
    reserve_question_slot,
    validate_question,
)

if RAG_BACKEND == "pg":
    from .rag import pg as store
else:
    from .rag import local_store as store

router = APIRouter(prefix="/api/kb", tags=["kb"])

_EXT2TYPE = {".pdf": "pdf", ".html": "html", ".htm": "html", ".md": "md", ".txt": "text"}
MAX_UPLOAD_MB = 20


class AskIn(BaseModel):
    question: str


@router.post("/upload")
async def upload(file: UploadFile = File(...), user: User = Depends(get_current_user_detached)):
    """上传文档建知识库：校验类型/大小后入库。local 同步返回 ready；pg 投异步返回 parsing。"""
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in _EXT2TYPE:
        raise HTTPException(415, f"不支持的文件类型 {ext or '(无扩展名)'}；仅支持 {'/'.join(sorted(_EXT2TYPE))}")
    max_bytes = MAX_UPLOAD_MB * 1024 * 1024
    chunks = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(413, f"文件超过 {MAX_UPLOAD_MB}MB 上限")
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data:
        raise HTTPException(400, "空文件")
    ftype = _EXT2TYPE[ext]

    if RAG_BACKEND == "pg":
        from .rag import ingest
        from .rag.tasks import ingest_document_task
        doc_id = ingest.stage_for_async(user.id, file.filename, data, ftype, title=file.filename)
        ingest_document_task.delay(doc_id)
        return {"doc_id": doc_id, "status": "parsing", "file_type": ftype}

    # local：同步解析 + 向量化（首次会加载 BGE 模型，稍慢；之后很快）
    from .rag.local_ingest import ingest_bytes
    try:
        doc_id, n = ingest_bytes(user.id, file.filename, data, ftype, title=file.filename)
    except Exception as e:  # noqa: BLE001
        # P1 FIX: 不把内部异常（含文件路径、依赖库信息）泄露给前端
        logger.error(f"[kb/upload] user={user.id} file={file.filename!r} error: {e}", exc_info=True)
        raise HTTPException(500, "文件解析失败，请检查文件格式或联系管理员")
    return {"doc_id": doc_id, "status": "ready", "file_type": ftype, "chunk_count": n}


@router.get("/list")
def kb_list(user: User = Depends(get_current_user_detached)):
    """当前用户的文档 + 公共种子库（已过滤软删，含解析状态）。"""
    documents = store.list_documents(user.id)
    for doc in documents:
        owner = doc.get("user_id")
        doc["is_public"] = owner is None or owner == 0
    return {"documents": documents}


@router.get("/{doc_id}")
def document_status(doc_id: int, user: User = Depends(get_current_user_detached)):
    """单个文档状态（前端轮询）。只能看自己的（公共种子库不在此暴露明细）。"""
    doc = store.get_document(doc_id)
    if doc is None or doc.get("user_id") != user.id or doc.get("deleted_at"):
        raise HTTPException(404, "文档不存在")
    return {"doc_id": doc["id"], "filename": doc["filename"], "status": doc["status"],
            "chunk_count": doc["chunk_count"], "file_type": doc["file_type"]}


@router.delete("/{doc_id}")
def kb_delete(doc_id: int, user: User = Depends(get_current_user_detached)):
    """软删除文档（只能删自己的；公共种子库不可删）。"""
    doc = store.get_document(doc_id)
    if doc is None or doc.get("user_id") != user.id or doc.get("deleted_at"):
        raise HTTPException(404, "文档不存在")
    store.soft_delete(doc_id)
    return {"doc_id": doc_id, "deleted": True}


@router.post("/ask")
def ask(body: AskIn, user: User = Depends(get_current_user_detached)):
    """RAG 在线问答：检索→归并→带引用生成（§5.4/5.5）。检索范围 = 自己的文档 + 公共种子库。"""
    from .rag.retrieve import answer_question
    question = validate_question(body.question)
    enforce_request_interval(user.id)
    if not _ASK_SLOTS.acquire(blocking=False):
        raise HTTPException(
            503,
            f"当前分析任务已满（最多 {ASK_MAX_CONCURRENCY} 个并发），请稍后重试",
        )
    try:
        with SessionLocal() as setup_db:
            conversation_id, _ = reserve_question_slot(
                setup_db,
                user.id,
                question,
                title_prefix="知识库：",
            )

        result = answer_question(user.id, question)

        with SessionLocal() as persist_db:
            assistant = Message(
                conversation_id=conversation_id,
                user_id=user.id,
                role="assistant",
                content=result.get("answer") or "",
                intent="rag",
                result_meta=json.dumps(
                    {"citations": result.get("citations") or [], "intent": "rag"},
                    ensure_ascii=False,
                    default=str,
                ),
            )
            persist_db.add(assistant)
            persist_db.commit()
            msg_id = assistant.id
        result["conversation_id"] = conversation_id
        result["msg_id"] = msg_id
        return result
    finally:
        _ASK_SLOTS.release()
