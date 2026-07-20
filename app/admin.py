"""管理员后台（PRD-2 §17 延伸）：用户管理 + 全局概览。全部需 admin 角色（require_admin）。

接口（前缀 /api/admin）：
- GET    /overview           全局统计（用户/管理员/会话/提问/收藏）
- GET    /users              用户列表 + 每人用量（会话/提问/收藏）
- PATCH  /users/{id}         改角色(role) / 启用禁用(disabled)
- POST   /users/{id}/reset-password   重置某用户密码
- DELETE /users/{id}         删除用户及其数据（会话/消息/收藏/分享）

安全护栏：不能禁用/降级/删除自己；不能动"最后一个管理员"，避免把自己锁在门外。
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, func, delete
from sqlalchemy.orm import Session

from .auth import require_admin, _user_public
from .database import get_db
from .models import User, Conversation, Message, SavedInsight, SharedInsight
from .security import hash_password

router = APIRouter(prefix="/api/admin", tags=["admin"])


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
    # 级联清理该用户数据（应用库内；本地知识库 chunk 另属 store，演示从简不清）
    db.execute(delete(Message).where(Message.user_id == user_id))
    db.execute(delete(Conversation).where(Conversation.user_id == user_id))
    db.execute(delete(SavedInsight).where(SavedInsight.user_id == user_id))
    db.execute(delete(SharedInsight).where(SharedInsight.user_id == user_id))
    db.delete(u)
    db.commit()
    return {"id": user_id, "deleted": True}
