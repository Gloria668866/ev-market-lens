"""鉴权模块：注册 / 登录 / 当前用户，以及 get_current_user 依赖。

接口（前缀 /api/auth）：
- POST /register {username,password,nickname?}  → 校验重名 + bcrypt 哈希入库
- POST /login    {username,password}            → 校验 → {access_token, user}，更新 last_login_at
- GET  /me       (需 Bearer token)               → 当前用户

get_current_user(Depends)：解析 Authorization: Bearer <token> → user_id → 取用户。
其它受保护接口 Depends(get_current_user) 即可拿到当前 User。
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from .database import get_db
from .models import User, Conversation, Message, SavedInsight
from .security import hash_password, verify_password, create_access_token, decode_token

router = APIRouter(prefix="/api/auth", tags=["auth"])
_bearer = HTTPBearer(auto_error=False)  # auto_error=False：自己给中文 401，不抛默认 403


class RegisterIn(BaseModel):
    username: str
    password: str
    nickname: Optional[str] = None


class LoginIn(BaseModel):
    username: str
    password: str


def _user_public(u: User) -> dict:
    """对外返回的用户字段，绝不含 password_hash。"""
    return {
        "id": u.id,
        "username": u.username,
        "nickname": u.nickname,
        "role": u.role or "user",
        "disabled": bool(u.disabled),
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
    }


def get_current_user(
    cred: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    """从 Bearer token 解析出当前用户；缺失/无效/过期/用户不存在 → 401。"""
    if cred is None or not cred.credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "未提供登录凭证（需 Authorization: Bearer <token>）")
    result = decode_token(cred.credentials)
    if result is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "登录凭证无效或已过期")
    user_id, token_version = result
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在")
    if user.disabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "账号已被禁用，请联系管理员")
    # P1 FIX: 校验 token_version，改密码后旧 token 立即失效
    if (user.token_version or 0) != token_version:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "登录凭证已失效，请重新登录")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    """管理员守卫：非 admin → 403。用于 /api/admin/* 等受限接口。"""
    if (user.role or "user") != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "需要管理员权限")
    return user


@router.post("/register")
def register(body: RegisterIn, db: Session = Depends(get_db)):
    if not body.username.strip() or not body.password:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "用户名和密码不能为空")
    if len(body.password) < 6:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "密码至少 6 位")
    if db.scalar(select(User).where(User.username == body.username)):
        raise HTTPException(status.HTTP_409_CONFLICT, "用户名已存在")
    user = User(
        username=body.username.strip(),
        password_hash=hash_password(body.password),
        nickname=(body.nickname or body.username).strip(),
    )
    db.add(user)
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        # P1 FIX: 并发注册同名用户时 UNIQUE constraint 触发 IntegrityError → 409 而非 500
        if "UNIQUE" in str(e).upper() or "unique" in str(e).lower():
            raise HTTPException(status.HTTP_409_CONFLICT, "用户名已存在")
        raise
    db.refresh(user)
    return {"user": _user_public(user)}


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == body.username))
    # 用户名不存在与密码错误统一报「用户名或密码错误」，不泄露哪个错
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或密码错误")
    if user.disabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "账号已被禁用，请联系管理员")
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    return {
        "access_token": create_access_token(user.id, token_version=user.token_version or 0),
        "token_type": "bearer",
        "user": _user_public(user),
    }


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return {"user": _user_public(user)}


# ---------------------------------------------------------------- 账户自助（重度用户：改昵称/改密码/看用量）
class UpdateMeIn(BaseModel):
    nickname: str


class ChangePwdIn(BaseModel):
    old_password: str
    new_password: str


@router.patch("/me")
def update_me(body: UpdateMeIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """改昵称。"""
    nn = (body.nickname or "").strip()
    if not nn:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "昵称不能为空")
    user.nickname = nn[:64]
    db.commit()
    return {"user": _user_public(user)}


@router.post("/change-password")
def change_password(body: ChangePwdIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """改密码：先验旧密码。"""
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "原密码不正确")
    if len(body.new_password or "") < 6:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "新密码至少 6 位")
    user.password_hash = hash_password(body.new_password)
    # P1 FIX: 自增 token_version，使改密码前签发的所有 JWT 立即失效
    user.token_version = (user.token_version or 0) + 1
    db.commit()
    return {"ok": True}


@router.get("/stats")
def my_stats(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """我的用量：会话数 / 提问数 / 收藏数。"""
    conv = db.scalar(select(func.count(Conversation.id)).where(Conversation.user_id == user.id)) or 0
    asks = db.scalar(select(func.count(Message.id)).where(
        Message.user_id == user.id, Message.role == "user")) or 0
    favs = db.scalar(select(func.count(SavedInsight.id)).where(SavedInsight.user_id == user.id)) or 0
    return {"conversations": conv, "questions": asks, "insights": favs}


def bootstrap_admin(db: Session) -> tuple:
    """启动时确保有一个管理员账号（演示开箱即用）。ADMIN_USERNAME/ADMIN_PASSWORD 可在 .env 配置。
    返回 (action, username)：created / promoted / exists。"""
    import os
    uname = os.getenv("ADMIN_USERNAME", "admin")
    pwd = os.getenv("ADMIN_PASSWORD", "admin123")
    u = db.scalar(select(User).where(User.username == uname))
    if u is None:
        u = User(username=uname, password_hash=hash_password(pwd), nickname="管理员", role="admin")
        db.add(u)
        db.commit()
        return ("created", uname)
    if (u.role or "user") != "admin":
        u.role = "admin"
        db.commit()
        return ("promoted", uname)
    return ("exists", uname)
