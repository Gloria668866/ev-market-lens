"""Shared request-cost guards for every LLM-backed endpoint."""
import threading
import time
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import DAILY_QUESTION_LIMIT
from .models import Conversation, Message, User

MAX_QUESTION_LEN = 2000
MIN_REQUEST_INTERVAL_SECONDS = 0.5

_last_call: dict[int, float] = {}
_last_call_lock = threading.Lock()
_reservation_locks = tuple(threading.Lock() for _ in range(64))


def validate_question(question: str) -> str:
    value = (question or "").strip()
    if not value:
        raise HTTPException(400, "问题不能为空")
    if len(value) > MAX_QUESTION_LEN:
        raise HTTPException(400, f"问题过长，请控制在{MAX_QUESTION_LEN}字符以内")
    return value


def enforce_daily_question_limit(
    db: Session,
    user_id: int,
    limit: int | None = None,
) -> None:
    effective_limit = DAILY_QUESTION_LIMIT if limit is None else limit
    if effective_limit <= 0:
        return
    today_utc = datetime.now(timezone.utc).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
        tzinfo=None,
    )
    used = db.scalar(
        select(func.count(Message.id)).where(
            Message.user_id == user_id,
            Message.role == "user",
            Message.created_at >= today_utc,
        )
    ) or 0
    if used >= effective_limit:
        raise HTTPException(
            status_code=429,
            detail=f"今日体验次数已用完（每个账号 {effective_limit} 次），请明天再试",
        )


def reserve_question_slot(
    db: Session,
    user_id: int,
    question: str,
    conversation_id: int | None = None,
    *,
    title_prefix: str = "",
    limit: int | None = None,
) -> tuple[int, int]:
    """Atomically consume quota and persist the accepted user question.

    A completed-message counter can be bypassed with concurrent requests or an
    SSE disconnect.  Reserving before model work means accepted requests count
    even when the client leaves or the upstream model fails.  PostgreSQL uses a
    per-user row lock across processes; the striped process lock also makes the
    SQLite demo deterministic.
    """
    lock = _reservation_locks[user_id % len(_reservation_locks)]
    with lock:
        try:
            # Serialise count+insert for this user on PostgreSQL.  SQLite
            # ignores FOR UPDATE, so the striped lock above is its adapter.
            existing_user = db.scalar(
                select(User).where(User.id == user_id).with_for_update()
            )
            if existing_user is None:
                raise HTTPException(401, "用户不存在")
            enforce_daily_question_limit(db, user_id, limit)

            conversation = None
            if conversation_id is not None:
                conversation = db.get(Conversation, conversation_id)
                if conversation is not None and conversation.user_id != user_id:
                    conversation = None
            if conversation is None:
                conversation = Conversation(
                    user_id=user_id,
                    title=f"{title_prefix}{question[:40]}",
                )
                db.add(conversation)
                db.flush()

            message = Message(
                conversation_id=conversation.id,
                user_id=user_id,
                role="user",
                content=question,
            )
            db.add(message)
            db.commit()
            return conversation.id, message.id
        except HTTPException:
            db.rollback()
            raise
        except Exception:
            db.rollback()
            raise


def enforce_request_interval(user_id: int) -> None:
    now = time.monotonic()
    with _last_call_lock:
        previous = _last_call.get(user_id, 0.0)
        if now - previous < MIN_REQUEST_INTERVAL_SECONDS:
            raise HTTPException(429, "请稍后再试，间隔 0.5 秒")
        _last_call[user_id] = now
