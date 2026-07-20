"""密码哈希（bcrypt）+ JWT 签发/校验。密钥来自 .env，绝不入库。

P1 FIX: token_version 机制
  - 每次改密码时 users.token_version 自增
  - JWT payload 中写入 tv（token version）
  - get_current_user 校验 tv 是否与数据库匹配，不匹配则 401
  - 效果：改密码后旧 token 立即失效，攻击者无法继续使用
"""
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from jose import jwt, JWTError
from passlib.context import CryptContext

from .config import JWT_SECRET, JWT_EXPIRE_DAYS, JWT_ALGORITHM

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return _pwd.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd.verify(plain, hashed)


def create_access_token(user_id: int, token_version: int = 0) -> str:
    """签发 JWT，sub=用户ID，tv=token版本（改密码后自增），exp=JWT_EXPIRE_DAYS 后过期。"""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "tv": token_version,     # token version，校验时比对数据库中的版本
        "iat": now,
        "exp": now + timedelta(days=JWT_EXPIRE_DAYS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> Optional[Tuple[int, int]]:
    """校验并取出 (user_id, token_version)；无效/过期返回 None。"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return int(payload["sub"]), int(payload.get("tv", 0))
    except (JWTError, KeyError, ValueError, TypeError):
        return None
