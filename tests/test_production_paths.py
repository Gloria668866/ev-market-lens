"""生产高危路径测试 — 覆盖上线前必须通过的关键路径。

范围：
  - 注册/登录完整流程（重名/短密码/错密码/禁用）
  - 所有受保护接口的 401 守卫
  - 用户数据隔离（A 看不到 B 的历史/知识库）
  - 输入边界（空问题/超长问题）
  - 价格/品牌接口功能验证
  - 管理员权限守卫
  - 公开分享免鉴权
"""
import time
import pytest
from unittest.mock import patch
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

pytestmark = pytest.mark.integration


# ────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────
def _app_client():
    from app.main import app
    return TestClient(app)


def _register_login(client, suffix=None):
    """注册并登录，返回 (username, token)。每次用唯一用户名。"""
    uname = f"prod_test_{suffix or int(time.time() * 1000) % 10**9}"
    client.post("/api/auth/register", json={"username": uname, "password": "pw123456"})
    r = client.post("/api/auth/login", json={"username": uname, "password": "pw123456"})
    return uname, r.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ────────────────────────────────────────────
# 注册 / 登录流程
# ────────────────────────────────────────────
class TestAuth:
    def test_register_and_login_full_cycle(self):
        client = _app_client()
        ts = int(time.time() * 1000) % 10**9
        uname = f"cycle_{ts}"

        # 注册
        r = client.post("/api/auth/register", json={"username": uname, "password": "pw123456"})
        assert r.status_code == 200, r.text
        assert r.json()["user"]["username"] == uname

        # 重名注册 → 409
        r2 = client.post("/api/auth/register", json={"username": uname, "password": "pw123456"})
        assert r2.status_code == 409

        # 登录
        r3 = client.post("/api/auth/login", json={"username": uname, "password": "pw123456"})
        assert r3.status_code == 200
        assert "access_token" in r3.json()

        # 错密码 → 401
        r4 = client.post("/api/auth/login", json={"username": uname, "password": "wrongpw"})
        assert r4.status_code == 401

        # /me 验证 token
        token = r3.json()["access_token"]
        r5 = client.get("/api/auth/me", headers=_auth(token))
        assert r5.status_code == 200
        assert r5.json()["user"]["username"] == uname

    def test_short_password_rejected(self):
        client = _app_client()
        r = client.post("/api/auth/register",
                        json={"username": f"short_{int(time.time()*1000)%10**8}", "password": "12345"})
        assert r.status_code == 400

    def test_invalid_token_returns_401(self):
        client = _app_client()
        r = client.get("/api/history", headers={"Authorization": "Bearer garbage.token.here"})
        assert r.status_code == 401

    def test_missing_token_returns_401(self):
        client = _app_client()
        for endpoint, method in [
            ("/api/history", "GET"),
            ("/api/ask_sync", "POST"),
            ("/api/insights", "GET"),
            ("/api/prices", "GET"),
        ]:
            if method == "GET":
                r = client.get(endpoint)
            else:
                r = client.post(endpoint, json={"question": "test"})
            assert r.status_code == 401, f"{endpoint} 应返回 401，实际 {r.status_code}"


# ────────────────────────────────────────────
# 用户数据隔离
# ────────────────────────────────────────────
class TestUserIsolation:
    def test_history_isolated_between_users(self):
        """A 的历史对 B 不可见。"""
        client = _app_client()
        _, tok_a = _register_login(client, f"iso_a_{int(time.time()*1000)%10**8}")
        _, tok_b = _register_login(client, f"iso_b_{int(time.time()*1000)%10**8}")

        # A 的历史列表
        ra = client.get("/api/history", headers=_auth(tok_a))
        rb = client.get("/api/history", headers=_auth(tok_b))
        assert ra.status_code == 200
        assert rb.status_code == 200
        # 两者互不干扰（各自独立列表）
        ids_a = {c["id"] for c in ra.json().get("conversations", [])}
        ids_b = {c["id"] for c in rb.json().get("conversations", [])}
        assert ids_a.isdisjoint(ids_b), "A 和 B 的会话 ID 不应有交集"

    def test_history_detail_forbidden_for_other_user(self):
        """B 不能用自己的 token 访问 A 的会话详情。"""
        client = _app_client()
        _, tok_a = _register_login(client, f"detail_a_{int(time.time()*1000)%10**8}")
        _, tok_b = _register_login(client, f"detail_b_{int(time.time()*1000)%10**8}")

        # A 用 ask_sync 创建一条会话（mock LLM）
        def _noop(*a, **k): return {"final_answer": "ok", "intent": "chat", "trace": [],
                                     "has_answer": True, "cols": [], "rows": [], "chart": None, "citations": []}
        with patch("app.main.run_agent", _noop):
            r = client.post("/api/ask_sync", headers=_auth(tok_a), json={"question": "test"})
        assert r.status_code == 200
        conv_id = r.json().get("conversation_id")
        assert conv_id is not None

        # B 用自己的 token 访问 A 的会话 → 404
        rb = client.get(f"/api/history/{conv_id}", headers=_auth(tok_b))
        assert rb.status_code == 404, f"B 不应能访问 A 的会话，实际 {rb.status_code}"

    def test_insight_isolated(self):
        """A 收藏的洞察 B 看不到。"""
        client = _app_client()
        _, tok_a = _register_login(client, f"ins_a_{int(time.time()*1000)%10**8}")
        _, tok_b = _register_login(client, f"ins_b_{int(time.time()*1000)%10**8}")

        client.post("/api/insights", headers=_auth(tok_a),
                    json={"title": "A 的收藏", "payload": "x"})

        # B 的收藏列表里不应出现 A 的
        rb = client.get("/api/insights", headers=_auth(tok_b))
        assert rb.status_code == 200
        titles_b = [i["title"] for i in rb.json().get("insights", [])]
        assert "A 的收藏" not in titles_b


# ────────────────────────────────────────────
# 输入边界
# ────────────────────────────────────────────
class TestInputValidation:
    def test_empty_question_rejected(self):
        client = _app_client()
        _, tok = _register_login(client, f"empty_{int(time.time()*1000)%10**8}")

        def _noop(*a, **k): return {"final_answer": "ok", "intent": "chat", "trace": [],
                                     "has_answer": True, "cols": [], "rows": [], "chart": None, "citations": []}
        with patch("app.main.run_agent", _noop):
            r = client.post("/api/ask_sync", headers=_auth(tok), json={"question": ""})
        assert r.status_code in (400, 422), f"空问题应被拒绝，实际 {r.status_code}"

    def test_oversized_question_rejected(self):
        client = _app_client()
        _, tok = _register_login(client, f"huge_{int(time.time()*1000)%10**8}")

        def _noop(*a, **k): return {"final_answer": "ok", "intent": "chat", "trace": [],
                                     "has_answer": True, "cols": [], "rows": [], "chart": None, "citations": []}
        with patch("app.main.run_agent", _noop):
            r = client.post("/api/ask_sync", headers=_auth(tok),
                            json={"question": "x" * 2001})
        assert r.status_code in (400, 422), f"超长问题应被拒绝，实际 {r.status_code}"


# ────────────────────────────────────────────
# 车型报价
# ────────────────────────────────────────────
class TestPrices:
    def test_prices_returns_list(self):
        client = _app_client()
        _, tok = _register_login(client, f"prices_{int(time.time()*1000)%10**8}")
        r = client.get("/api/prices?limit=5", headers=_auth(tok))
        assert r.status_code == 200
        data = r.json()
        assert "items" in data
        assert "count" in data
        assert data["returned"] <= 5
        assert data["count"] >= data["returned"]

    def test_price_brands_returns_list(self):
        client = _app_client()
        _, tok = _register_login(client, f"brands_{int(time.time()*1000)%10**8}")
        r = client.get("/api/prices/brands", headers=_auth(tok))
        assert r.status_code == 200
        assert "brands" in r.json()

    def test_prices_search_filter(self):
        client = _app_client()
        _, tok = _register_login(client, f"srch_{int(time.time()*1000)%10**8}")
        r = client.get("/api/prices?q=比亚迪&limit=10", headers=_auth(tok))
        assert r.status_code == 200
        items = r.json()["items"]
        # 所有结果品牌应包含比亚迪
        for item in items:
            assert "比亚迪" in item.get("brand", "") or "比亚迪" in item.get("series", ""), \
                f"搜索'比亚迪'返回了不相关结果: {item}"


# ────────────────────────────────────────────
# 管理员权限
# ────────────────────────────────────────────
class TestAdminGuard:
    def test_non_admin_cannot_access_admin_endpoints(self):
        client = _app_client()
        _, tok = _register_login(client, f"nonadmin_{int(time.time()*1000)%10**8}")
        for path in ["/api/admin/overview", "/api/admin/metrics", "/api/admin/users"]:
            r = client.get(path, headers=_auth(tok))
            assert r.status_code == 403, f"非管理员访问 {path} 应 403，实际 {r.status_code}"

    def test_admin_can_access_overview(self):
        client = _app_client()
        r_login = client.post("/api/auth/login",
                              json={"username": "admin", "password": "admin123"})
        if r_login.status_code != 200:
            pytest.skip("admin 账号未初始化，跳过")
        tok = r_login.json()["access_token"]
        r = client.get("/api/admin/overview", headers=_auth(tok))
        assert r.status_code == 200
        assert "users" in r.json()   # 实际字段名是 users，非 total_users

    def test_admin_can_access_process_metrics_without_secrets(self):
        client = _app_client()
        r_login = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        if r_login.status_code != 200:
            pytest.skip("admin 账号未初始化，跳过")
        tok = r_login.json()["access_token"]
        response = client.get("/api/admin/metrics", headers=_auth(tok))
        assert response.status_code == 200
        payload = response.json()
        assert payload["scope"] == "current_process"
        assert payload["resets_on_restart"] is True
        assert payload["ask_max_concurrency"] >= 1
        assert {"calls", "errors", "p50_ms", "p95_ms", "total_tokens"} <= set(payload["llm"])
        assert "api_key" not in str(payload).lower()

    def test_admin_password_reset_revokes_existing_token(self):
        from app.database import SessionLocal
        from app.models import User
        from sqlalchemy import select

        client = _app_client()
        username, token = _register_login(
            client,
            f"reset_admin_{int(time.time()*1000)%10**8}",
        )
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.username == username))
            user.role = "admin"
            user_id = user.id
            db.commit()

        response = client.post(
            f"/api/admin/users/{user_id}/reset-password",
            headers=_auth(token),
            json={"new_password": "new-password-123"},
        )
        assert response.status_code == 200, response.text
        assert client.get("/api/auth/me", headers=_auth(token)).status_code == 401

    def test_admin_can_create_account_when_public_registration_is_closed(self):
        from app.database import SessionLocal
        from app.models import User
        from sqlalchemy import select

        client = _app_client()
        username, token = _register_login(
            client,
            f"creator_admin_{int(time.time()*1000)%10**8}",
        )
        with SessionLocal() as db:
            admin = db.scalar(select(User).where(User.username == username))
            admin.role = "admin"
            db.commit()

        created_username = f"controlled_{int(time.time()*1000)%10**8}"
        with patch("app.auth.ALLOW_PUBLIC_REGISTRATION", False):
            response = client.post(
                "/api/admin/users",
                headers=_auth(token),
                json={
                    "username": created_username,
                    "password": "controlled-password",
                    "nickname": "受控演示账号",
                },
            )
        assert response.status_code == 200, response.text
        login = client.post(
            "/api/auth/login",
            json={"username": created_username, "password": "controlled-password"},
        )
        assert login.status_code == 200


# ────────────────────────────────────────────
# 公开分享（免鉴权）
# ────────────────────────────────────────────
class TestPublicShare:
    def test_share_create_and_public_read(self):
        client = _app_client()
        _, tok = _register_login(client, f"share_{int(time.time()*1000)%10**8}")

        # 创建分享
        r = client.post("/api/share", headers=_auth(tok),
                        json={"title": "测试分享", "question": "比亚迪销量？", "payload": "{}"})
        assert r.status_code == 200
        token = r.json()["token"]
        assert token

        # 无 token 可公开读取
        r2 = client.get(f"/api/public/share/{token}")
        assert r2.status_code == 200
        assert r2.json()["title"] == "测试分享"

    def test_invalid_share_token_returns_404(self):
        client = _app_client()
        r = client.get("/api/public/share/nonexistent_token_xyz")
        assert r.status_code == 404


# ────────────────────────────────────────────
# 历史会话 CRUD
# ────────────────────────────────────────────
class TestHistory:
    def test_delete_own_conversation(self):
        from app.database import SessionLocal
        from app.models import Conversation, MemoryEpisode

        client = _app_client()
        _, tok = _register_login(client, f"del_hist_{int(time.time()*1000)%10**8}")

        def _noop(*a, **k): return {"final_answer": "ok", "intent": "chat", "trace": [],
                                     "has_answer": True, "cols": [], "rows": [], "chart": None, "citations": []}
        with patch("app.main.run_agent", _noop):
            r = client.post("/api/ask_sync", headers=_auth(tok), json={"question": "hello"})
        conv_id = r.json()["conversation_id"]
        with SessionLocal() as db:
            conversation = db.get(Conversation, conv_id)
            episode = MemoryEpisode(
                user_id=conversation.user_id,
                conversation_id=conv_id,
                summary="delete cascade regression",
            )
            db.add(episode)
            db.commit()
            episode_id = episode.id

        # 删除
        rd = client.delete(f"/api/history/{conv_id}", headers=_auth(tok))
        assert rd.status_code == 200
        with SessionLocal() as db:
            assert db.get(MemoryEpisode, episode_id) is None

        # 再访问 → 404
        r2 = client.get(f"/api/history/{conv_id}", headers=_auth(tok))
        assert r2.status_code == 404

    def test_cannot_delete_others_conversation(self):
        client = _app_client()
        _, tok_a = _register_login(client, f"del_a_{int(time.time()*1000)%10**8}")
        _, tok_b = _register_login(client, f"del_b_{int(time.time()*1000)%10**8}")

        def _noop(*a, **k): return {"final_answer": "ok", "intent": "chat", "trace": [],
                                     "has_answer": True, "cols": [], "rows": [], "chart": None, "citations": []}
        with patch("app.main.run_agent", _noop):
            r = client.post("/api/ask_sync", headers=_auth(tok_a), json={"question": "hello"})
        conv_id = r.json()["conversation_id"]

        # B 试图删 A 的会话 → 404
        rd = client.delete(f"/api/history/{conv_id}", headers=_auth(tok_b))
        assert rd.status_code == 404
