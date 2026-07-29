"""FastAPI 接口关键路径单测：健康检查可达 + 业务接口强制鉴权。"""
import os
import time
import threading
import pytest
from unittest.mock import patch

pytestmark = pytest.mark.integration   # import 全 app + 起 TestClient，CI 跳过

pytest.importorskip("httpx")          # TestClient 依赖 httpx
from fastapi.testclient import TestClient  # noqa: E402


def _client():
    from app.main import app
    return TestClient(app)


def test_health_ok():
    r = _client().get("/health")
    assert r.status_code == 200 and r.json().get("ok") is True
    assert "ready" in r.json()
    assert "services" in r.json()
    assert r.json()["services"]["model_probe"] == "artifact"


def test_deep_health_uses_real_model_probe():
    with patch("app.main._deep_health_cache", None), patch(
        "app.main._deep_model_health",
        return_value=(False, False),
    ) as probe:
        r = _client().get("/health?deep=true")
    probe.assert_called_once_with()
    assert r.status_code == 200
    assert r.json()["status"] == "degraded"
    assert r.json()["services"]["embedding"] is False
    assert r.json()["services"]["reranker"] is False
    assert r.json()["services"]["model_probe"] == "inference"


def test_readiness_returns_503_when_degraded():
    with patch("app.main._health_payload", return_value={
        "ok": True,
        "ready": False,
        "status": "degraded",
        "services": {},
    }):
        r = _client().get("/ready")
    assert r.status_code == 503
    assert r.json()["ready"] is False


def test_readiness_returns_200_only_when_fully_healthy():
    with patch("app.main._health_payload", return_value={
        "ok": True,
        "ready": True,
        "status": "healthy",
        "services": {},
    }):
        r = _client().get("/ready")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"


def test_missing_retrievable_embeddings_fail_readiness_and_request_reindex():
    from unittest.mock import MagicMock

    import app.main as main

    connection = MagicMock()
    connection.execute.return_value.first.return_value = (1,)
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value = connection
    vector_stats = {
        "retrievable": 3,
        "compatible": 2,
        "missing": 1,
        "legacy": 0,
        "mismatched": 0,
    }

    with patch.object(main, "bi_engine", engine), patch.object(
        main,
        "app_engine",
        engine,
    ), patch.object(main, "RAG_BACKEND", "local"), patch.object(
        main,
        "KB_ROUTER_LOADED",
        True,
    ), patch(
        "app.rag.local_store.embedding_compatibility_stats",
        return_value=vector_stats,
    ), patch(
        "app.agent_pipeline._redis_available",
        return_value=True,
    ), patch.object(
        main,
        "_model_artifact_available",
        return_value=True,
    ), patch.object(
        main,
        "_llm_config_ready",
        return_value=True,
    ):
        payload = main._health_payload()

    assert payload["ready"] is False
    assert payload["services"]["embedding_store_compatible"] is False
    assert payload["services"]["reindex_required"] is True


def test_production_readiness_requires_an_official_search_provider():
    from unittest.mock import MagicMock

    import app.main as main

    connection = MagicMock()
    connection.execute.return_value.first.return_value = (1,)
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value = connection
    vector_stats = {
        "retrievable": 2,
        "compatible": 2,
        "missing": 0,
        "legacy": 0,
        "mismatched": 0,
    }
    search_status = {
        "official_api_ready": False,
        "primary_provider": None,
        "mode": "html_fallback_only",
        "providers": {
            "tavily": {"configured": False},
            "brave": {"configured": False},
        },
        "html_fallback_enabled": True,
        "last_attempt": None,
    }

    with patch.object(main, "bi_engine", engine), patch.object(
        main,
        "app_engine",
        engine,
    ), patch.object(main, "IS_PRODUCTION", True), patch.object(
        main,
        "RAG_BACKEND",
        "local",
    ), patch.object(main, "KB_ROUTER_LOADED", True), patch(
        "app.rag.local_store.embedding_compatibility_stats",
        return_value=vector_stats,
    ), patch(
        "app.agent_tools.search_provider_status",
        return_value=search_status,
    ), patch(
        "app.agent_pipeline._redis_available",
        return_value=True,
    ), patch.object(
        main,
        "_model_artifact_available",
        return_value=True,
    ), patch.object(
        main,
        "_llm_config_ready",
        return_value=True,
    ):
        payload = main._health_payload()

    assert payload["ready"] is False
    assert payload["services"]["web_search_official_api"] is False
    assert payload["services"]["web_search"]["mode"] == "html_fallback_only"


def test_model_artifact_check_rejects_truncated_safetensors(tmp_path):
    from app.main import _model_artifact_available

    model_dir = tmp_path / "broken-bge"
    model_dir.mkdir()
    (model_dir / "model.safetensors").write_bytes(b"truncated")

    assert _model_artifact_available(str(model_dir)) is False


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("", False),
        ("sk-REPLACE_WITH_YOUR_PROVIDER_KEY", False),
        ("changeMe", False),
        ("real-provider-token", True),
    ],
)
def test_llm_config_readiness_rejects_placeholders(value, expected):
    from app.main import _llm_config_ready

    assert _llm_config_ready(value) is expected


@pytest.mark.parametrize(
    ("value", "min_length", "expected"),
    [
        ("REPLACE_WITH_64_HEX_RANDOM", 32, False),
        ("REPLACE_WITH_STRONG_ADMIN_PASSWORD", 12, False),
        ("short", 12, False),
        ("3b6066803cf74666a783ec72405cc0f1", 32, True),
        ("long-and-private-admin-password", 12, True),
    ],
)
def test_production_secret_readiness_rejects_public_templates(
    value,
    min_length,
    expected,
):
    from app.main import _configured_secret_ready

    assert _configured_secret_ready(value, min_length) is expected


def test_bootstrap_admin_refuses_to_promote_existing_regular_user(monkeypatch):
    from app.auth import bootstrap_admin
    from app.database import SessionLocal
    from app.models import User
    from app.security import hash_password

    username = f"collision_{int(time.time() * 1000)}"
    monkeypatch.setenv("ADMIN_USERNAME", username)
    monkeypatch.setenv("ADMIN_PASSWORD", "long-private-admin-password")
    with SessionLocal() as db:
        user = User(
            username=username,
            password_hash=hash_password("regular-password"),
            role="user",
        )
        db.add(user)
        db.commit()
        with pytest.raises(RuntimeError, match="拒绝静默提权"):
            bootstrap_admin(db)
        db.refresh(user)
        assert user.role == "user"
        db.delete(user)
        db.commit()


def test_ask_requires_auth():
    r = _client().post("/api/ask_sync", json={"question": "随便问"})
    assert r.status_code in (401, 403)   # 无 token → 拒绝


def test_history_requires_auth():
    r = _client().get("/api/history")
    assert r.status_code in (401, 403)


def test_public_registration_can_be_disabled():
    with patch("app.auth.ALLOW_PUBLIC_REGISTRATION", False):
        r = _client().post("/api/auth/register", json={
            "username": f"closed_{int(time.time() * 1000)}",
            "password": "pw123456",
        })
    assert r.status_code == 403
    assert "关闭公开注册" in r.json()["detail"]


def test_daily_question_limit_blocks_before_agent_call():
    from app.database import SessionLocal
    from app.models import Conversation, Message, User
    from sqlalchemy import select

    client = _client()
    uname = f"quota_{int(time.time() * 1000)}"
    client.post("/api/auth/register", json={"username": uname, "password": "pw123456"})
    token = client.post(
        "/api/auth/login",
        json={"username": uname, "password": "pw123456"},
    ).json()["access_token"]
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == uname))
        conv = Conversation(user_id=user.id, title="quota")
        db.add(conv)
        db.flush()
        db.add(Message(
            conversation_id=conv.id,
            user_id=user.id,
            role="user",
            content="already used",
        ))
        db.commit()
    with patch("app.main.DAILY_QUESTION_LIMIT", 1), patch("app.main.run_agent") as agent:
        r = client.post(
            "/api/ask_sync",
            headers={"Authorization": f"Bearer {token}"},
            json={"question": "should be blocked"},
        )
    assert r.status_code == 429
    agent.assert_not_called()


def test_sse_rejects_when_bounded_agent_pool_is_full():
    client = _client()
    uname = f"quota_pool_{int(time.time() * 1000)}"
    client.post("/api/auth/register", json={
        "username": uname,
        "password": "pw123456",
    })
    token = client.post("/api/auth/login", json={
        "username": uname,
        "password": "pw123456",
    }).json()["access_token"]

    class FullPool:
        def acquire(self, blocking=False):
            return False

    with patch("app.main._ASK_SLOTS", FullPool()), patch(
        "app.main._ASK_EXECUTOR"
    ) as executor:
        response = client.post(
            "/api/ask",
            headers={"Authorization": f"Bearer {token}"},
            json={"question": "should fail before reservation"},
        )

    assert response.status_code == 503
    assert "分析任务已满" in response.json()["detail"]
    executor.submit.assert_not_called()


def test_kb_ask_shares_quota_and_persists_history():
    from app.database import SessionLocal
    from app.models import Message, User
    from sqlalchemy import select

    client = _client()
    username = f"kb_history_{int(time.time() * 1000)}"
    client.post("/api/auth/register", json={
        "username": username,
        "password": "pw123456",
    })
    token = client.post("/api/auth/login", json={
        "username": username,
        "password": "pw123456",
    }).json()["access_token"]
    with patch(
        "app.rag.retrieve.answer_question",
        return_value={
            "answer": "有引用的答案",
            "citations": [{"doc_id": 1, "page_no": 1, "chunk_id": 2}],
            "has_answer": True,
        },
    ):
        response = client.post(
            "/api/kb/ask",
            headers={"Authorization": f"Bearer {token}"},
            json={"question": "知识库问题"},
        )
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == username))
        messages = db.scalars(
            select(Message).where(Message.user_id == user.id).order_by(Message.id),
        ).all()
    assert [message.role for message in messages[-2:]] == ["user", "assistant"]
    assert messages[-1].content == "有引用的答案"


def test_kb_ask_rejects_when_shared_capacity_is_full():
    client = _client()
    username = f"kb_pool_{int(time.time() * 1000)}"
    client.post("/api/auth/register", json={
        "username": username,
        "password": "pw123456",
    })
    token = client.post("/api/auth/login", json={
        "username": username,
        "password": "pw123456",
    }).json()["access_token"]

    class FullPool:
        def acquire(self, blocking=False):
            return False

    with patch("app.kb._ASK_SLOTS", FullPool()), patch(
        "app.rag.retrieve.answer_question",
    ) as answer:
        response = client.post(
            "/api/kb/ask",
            headers={"Authorization": f"Bearer {token}"},
            json={"question": "知识库问题"},
        )

    assert response.status_code == 503
    assert "分析任务已满" in response.json()["detail"]
    answer.assert_not_called()


def test_sync_ask_rejects_when_shared_capacity_is_full():
    client = _client()
    username = f"sync_pool_{int(time.time() * 1000)}"
    client.post("/api/auth/register", json={
        "username": username,
        "password": "pw123456",
    })
    token = client.post("/api/auth/login", json={
        "username": username,
        "password": "pw123456",
    }).json()["access_token"]

    class FullPool:
        def acquire(self, blocking=False):
            return False

    with patch("app.main._ASK_SLOTS", FullPool()), patch("app.main.run_agent") as agent:
        response = client.post(
            "/api/ask_sync",
            headers={"Authorization": f"Bearer {token}"},
            json={"question": "同步问题"},
        )

    assert response.status_code == 503
    assert "分析任务已满" in response.json()["detail"]
    agent.assert_not_called()


def test_kb_upload_rejects_oversized_body_while_streaming():
    client = _client()
    username = f"kb_upload_{int(time.time() * 1000)}"
    client.post("/api/auth/register", json={
        "username": username,
        "password": "pw123456",
    })
    token = client.post("/api/auth/login", json={
        "username": username,
        "password": "pw123456",
    }).json()["access_token"]
    with patch("app.kb.MAX_UPLOAD_MB", 1):
        response = client.post(
            "/api/kb/upload",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("large.md", b"x" * (1024 * 1024 + 1), "text/markdown")},
        )
    assert response.status_code == 413


def test_task_stream_isolated_between_users():
    from app.agent_pipeline import _set_progress
    from app.database import SessionLocal
    from app.models import User
    from sqlalchemy import select

    client = _client()
    owner_name = f"task_owner_{int(time.time() * 1000)}"
    other_name = f"task_other_{int(time.time() * 1000)}"
    for name in (owner_name, other_name):
        client.post("/api/auth/register", json={
            "username": name,
            "password": "pw123456",
        })
    with SessionLocal() as db:
        owner = db.scalar(select(User).where(User.username == owner_name))
        owner_id = owner.id
    other_token = client.post("/api/auth/login", json={
        "username": other_name,
        "password": "pw123456",
    }).json()["access_token"]

    task_id = f"private_task_{int(time.time() * 1000)}"
    _set_progress(task_id, {
        "stage": "queued",
        "status": "pending",
        "user_id": owner_id,
    })
    response = client.get(
        f"/api/tasks/{task_id}/stream",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------- 禁用账号鉴权
def test_disabled_user_cannot_access_protected_endpoints():
    """持有有效 JWT 的被禁用用户，访问任意受保护接口，得到 403（不是 200 也不是 401）。

    行为说明：
    - login 端点已拦截禁用用户（不让新登录）
    - 但账号被禁用「之前」签发的 token 仍然有效
    - get_current_user 必须在 token 验证后检查 disabled 状态
    """
    from app.main import app
    from app.database import SessionLocal
    from sqlalchemy import select
    from app.models import User

    client = TestClient(app)

    # Step 1：注册并登录，拿到有效 token（先确保用户处于启用状态，测试幂等）
    uname = "test_disabled_user_tdd"
    client.post("/api/auth/register", json={"username": uname, "password": "pw123456"})
    with SessionLocal() as db:
        existing = db.scalar(select(User).where(User.username == uname))
        if existing:
            existing.disabled = False
            db.commit()
    login_r = client.post("/api/auth/login", json={"username": uname, "password": "pw123456"})
    assert login_r.status_code == 200, f"登录失败: {login_r.text}"
    token = login_r.json()["access_token"]
    auth = {"Authorization": f"Bearer {token}"}

    # Step 2：确认此 token 正常可用（先建立 baseline）
    r = client.get("/api/history", headers=auth)
    assert r.status_code == 200, "baseline 应该 200"

    # Step 3：在数据库里禁用该用户（模拟管理员操作）
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == uname))
        user.disabled = True
        db.commit()

    # Step 4：持同一个有效 token 再次请求 → 期望 403
    r = client.get("/api/history", headers=auth)
    assert r.status_code == 403, (
        f"禁用用户应返回 403，实际返回 {r.status_code}。"
        f"get_current_user 缺少 disabled 检查。"
    )


# ---------------------------------------------------------------- 速率限制
def _mock_stream(*args, **kwargs):
    """替代 stream_agent，立即返回一个 mock 快照，不调用 LLM。"""
    yield {"final_answer": "ok", "intent": "chat", "trace": [], "has_answer": True}


def test_rate_limit_blocks_rapid_requests():
    """同一用户 0.5s 内连发两次 /api/ask，第二次应在建流前被 429 拒绝。

    行为说明：
    - 速率限制必须按 user.id 追踪，不能存在闭包对象上（每次请求都是新闭包）
    - 限制必须在创建 SSE 响应前触发，客户端才能收到标准 HTTP 429
    """
    from app.main import app
    client = TestClient(app)

    # 注册登录（每次测试用不同账号，避免跨测试的速率状态干扰）
    uname = f"test_ratelimit_{int(time.time())}"
    client.post("/api/auth/register", json={"username": uname, "password": "pw123456"})
    token = client.post("/api/auth/login",
                        json={"username": uname, "password": "pw123456"}).json()["access_token"]
    auth = {"Authorization": f"Bearer {token}"}

    with patch("app.main.stream_agent", _mock_stream):
        # 第一次请求：应正常通过
        r1 = client.post("/api/ask", headers=auth, json={"question": "test"})
        assert r1.status_code == 200
        assert "RATE_LIMITED" not in r1.text, "第一次请求不应触发速率限制"

        # 立刻发第二次（< 0.5s）：应被速率限制
        r2 = client.post("/api/ask", headers=auth, json={"question": "test"})
        assert r2.status_code == 429
        assert "请稍后再试" in r2.text, (
            f"0.5s 内第二次请求应返回 HTTP 429，实际 body：{r2.text[:200]}"
        )


# ---------------------------------------------------------------- Payload 大小限制
PAYLOAD_MAX = 65536   # 64KB，与实现对齐

def test_insight_rejects_oversized_payload():
    """POST /api/insights 传超大 payload → 422，不入库不进内存。

    行为说明：
    - 正常图表快照 < 3KB；64KB 以内均合法
    - 攻击者传 10MB payload 时必须在 Pydantic 校验层被拒，
      返回 422 Unprocessable Entity，不落到业务逻辑
    """
    from app.main import app
    client = TestClient(app)

    uname = f"test_payload_{int(time.time())}"
    client.post("/api/auth/register", json={"username": uname, "password": "pw123456"})
    token = client.post("/api/auth/login",
                        json={"username": uname, "password": "pw123456"}).json()["access_token"]
    auth = {"Authorization": f"Bearer {token}"}

    # 合法大小：应通过（64KB 以内）
    ok_payload = "x" * PAYLOAD_MAX
    r = client.post("/api/insights", headers=auth,
                    json={"title": "t", "payload": ok_payload})
    assert r.status_code == 200, f"合法 payload 应通过，实际 {r.status_code}"

    # 超限：64KB + 1 字符，应被拒
    over_payload = "x" * (PAYLOAD_MAX + 1)
    r = client.post("/api/insights", headers=auth,
                    json={"title": "t", "payload": over_payload})
    assert r.status_code == 422, (
        f"超大 payload 应返回 422，实际 {r.status_code}。"
        f"InsightIn.payload 缺少 max_length 约束。"
    )


def test_share_rejects_oversized_payload():
    """POST /api/share 传超大 payload → 422。与 insights 同一问题，分别覆盖。"""
    from app.main import app
    client = TestClient(app)

    uname = f"test_share_payload_{int(time.time())}"
    client.post("/api/auth/register", json={"username": uname, "password": "pw123456"})
    token = client.post("/api/auth/login",
                        json={"username": uname, "password": "pw123456"}).json()["access_token"]
    auth = {"Authorization": f"Bearer {token}"}

    over_payload = "x" * (PAYLOAD_MAX + 1)
    r = client.post("/api/share", headers=auth,
                    json={"title": "t", "payload": over_payload})
    assert r.status_code == 422, (
        f"超大 payload 应返回 422，实际 {r.status_code}。"
        f"ShareIn.payload 缺少 max_length 约束。"
    )


# ---------------------------------------------------------------- Worker 断连取消
def test_worker_stops_when_stop_event_is_set():
    """_stop Event 设置后，worker 线程在下一个快照前停止，不继续消耗 LLM token。

    测试 seam：直接测 worker 函数的停止机制（不经过 HTTP 层）。
    HTTP 层的集成（gen() finally → _stop.set()）通过代码审查验证，
    因为 TestClient 是同步阻塞的，无法模拟真实的 mid-stream 断连。

    行为：
    - worker 每次快照后检查 _stop.is_set()
    - _stop 被设置后，worker 在 ≤ 1 个额外快照后退出
    - gen() 的 try/finally 保证断连时 _stop 一定被设置
    """
    import asyncio
    import queue as Q
    from app.main import _run_agent_worker   # 将被抽出的 helper

    snaps_processed = []
    stop = threading.Event()
    sync_q = Q.Queue()

    def slow_stream(*args, **kwargs):
        for i in range(50):
            snaps_processed.append(i)
            time.sleep(0.05)
            yield {"final_answer": f"snap_{i}", "intent": "chat",
                   "trace": [], "has_answer": True}

    # 用 dummy loop + 同步 queue 替代 asyncio，直接测 worker 逻辑
    with patch("app.main.stream_agent", slow_stream):
        t = threading.Thread(
            target=_run_agent_worker,
            args=("test", 1, [], sync_q.put, stop),
        )
        t.start()

        # 消费 3 个快照后设置 stop（模拟 gen() 被客户端断连关闭）
        consumed = 0
        while consumed < 3:
            item = sync_q.get(timeout=2)
            if item[0] == "end":
                break
            consumed += 1

        stop.set()   # ← 这就是 gen() finally 块要做的事
        t.join(timeout=2)

    # worker 应在 stop 信号后 ≤ 1 个快照内退出
    assert len(snaps_processed) <= 4, (
        f"stop.set() 后 worker 应立即停止，"
        f"实际处理了 {len(snaps_processed)}/50 个快照。"
        f"worker 缺少 _stop.is_set() 检查。"
    )
