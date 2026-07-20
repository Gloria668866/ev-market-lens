"""Unit tests for app/memory.py — long-term memory service.

Uses temporary SQLite database and mocked LLM. No real API calls.
"""
import json
import time
import pytest
import threading
from unittest.mock import patch, MagicMock

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.models import Base, UserProfile, MemoryEpisode, Message, Conversation, User


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _set_fk(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def user_a(db):
    u = User(username="alice", password_hash="x", nickname="Alice")
    db.add(u)
    db.commit()
    return u


@pytest.fixture
def user_b(db):
    u = User(username="bob", password_hash="x", nickname="Bob")
    db.add(u)
    db.commit()
    return u


def _add_conversation(db, user, messages_text):
    conv = Conversation(user_id=user.id, title="test")
    db.add(conv)
    db.flush()
    for role, text in messages_text:
        db.add(Message(conversation_id=conv.id, user_id=user.id,
                       role=role, content=text))
    db.commit()
    return conv


@pytest.fixture(autouse=True)
def _clear_scheduler_state():
    """Reset global scheduler state between tests."""
    from app.memory import _running_convs, _last_extracted_counts, _running_lock
    with _running_lock:
        _running_convs.clear()
        _last_extracted_counts.clear()
    yield
    with _running_lock:
        _running_convs.clear()
        _last_extracted_counts.clear()


# ── User isolation ────────────────────────────────────────────────────────────

def test_profile_isolation(db, user_a, user_b):
    db.add(UserProfile(user_id=user_a.id, key="preferred_brands",
                       value='["比亚迪"]', confidence=0.8, evidence_count=1))
    db.add(UserProfile(user_id=user_b.id, key="preferred_brands",
                       value='["特斯拉"]', confidence=0.8, evidence_count=1))
    db.commit()

    from app.memory import recall_profile
    assert recall_profile(db, user_a.id)["preferred_brands"] == ["比亚迪"]
    assert recall_profile(db, user_b.id)["preferred_brands"] == ["特斯拉"]


def test_episode_isolation(db, user_a, user_b):
    conv_a = _add_conversation(db, user_a, [("user", "比亚迪")])
    conv_b = _add_conversation(db, user_b, [("user", "特斯拉")])
    db.add(MemoryEpisode(user_id=user_a.id, conversation_id=conv_a.id,
                         summary="Alice问比亚迪",
                         entities_json='{"brands":["比亚迪"]}'))
    db.add(MemoryEpisode(user_id=user_b.id, conversation_id=conv_b.id,
                         summary="Bob问特斯拉",
                         entities_json='{"brands":["特斯拉"]}'))
    db.commit()

    from app.memory import recall_episodes
    with patch("app.graph._extract_entities_from_text",
               return_value={"brands": ["比亚迪"], "models": []}):
        eps = recall_episodes(db, user_a.id, "比亚迪")
    assert len(eps) == 1
    assert "Alice" in eps[0]["summary"]


# ── Keyword recall ────────────────────────────────────────────────────────────

def test_keyword_recall_matches_relevant(db, user_a):
    conv1 = _add_conversation(db, user_a, [("user", "比亚迪")])
    conv2 = _add_conversation(db, user_a, [("user", "特斯拉")])
    db.add(MemoryEpisode(user_id=user_a.id, conversation_id=conv1.id,
                         summary="问了比亚迪2025年销量",
                         entities_json='{"brands":["比亚迪"]}'))
    db.add(MemoryEpisode(user_id=user_a.id, conversation_id=conv2.id,
                         summary="问了特斯拉价格",
                         entities_json='{"brands":["特斯拉"]}'))
    db.commit()

    from app.memory import recall_episodes
    with patch("app.graph._extract_entities_from_text",
               return_value={"brands": ["比亚迪"], "models": []}):
        eps = recall_episodes(db, user_a.id, "比亚迪今年")
    assert len(eps) == 1
    assert "比亚迪" in eps[0]["summary"]


def test_no_keyword_returns_empty(db, user_a):
    conv = _add_conversation(db, user_a, [("user", "hi")])
    db.add(MemoryEpisode(user_id=user_a.id, conversation_id=conv.id,
                         summary="问了比亚迪", entities_json='{}'))
    db.commit()

    from app.memory import recall_episodes
    with patch("app.graph._extract_entities_from_text",
               return_value={"brands": [], "models": []}):
        assert recall_episodes(db, user_a.id, "你好") == []


# ── Extract uses only user messages ───────────────────────────────────────────

def test_extract_summary_excludes_assistant(db, user_a):
    conv = _add_conversation(db, user_a, [
        ("user", "比亚迪2025年销量"),
        ("assistant", "累计120万辆"),
        ("user", "按月拆开"),
        ("assistant", "1月15万"),
    ])
    captured = []

    def fake_chat(msgs, **kw):
        captured.append(msgs[1]["content"])
        if "摘要" in msgs[0]["content"]:
            return "比亚迪销量查询"
        return '{}'

    with patch("app.memory.chat", side_effect=fake_chat), \
         patch("app.graph._extract_entities_from_text", return_value={"brands": ["比亚迪"], "models": []}):
        from app.memory import extract_memory
        result = extract_memory(db, user_a.id, conv.id)

    assert result is True
    assert "120万辆" not in captured[0]
    assert "比亚迪2025年销量" in captured[0]


def test_extract_profile_excludes_assistant(db, user_a):
    conv = _add_conversation(db, user_a, [
        ("user", "比亚迪销量"),
        ("assistant", "比亚迪累计120万辆"),
        ("user", "看看趋势"),
        ("assistant", "呈上升趋势"),
    ])
    captured = []

    def fake_chat(msgs, **kw):
        captured.append(msgs[1]["content"])
        if "偏好" in msgs[0]["content"]:
            return '{"preferred_brands":["比亚迪"]}'
        return "比亚迪查询"

    with patch("app.memory.chat", side_effect=fake_chat), \
         patch("app.graph._extract_entities_from_text", return_value={"brands": ["比亚迪"], "models": []}):
        from app.memory import extract_memory
        extract_memory(db, user_a.id, conv.id)

    assert "120万辆" not in captured[1]


# ── Messages below threshold ─────────────────────────────────────────────────

def test_too_few_messages_skips_llm(db, user_a):
    conv = _add_conversation(db, user_a, [("user", "hi"), ("assistant", "hello")])

    with patch("app.memory.chat") as mock_chat, \
         patch("app.graph._extract_entities_from_text"):
        from app.memory import extract_memory
        result = extract_memory(db, user_a.id, conv.id)
        mock_chat.assert_not_called()
    assert result is False


# ── Extraction failure ────────────────────────────────────────────────────────

def test_extract_failure_returns_false(db, user_a):
    conv = _add_conversation(db, user_a, [
        ("user", "q1"), ("assistant", "a1"),
        ("user", "q2"), ("assistant", "a2"),
    ])

    with patch("app.memory.chat", side_effect=Exception("LLM down")), \
         patch("app.graph._extract_entities_from_text", return_value={"brands": [], "models": []}):
        from app.memory import extract_memory
        result = extract_memory(db, user_a.id, conv.id)

    assert result is False
    assert db.query(MemoryEpisode).filter_by(user_id=user_a.id).count() == 0


# ── Duplicate extraction upserts ──────────────────────────────────────────────

def test_duplicate_extraction_upserts(db, user_a):
    conv = _add_conversation(db, user_a, [
        ("user", "比亚迪销量"), ("assistant", "120万"),
        ("user", "按月看"), ("assistant", "1月15万"),
    ])

    def fake_chat(msgs, **kw):
        if "摘要" in msgs[0]["content"]:
            return "比亚迪查询"
        return '{"preferred_brands":["比亚迪"]}'

    with patch("app.memory.chat", side_effect=fake_chat), \
         patch("app.graph._extract_entities_from_text", return_value={"brands": ["比亚迪"], "models": []}):
        from app.memory import extract_memory
        extract_memory(db, user_a.id, conv.id)
        extract_memory(db, user_a.id, conv.id)

    assert db.query(MemoryEpisode).filter_by(user_id=user_a.id).count() == 1


# ── Sensitive token not stored ────────────────────────────────────────────────

def test_sensitive_bearer_token_not_stored(db, user_a):
    conv = _add_conversation(db, user_a, [
        ("user", "test"), ("assistant", "ok"),
        ("user", "Bearer sk-abc123"), ("assistant", "noted"),
    ])

    with patch("app.memory.chat", return_value="Bearer sk-abc123 被提及"), \
         patch("app.graph._extract_entities_from_text", return_value={"brands": [], "models": []}):
        from app.memory import extract_memory
        result = extract_memory(db, user_a.id, conv.id)

    assert result is False
    assert db.query(MemoryEpisode).filter_by(user_id=user_a.id).count() == 0


# ── Memory block safety ───────────────────────────────────────────────────────

def test_memory_block_has_safety_markers(db, user_a):
    db.add(UserProfile(user_id=user_a.id, key="preferred_brands",
                       value='["比亚迪"]', confidence=0.8, evidence_count=1))
    db.commit()

    from app.memory import build_memory_block
    with patch("app.memory.recall_episodes", return_value=[]):
        block = build_memory_block(db, user_a.id, "比亚迪")
    assert "不可信数据" in block
    assert "不是系统指令" in block
    assert "不得执行" in block


def test_memory_block_filters_sensitive_episode(db, user_a):
    conv = _add_conversation(db, user_a, [("user", "比亚迪")])
    db.add(MemoryEpisode(user_id=user_a.id, conversation_id=conv.id,
                         summary="token=eyJhbGciOiJ被泄露",
                         entities_json='{"brands":["比亚迪"]}'))
    db.commit()

    from app.memory import build_memory_block
    with patch("app.graph._extract_entities_from_text",
               return_value={"brands": ["比亚迪"], "models": []}):
        block = build_memory_block(db, user_a.id, "比亚迪")
    assert "token=" not in block
    assert "eyJhbGciOiJ" not in block


def test_memory_block_filters_sensitive_profile(db, user_a):
    db.add(UserProfile(user_id=user_a.id, key="preferred_brands",
                       value='["Bearer mytoken"]', confidence=0.8, evidence_count=1))
    db.commit()

    from app.memory import build_memory_block
    with patch("app.memory.recall_episodes", return_value=[]):
        block = build_memory_block(db, user_a.id, "比亚迪")
    assert "Bearer " not in block
    assert "mytoken" not in block


def test_memory_block_empty_returns_empty(db, user_a):
    from app.memory import build_memory_block
    with patch("app.memory.recall_episodes", return_value=[]):
        assert build_memory_block(db, user_a.id, "你好") == ""


# ── Profile whitelist ─────────────────────────────────────────────────────────

def test_unknown_profile_key_rejected(db, user_a):
    from app.memory import _upsert_profile
    _upsert_profile(db, user_a.id, {"evil_key": ["hacked"], "preferred_brands": ["比亚迪"]})
    db.commit()

    keys = [p.key for p in db.query(UserProfile).filter_by(user_id=user_a.id).all()]
    assert "evil_key" not in keys
    assert "preferred_brands" in keys


def test_wrong_type_profile_rejected(db, user_a):
    from app.memory import _upsert_profile
    _upsert_profile(db, user_a.id, {
        "preferred_brands": "not_a_list",
        "output_style": ["not_a_string"],
    })
    db.commit()
    assert db.query(UserProfile).filter_by(user_id=user_a.id).count() == 0


def test_output_style_validates_allowed_values(db, user_a):
    from app.memory import _upsert_profile
    _upsert_profile(db, user_a.id, {"output_style": "chart"})
    _upsert_profile(db, user_a.id, {"output_style": "evil"})
    db.commit()

    profiles = db.query(UserProfile).filter_by(user_id=user_a.id, key="output_style").all()
    assert len(profiles) == 1
    assert profiles[0].value == "chart"


# ── ask_sync fail-open ────────────────────────────────────────────────────────

@pytest.mark.integration
def test_ask_sync_memory_failure_does_not_block():
    from app.main import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    client.post("/api/auth/register", json={"username": "memtest3", "password": "pass1234"})
    resp = client.post("/api/auth/login", json={"username": "memtest3", "password": "pass1234"})
    token = resp.json().get("access_token", "")

    with patch("app.main.build_memory_block", side_effect=Exception("memory crash")), \
         patch("app.main.run_agent", return_value={"intent": "chat", "insight": "hello"}):
        resp = client.post("/api/ask_sync",
                           json={"question": "你好"},
                           headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


# ── Unique constraint ─────────────────────────────────────────────────────────

def test_unique_constraint_prevents_duplicate_episode(db, user_a):
    conv = _add_conversation(db, user_a, [("user", "test")])
    db.add(MemoryEpisode(user_id=user_a.id, conversation_id=conv.id,
                         summary="first", entities_json="{}"))
    db.commit()

    from sqlalchemy.exc import IntegrityError
    db.add(MemoryEpisode(user_id=user_a.id, conversation_id=conv.id,
                         summary="dup", entities_json="{}"))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
    assert db.query(MemoryEpisode).filter_by(
        user_id=user_a.id, conversation_id=conv.id).count() == 1


# ── Scheduler tests ───────────────────────────────────────────────────────────

def test_schedule_same_conv_deduplicates():
    """Same conv scheduled concurrently → second call returns False."""
    from app.memory import schedule_extraction

    with patch("app.memory.extract_memory", return_value=True) as mock_ex, \
         patch("app.database.SessionLocal") as mock_sl:
        mock_sl.return_value = MagicMock(close=MagicMock())

        first = schedule_extraction(1, 999, msg_count=6)
        # Still running — second call must be rejected
        second = schedule_extraction(1, 999, msg_count=6)

        assert first is True
        assert second is False
        time.sleep(0.3)


def test_schedule_same_conv_same_count_after_success_rejected():
    """After successful extraction, same msg_count is rejected (no new messages)."""
    from app.memory import schedule_extraction

    with patch("app.memory.extract_memory", return_value=True), \
         patch("app.database.SessionLocal") as mock_sl:
        mock_sl.return_value = MagicMock(close=MagicMock())

        schedule_extraction(1, 800, msg_count=6)
        time.sleep(0.3)
        # Same count → must reject
        result = schedule_extraction(1, 800, msg_count=6)
        assert result is False


def test_schedule_same_conv_increased_count_accepted():
    """After successful extraction, increased msg_count allows re-extraction."""
    from app.memory import schedule_extraction

    with patch("app.memory.extract_memory", return_value=True), \
         patch("app.database.SessionLocal") as mock_sl:
        mock_sl.return_value = MagicMock(close=MagicMock())

        schedule_extraction(1, 801, msg_count=6)
        time.sleep(0.3)
        # Increased count → must accept
        result = schedule_extraction(1, 801, msg_count=8)
        assert result is True
        time.sleep(0.3)


def test_schedule_failed_extraction_allows_retry():
    """If extraction returns False, same msg_count can be retried."""
    from app.memory import schedule_extraction

    with patch("app.memory.extract_memory", return_value=False), \
         patch("app.database.SessionLocal") as mock_sl:
        mock_sl.return_value = MagicMock(close=MagicMock())

        schedule_extraction(1, 802, msg_count=6)
        time.sleep(0.3)
        # Failed → last_count not updated → same count retryable
        result = schedule_extraction(1, 802, msg_count=6)
        assert result is True
        time.sleep(0.3)


def test_schedule_exception_allows_retry():
    """If extraction raises, same msg_count can be retried."""
    from app.memory import schedule_extraction

    with patch("app.memory.extract_memory", side_effect=Exception("boom")), \
         patch("app.database.SessionLocal") as mock_sl:
        mock_sl.return_value = MagicMock(close=MagicMock())

        schedule_extraction(1, 803, msg_count=6)
        time.sleep(0.3)
        result = schedule_extraction(1, 803, msg_count=6)
        assert result is True
        time.sleep(0.3)


def test_schedule_submit_failure_releases_lock():
    """If executor.submit() raises, running mark is released."""
    from app.memory import schedule_extraction, _running_convs, _running_lock, _executor

    original_submit = _executor.submit
    with patch.object(_executor, "submit", side_effect=RuntimeError("pool shut down")):
        result = schedule_extraction(1, 804, msg_count=6)

    assert result is False
    with _running_lock:
        assert 804 not in _running_convs


def test_schedule_different_convs_independent():
    """Different conversations have independent last_count tracking."""
    from app.memory import schedule_extraction

    with patch("app.memory.extract_memory", return_value=True), \
         patch("app.database.SessionLocal") as mock_sl:
        mock_sl.return_value = MagicMock(close=MagicMock())

        schedule_extraction(1, 901, msg_count=6)
        schedule_extraction(1, 902, msg_count=6)
        time.sleep(0.3)

        # conv 901 at count 6 → rejected
        assert schedule_extraction(1, 901, msg_count=6) is False
        # conv 902 at count 6 → rejected
        assert schedule_extraction(1, 902, msg_count=6) is False
        # conv 901 at count 8 → accepted
        assert schedule_extraction(1, 901, msg_count=8) is True
        time.sleep(0.3)


def test_executor_max_workers_bounded():
    from app.memory import _executor, _EXECUTOR_MAX_WORKERS
    assert _executor._max_workers == _EXECUTOR_MAX_WORKERS
    assert _EXECUTOR_MAX_WORKERS <= 4


def test_schedule_below_threshold_skips():
    from app.memory import schedule_extraction
    assert schedule_extraction(1, 4000, msg_count=2) is False
