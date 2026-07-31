"""Quota reservation is atomic and counts accepted work before model execution."""

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select


def test_concurrent_reservations_cannot_exceed_daily_limit():
    from app.database import SessionLocal, init_db
    from app.models import Message, User
    from app.usage_limits import reserve_question_slot

    init_db()
    username = f"controlled_{uuid4().hex}"
    with SessionLocal() as db:
        user = User(
            username=username,
            password_hash="test-only",
            role="user",
        )
        db.add(user)
        db.commit()
        user_id = user.id

    def reserve(index: int):
        with SessionLocal() as db:
            try:
                return reserve_question_slot(
                    db,
                    user_id,
                    f"question-{index}",
                    limit=1,
                )
            except HTTPException as exc:
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(reserve, (1, 2)))

    assert sum(isinstance(outcome, tuple) for outcome in outcomes) == 1
    assert outcomes.count(429) == 1
    with SessionLocal() as db:
        used = db.scalar(
            select(func.count(Message.id)).where(
                Message.user_id == user_id,
                Message.role == "user",
            )
        )
    assert used == 1


def test_reserved_question_survives_model_failure():
    from app.database import SessionLocal, init_db
    from app.models import Message, User
    from app.usage_limits import reserve_question_slot

    init_db()
    username = f"controlled_{uuid4().hex}"
    with SessionLocal() as db:
        user = User(
            username=username,
            password_hash="test-only",
            role="user",
        )
        db.add(user)
        db.commit()
        conversation_id, message_id = reserve_question_slot(
            db,
            user.id,
            "accepted before upstream call",
            limit=5,
        )

    # No assistant is written: this simulates timeout/disconnect/upstream error.
    with SessionLocal() as db:
        message = db.get(Message, message_id)
        assert message is not None
        assert message.conversation_id == conversation_id
        assert message.role == "user"
        assert message.content == "accepted before upstream call"
