"""管理员后台：用户管理、全局概览与进程指标。见技术设计第 8/9 节。

接口（前缀 /api/admin）：
- GET    /overview           全局统计（用户/管理员/会话/提问/收藏）
- GET    /metrics            当前 API 进程的 LLM 调用/延迟/token/成本快照
- GET    /users              用户列表 + 每人用量（会话/提问/收藏）
- POST   /users              管理员创建受控演示账号
- PATCH  /users/{id}         改角色(role) / 启用禁用(disabled)
- POST   /users/{id}/reset-password   重置某用户密码
- DELETE /users/{id}         删除用户及其数据（会话/消息/收藏/分享）

安全护栏：不能禁用/降级/删除自己；不能动"最后一个管理员"，避免把自己锁在门外。
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, func, delete
from sqlalchemy.orm import Session

from .auth import require_admin, _user_public
from .database import get_db
from .config import ASK_MAX_CONCURRENCY, LLM_MODEL, RAG_BACKEND
from .llm import get_metrics
from .models import (
    User,
    Conversation,
    KbDocument,
    MemoryEpisode,
    Message,
    SavedInsight,
    SharedInsight,
    UserProfile,
)
from .security import hash_password

router = APIRouter(prefix="/api/admin", tags=["admin"])
logger = logging.getLogger("cheshijing.admin")


def _admin_count(db: Session) -> int:
    return db.scalar(select(func.count(User.id)).where(User.role == "admin")) or 0


@router.get("/overview")
def overview(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return {
        "users": db.scalar(select(func.count(User.id))) or 0,
        "admins": _admin_count(db),
        "disabled": db.scalar(select(func.count(User.id)).where(User.disabled == True)) or 0,  # noqa: E712
        "conversations": db.scalar(select(func.count(Conversation.id))) or 0,
        "questions": db.scalar(select(func.count(Message.id)).where(Message.role == "user")) or 0,
        "insights": db.scalar(select(func.count(SavedInsight.id))) or 0,
        "shares": db.scalar(select(func.count(SharedInsight.id))) or 0,
    }


@router.get("/metrics")
def metrics(admin: User = Depends(require_admin)):
    """Expose a secret-free, process-local LLM metrics snapshot to operators.

    This intentionally stays behind the admin guard.  It is not a replacement
    for a multi-process metrics backend: counters reset on restart and describe
    only the API worker that served this request.
    """
    return {
        "scope": "current_process",
        "resets_on_restart": True,
        "llm_model": LLM_MODEL,
        "ask_max_concurrency": ASK_MAX_CONCURRENCY,
        "llm": get_metrics(),
    }


@router.get("/users")
def list_users(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """所有用户 + 每人用量（会话/提问/收藏）。"""
    users = db.scalars(select(User).order_by(User.created_at)).all()
    conv = dict(db.execute(select(Conversation.user_id, func.count(Conversation.id))
                           .group_by(Conversation.user_id)).all())
    asks = dict(db.execute(select(Message.user_id, func.count(Message.id))
                           .where(Message.role == "user").group_by(Message.user_id)).all())
    favs = dict(db.execute(select(SavedInsight.user_id, func.count(SavedInsight.id))
                           .group_by(SavedInsight.user_id)).all())
    out = []
    for u in users:
        out.append({**_user_public(u),
                    "conversations": conv.get(u.id, 0),
                    "questions": asks.get(u.id, 0),
                    "insights": favs.get(u.id, 0)})
    return {"users": out}


class PatchUserIn(BaseModel):
    role: str | None = None       # 'user' / 'admin'
    disabled: bool | None = None


class CreateUserIn(BaseModel):
    username: str
    password: str
    nickname: str | None = None
    role: str = "user"


@router.post("/users")
def create_user(body: CreateUserIn,
                admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Create a controlled account while public self-registration stays closed."""
    username = body.username.strip()
    if not username or not body.password:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "用户名和密码不能为空")
    if len(body.password) < 6:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "密码至少 6 位")
    if body.role not in ("user", "admin"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "role 只能是 user / admin")
    if db.scalar(select(User).where(User.username == username)):
        raise HTTPException(status.HTTP_409_CONFLICT, "用户名已存在")
    user = User(
        username=username,
        password_hash=hash_password(body.password),
        nickname=(body.nickname or username).strip(),
        role=body.role,
    )
    db.add(user)
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        if "unique" in str(exc).lower():
            raise HTTPException(status.HTTP_409_CONFLICT, "用户名已存在") from exc
        raise
    db.refresh(user)
    return {"user": _user_public(user)}


@router.patch("/users/{user_id}")
def patch_user(user_id: int, body: PatchUserIn,
               admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")

    if body.role is not None:
        if body.role not in ("user", "admin"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "role 只能是 user / admin")
        # 不能把最后一个管理员降级（含自己）
        if (u.role or "user") == "admin" and body.role != "admin" and _admin_count(db) <= 1:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能降级最后一个管理员")
        u.role = body.role

    if body.disabled is not None:
        if u.id == admin.id and body.disabled:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能禁用自己")
        if body.disabled and (u.role or "user") == "admin" and _admin_count(db) <= 1:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能禁用最后一个管理员")
        u.disabled = body.disabled

    db.commit()
    return {"user": _user_public(u)}


class ResetPwdIn(BaseModel):
    new_password: str


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: int, body: ResetPwdIn,
                   admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    if len(body.new_password or "") < 6:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "新密码至少 6 位")
    u.password_hash = hash_password(body.new_password)
    u.token_version = int(u.token_version or 0) + 1
    db.commit()
    return {"ok": True}


@router.delete("/users/{user_id}")
def delete_user(user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    if u.id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能删除自己")
    if (u.role or "user") == "admin" and _admin_count(db) <= 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能删除最后一个管理员")
    # RAG 的 chunk 可能在独立本地库或 PG 原生表，必须先由对应后端清理。
    try:
        if RAG_BACKEND == "pg":
            from .rag import pg as rag_store
        else:
            from .rag import local_store as rag_store
        rag_store.purge_user_documents(user_id)
    except Exception as exc:  # noqa: BLE001
        logger.error("清理用户 %s 的 RAG 数据失败", user_id, exc_info=True)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "知识库清理失败，用户尚未删除，请稍后重试",
        ) from exc

    # 显式按外键依赖顺序清理，避免 SQLite 测试放行而 PostgreSQL 生产报错。
    db.execute(delete(MemoryEpisode).where(MemoryEpisode.user_id == user_id))
    db.execute(delete(Message).where(Message.user_id == user_id))
    db.execute(delete(Conversation).where(Conversation.user_id == user_id))
    db.execute(delete(SavedInsight).where(SavedInsight.user_id == user_id))
    db.execute(delete(SharedInsight).where(SharedInsight.user_id == user_id))
    db.execute(delete(UserProfile).where(UserProfile.user_id == user_id))
    db.execute(delete(KbDocument).where(KbDocument.user_id == user_id))
    db.delete(u)
    db.commit()
    return {"id": user_id, "deleted": True}
