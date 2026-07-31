"""Tests for agent pipeline: tools, DAG execution, pipeline runner."""
import json
import time

import pytest
from unittest.mock import patch, MagicMock


# ── Tool registry ─────────────────────────────────────────────────────────────

def test_get_tool_definitions_returns_schemas():
    from app.agent_tools import get_tool_definitions
    schemas = get_tool_definitions("code_agent")
    assert isinstance(schemas, list)
    assert len(schemas) >= 3  # http_get, search_web, parse_html
    # Each must have "type": "function"
    for s in schemas:
        assert s["type"] == "function"
        assert "function" in s
        assert "name" in s["function"]


def test_get_tool_definitions_research_agent_empty():
    from app.agent_tools import get_tool_definitions
    schemas = get_tool_definitions("research_agent")
    assert schemas == []


def test_execute_tool_http_get_success():
    from app.agent_tools import execute_tool
    with patch("app.agent_tools.httpx.get") as mock_get, patch(
        "app.agent_tools._resolve_host_addresses",
        return_value={__import__("ipaddress").ip_address("93.184.216.34")},
    ):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body>Test page content</body></html>"
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.extensions = {}
        mock_get.return_value = mock_resp

        result = execute_tool("http_get", {"url": "https://example.com"})
        assert result["status"] == "success"
        assert result["status_code"] == 200
        assert "Test page content" in result["content"]


def test_execute_tool_http_get_http_error():
    from app.agent_tools import execute_tool
    with patch("app.agent_tools.httpx.get") as mock_get, patch(
        "app.agent_tools._resolve_host_addresses",
        return_value={__import__("ipaddress").ip_address("93.184.216.34")},
    ):
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.text = "Forbidden"
        mock_resp.headers = {}
        mock_resp.extensions = {}
        mock_get.return_value = mock_resp

        result = execute_tool("http_get", {"url": "https://blocked.example.com"})
        assert result["status"] == "failed"
        assert result["status_code"] == 403


def test_execute_tool_http_get_timeout():
    from app.agent_tools import execute_tool
    import httpx
    with patch(
        "app.agent_tools.httpx.get",
        side_effect=httpx.TimeoutException("timeout"),
    ), patch(
        "app.agent_tools._resolve_host_addresses",
        return_value={__import__("ipaddress").ip_address("93.184.216.34")},
    ):
        result = execute_tool("http_get", {"url": "https://slow.example.com"})
        assert result["status"] == "failed"
        assert "timeout" in result.get("error", "").lower()


def test_search_web_prefers_tavily_and_returns_normalized_schema(monkeypatch):
    import app.agent_tools as tools

    monkeypatch.setattr(tools, "TAVILY_API_KEY", "tvly-private-test-key")
    monkeypatch.setattr(tools, "BRAVE_SEARCH_API_KEY", "")
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "results": [{
            "title": "2026 年新能源汽车政策",
            "url": "https://example.com/policy",
            "content": "政策正文摘要",
            "score": 0.91,
        }],
    }

    with patch("app.agent_tools.httpx.post", return_value=response) as post, patch(
        "app.agent_tools._baidu_search",
    ) as baidu, patch("app.agent_tools._bing_html_search") as bing:
        result = tools._tool_search_web("新能源汽车政策", 3)

    assert result["status"] == "success"
    assert result["source"] == "tavily_api"
    assert result["results"] == [{
        "title": "2026 年新能源汽车政策",
        "url": "https://example.com/policy",
        "snippet": "政策正文摘要",
    }]
    assert result["provider_attempts"] == [{
        "provider": "tavily",
        "status": "success",
    }]
    request = post.call_args
    assert request.args[0] == "https://api.tavily.com/search"
    assert request.kwargs["headers"]["Authorization"] == "Bearer tvly-private-test-key"
    assert request.kwargs["json"] == {
        "query": "新能源汽车政策",
        "max_results": 3,
        "search_depth": "basic",
    }
    assert "tvly-private-test-key" not in json.dumps(result, ensure_ascii=False)
    baidu.assert_not_called()
    bing.assert_not_called()


def test_search_web_degrades_from_tavily_error_to_brave(monkeypatch):
    import httpx
    import app.agent_tools as tools

    monkeypatch.setattr(tools, "TAVILY_API_KEY", "tvly-private-test-key")
    monkeypatch.setattr(tools, "BRAVE_SEARCH_API_KEY", "brave-private-test-key")
    brave_response = MagicMock()
    brave_response.status_code = 200
    brave_response.json.return_value = {
        "web": {
            "results": [{
                "title": "Brave result",
                "url": "https://example.org/report",
                "description": "Brave snippet",
            }],
        },
    }

    with patch(
        "app.agent_tools.httpx.post",
        side_effect=httpx.TimeoutException("provider timeout"),
    ), patch("app.agent_tools.httpx.get", return_value=brave_response) as get, patch(
        "app.agent_tools._baidu_search",
    ) as baidu:
        result = tools._tool_search_web("市场报告", 5)

    assert result["status"] == "success"
    assert result["source"] == "brave_api"
    assert result["results"][0]["snippet"] == "Brave snippet"
    assert result["provider_attempts"] == [
        {
            "provider": "tavily",
            "status": "failed",
            "error_code": "timeout",
        },
        {"provider": "brave", "status": "success"},
    ]
    request = get.call_args
    assert request.args[0] == (
        "https://api.search.brave.com/res/v1/web/search"
    )
    assert request.kwargs["headers"]["X-Subscription-Token"] == (
        "brave-private-test-key"
    )
    assert request.kwargs["params"] == {"q": "市场报告", "count": 5}
    assert "tvly-private-test-key" not in json.dumps(result)
    assert "brave-private-test-key" not in json.dumps(result)
    baidu.assert_not_called()


def test_search_web_without_official_keys_uses_html_fallback(monkeypatch):
    import app.agent_tools as tools

    monkeypatch.setattr(tools, "TAVILY_API_KEY", "")
    monkeypatch.setattr(tools, "BRAVE_SEARCH_API_KEY", "")
    fallback = [{
        "title": "百度结果",
        "url": "https://example.cn/result",
        "snippet": "HTML fallback snippet",
    }]

    with patch("app.agent_tools.httpx.post") as post, patch(
        "app.agent_tools._baidu_search",
        return_value=fallback,
    ) as baidu, patch("app.agent_tools._bing_html_search") as bing:
        result = tools._tool_search_web("销量", 5)

    assert result["status"] == "success"
    assert result["source"] == "baidu_html"
    assert result["provider_attempts"] == [
        {"provider": "tavily", "status": "not_configured"},
        {"provider": "brave", "status": "not_configured"},
        {"provider": "baidu_html", "status": "success"},
    ]
    post.assert_not_called()
    baidu.assert_called_once_with("销量", 5)
    bing.assert_not_called()


def test_search_provider_status_never_exposes_keys(monkeypatch):
    import app.agent_tools as tools

    monkeypatch.setattr(tools, "TAVILY_API_KEY", "tvly-private-test-key")
    monkeypatch.setattr(tools, "BRAVE_SEARCH_API_KEY", "")

    status = tools.search_provider_status()

    assert status["official_api_ready"] is True
    assert status["primary_provider"] == "tavily"
    assert status["providers"] == {
        "tavily": {"configured": True},
        "brave": {"configured": False},
    }
    serialized = json.dumps(status)
    assert "tvly-private-test-key" not in serialized


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://10.0.0.1/",
        "http://172.31.0.2/",
        "http://192.168.1.10/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
    ],
)
def test_http_tool_blocks_all_non_public_ip_ranges(url):
    from app.agent_tools import _tool_http_get

    with patch("app.agent_tools.httpx.get") as mock_get:
        result = _tool_http_get(url)
    assert result["status"] == "failed"
    mock_get.assert_not_called()


def test_http_tool_revalidates_redirect_target():
    from app.agent_tools import _tool_http_get
    import ipaddress

    response = MagicMock()
    response.status_code = 302
    response.headers = {"location": "http://redis:6379/"}
    response.extensions = {}

    def resolve(hostname, _port):
        if hostname == "redis":
            return {ipaddress.ip_address("172.20.0.4")}
        return {ipaddress.ip_address("93.184.216.34")}

    with patch("app.agent_tools.httpx.get", return_value=response) as mock_get, patch(
        "app.agent_tools._resolve_host_addresses",
        side_effect=resolve,
    ):
        result = _tool_http_get("https://example.com/open-redirect")
    assert result["status"] == "failed"
    assert mock_get.call_count == 1


def test_browser_fetch_falls_back_when_browser_runtime_fails(monkeypatch):
    import app.agent_tools as tools
    import ipaddress

    monkeypatch.setattr(
        tools,
        "_resolve_host_addresses",
        lambda *_args: {ipaddress.ip_address("93.184.216.34")},
    )
    monkeypatch.setattr(
        tools,
        "_tool_http_get",
        lambda url: {"status": "success", "status_code": 200, "content": "fallback", "url": url},
    )

    # Force the Playwright path to fail independently of what is installed locally.
    with patch.dict("sys.modules", {"playwright.async_api": None}):
        result = tools._tool_browser_fetch("https://example.com")

    assert result["status"] == "success"
    assert result["content"] == "fallback"


def test_execute_tool_parse_html():
    from app.agent_tools import execute_tool
    html = "<html><body><h1>Title</h1><p>Paragraph text here.</p><script>alert('xss')</script></body></html>"
    result = execute_tool("parse_html", {"html": html})
    assert result["status"] == "success"
    assert "Title" in result["text"]
    assert "Paragraph text here." in result["text"]
    assert "alert" not in result["text"]  # script stripped


def test_execute_tool_unknown_tool():
    from app.agent_tools import execute_tool
    result = execute_tool("nonexistent_tool", {})
    assert result["status"] == "error"
    assert "unknown tool" in result.get("error", "").lower()


def test_execute_tool_write_to_rag(monkeypatch):
    from app.agent_tools import execute_tool
    from unittest.mock import MagicMock

    mock_ingest = MagicMock(return_value=(42, 5))
    monkeypatch.setattr("app.agent_tools.ingest_text_as_document", mock_ingest)

    result = execute_tool("write_to_rag", {
        "title": "Test Document",
        "content": "This is test content for RAG",
        "source_url": "https://example.com/data"
    })
    assert result["status"] == "success"
    assert result["doc_id"] == 42
    assert result["chunk_count"] == 5
    assert mock_ingest.call_args.kwargs["public"] is False


def test_execute_tool_write_to_rag_can_bind_private_owner(monkeypatch):
    from app.agent_tools import execute_tool
    from unittest.mock import MagicMock

    mock_ingest = MagicMock(return_value=(43, 6))
    monkeypatch.setattr("app.agent_tools.ingest_text_as_document", mock_ingest)

    result = execute_tool("write_to_rag", {
        "title": "Private collection",
        "content": "collected content",
        "source_url": "agent_pipeline_auto_collect",
        "user_id": 7,
        "public": False,
    })

    assert result["status"] == "success"
    mock_ingest.assert_called_once()
    assert mock_ingest.call_args.kwargs["user_id"] == 7
    assert mock_ingest.call_args.kwargs["public"] is False


def test_llm_cannot_call_tool_outside_agent_allowlist(monkeypatch):
    import app.agent_pipeline as ap
    from types import SimpleNamespace

    unauthorized = SimpleNamespace(
        id="call-1",
        function=SimpleNamespace(
            name="write_to_rag",
            arguments='{"title":"poison","content":"prompt injection"}',
        ),
    )
    responses = iter([
        SimpleNamespace(content="", tool_calls=[unauthorized]),
        SimpleNamespace(content='{"status":"success"}', tool_calls=[]),
    ])
    monkeypatch.setattr(ap, "chat_with_tools", lambda *_args, **_kwargs: next(responses))
    executed = []
    monkeypatch.setattr(
        "app.agent_tools.execute_tool",
        lambda name, args: executed.append((name, args)) or {"status": "success"},
    )
    http_only = [{
        "type": "function",
        "function": {
            "name": "http_get",
            "parameters": {"type": "object", "properties": {}},
        },
    }]

    result = ap._call_llm_with_tools("code_agent", [], http_only, max_rounds=2)

    assert result["status"] == "success"
    assert executed == []


# ── Pipeline DAG engine ───────────────────────────────────────────────────────

def test_load_pipeline_config():
    from app.agent_pipeline import _load_pipeline_config
    cfg = _load_pipeline_config()
    assert "stages" in cfg
    assert len(cfg["stages"]) == 4
    stage_ids = [s["id"] for s in cfg["stages"]]
    assert stage_ids == ["research", "plan", "code", "review"]


def test_topological_sort():
    from app.agent_pipeline import _topological_sort
    stages = [
        {"id": "research", "depends_on": []},
        {"id": "plan", "depends_on": ["research"]},
        {"id": "code", "depends_on": ["plan"]},
        {"id": "review", "depends_on": ["code"]},
    ]
    ordered = _topological_sort(stages)
    ids = [s["id"] for s in ordered]
    assert ids.index("research") < ids.index("plan")
    assert ids.index("plan") < ids.index("code")
    assert ids.index("code") < ids.index("review")


def test_topological_sort_diamond_dag():
    from app.agent_pipeline import _topological_sort
    stages = [
        {"id": "start", "depends_on": []},
        {"id": "left", "depends_on": ["start"]},
        {"id": "right", "depends_on": ["start"]},
        {"id": "end", "depends_on": ["left", "right"]},
    ]
    ordered = _topological_sort(stages)
    ids = [s["id"] for s in ordered]
    assert ids.index("start") == 0
    assert ids.index("end") == 3
    assert ids.index("start") < ids.index("left") < ids.index("end")
    assert ids.index("start") < ids.index("right") < ids.index("end")


def test_get_stage_dependencies():
    from app.agent_pipeline import _get_stage_by_id, _load_pipeline_config
    cfg = _load_pipeline_config()
    stage = _get_stage_by_id(cfg["stages"], "plan")
    assert stage is not None
    assert stage["id"] == "plan"
    assert "research" in stage.get("depends_on", [])


def test_parallel_stage_runs_one_agent_per_plan_item(monkeypatch):
    import app.agent_pipeline as ap

    seen = []

    def fake_execute(_stage, context, _question):
        task = context["plan"]["tasks"][0]
        seen.append(task["id"])
        return {
            "status": "success",
            "collected_data": [{"content_preview": task["id"]}],
            "tool_calls_made": 1,
        }

    monkeypatch.setattr(ap, "_execute_stage", fake_execute)
    result = ap._execute_parallel_stage(
        {"id": "code", "parallel": True, "max_parallel": 2},
        {"plan": {"tasks": [{"id": "a"}, {"id": "b"}, {"id": "c"}]}},
        "question",
    )

    assert sorted(seen) == ["a", "b", "c"]
    assert result["status"] == "success"
    assert result["tool_calls_made"] == 3
    assert sorted(x["content_preview"] for x in result["collected_data"]) == ["a", "b", "c"]


def test_parallel_stage_caps_llm_generated_plan(monkeypatch):
    import app.agent_pipeline as ap

    seen = []

    def fake_execute(_stage, context, _question):
        seen.append(context["plan"]["tasks"][0]["id"])
        return {"status": "success", "collected_data": [], "tool_calls_made": 0}

    monkeypatch.setattr(ap, "_execute_stage", fake_execute)
    tasks = [{"id": str(i)} for i in range(ap.MAX_PLAN_TASKS + 5)]
    result = ap._execute_parallel_stage(
        {"id": "code", "parallel": True, "max_parallel": 4},
        {"plan": {"tasks": tasks}},
        "question",
    )

    assert len(seen) == ap.MAX_PLAN_TASKS
    assert result["plan_truncated"] is True


def test_parallel_stage_respects_process_wide_worker_cap(monkeypatch):
    import app.agent_pipeline as ap

    captured = {}

    class FakeExecutor:
        def __init__(self, max_workers, thread_name_prefix):
            captured["max_workers"] = max_workers

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def map(self, fn, items):
            return [fn(item) for item in items]

    monkeypatch.setattr(ap, "ThreadPoolExecutor", FakeExecutor)
    monkeypatch.setattr(
        ap,
        "_execute_stage",
        lambda _stage, _context, _question: {
            "status": "success",
            "collected_data": [],
            "tool_calls_made": 0,
        },
    )
    tasks = [{"id": str(i)} for i in range(4)]
    ap._execute_parallel_stage(
        {"id": "code", "parallel": True, "max_parallel": 99},
        {"plan": {"tasks": tasks}},
        "question",
    )

    assert captured["max_workers"] == min(len(tasks), ap.PIPELINE_MAX_PARALLEL)


def test_pipeline_result_is_not_arbitrarily_cut_at_500_characters():
    import app.agent_pipeline as ap

    answer = "结果" * 400
    assert ap._bounded_final_answer(answer) == answer


def test_redis_progress_write_read(monkeypatch):
    import app.agent_pipeline as ap
    fake_store = {}
    class FakeRedis:
        def set(self, key, value, ex=None):
            fake_store[key] = value
        def get(self, key):
            return fake_store.get(key)
        def exists(self, key):
            return key in fake_store
    monkeypatch.setattr(ap, "_redis_client", lambda: FakeRedis())
    ap._set_progress("test_task_123", {"stage": "research", "status": "running"})
    progress = ap._get_progress("test_task_123")
    assert progress is not None
    assert progress["stage"] == "research"


def test_progress_falls_back_to_process_cache_without_redis(monkeypatch):
    import app.agent_pipeline as ap
    monkeypatch.setattr(ap, "_redis_client", lambda: None)
    ap._set_progress("local_cache_task", {"stage": "queued", "status": "pending"})
    assert ap._get_progress("local_cache_task") == {
        "stage": "queued", "status": "pending"
    }


def test_redis_failure_enters_cooldown_and_keeps_local_progress(monkeypatch):
    import app.agent_pipeline as ap

    class BrokenRedis:
        def get(self, *_args, **_kwargs):
            raise TimeoutError("redis unavailable")

        def set(self, *_args, **_kwargs):
            raise AssertionError("set must not run after get proved Redis down")

    monkeypatch.setattr(ap, "_redis_client_instance", BrokenRedis())
    monkeypatch.setattr(ap, "_redis_retry_after", 0.0)

    ap._set_progress("cooldown-task", {"stage": "research", "status": "running"})

    assert ap._get_progress("cooldown-task")["stage"] == "research"
    assert ap._redis_client_instance is None
    assert ap._redis_retry_after > time.monotonic()
    assert ap._redis_client() is None


def test_progress_updates_preserve_task_owner(monkeypatch):
    import app.agent_pipeline as ap
    monkeypatch.setattr(ap, "_redis_client", lambda: None)

    ap._set_progress("owner_task", {
        "stage": "queued", "status": "pending", "user_id": 7,
    })
    ap._set_progress("owner_task", {
        "stage": "research", "status": "running",
    })

    assert ap._get_progress("owner_task")["user_id"] == 7


def test_enqueue_pipeline_uses_local_background_when_redis_is_down(monkeypatch):
    import app.agent_pipeline as ap
    submitted = []

    class FakeExecutor:
        def submit(self, fn, *args):
            submitted.append((fn, args))

    monkeypatch.setattr(ap, "_redis_available", lambda: False, raising=False)
    monkeypatch.setattr(ap, "_local_executor", FakeExecutor(), raising=False)
    monkeypatch.setattr(ap, "PIPELINE_LOCAL_FALLBACK", True, raising=False)

    result = ap.enqueue_pipeline("task_local", "问题", 7)

    assert result["accepted"] is True
    assert result["mode"] == "local_background"
    assert submitted and submitted[0][1] == ("task_local", "问题", 7)
    assert ap._get_progress("task_local")["user_id"] == 7


def test_enqueue_pipeline_rejects_when_local_capacity_is_exhausted(monkeypatch):
    import app.agent_pipeline as ap

    class ExhaustedSlots:
        def acquire(self, blocking=False):
            assert blocking is False
            return False

    monkeypatch.setattr(ap, "_redis_available", lambda: False, raising=False)
    monkeypatch.setattr(ap, "_local_slots", ExhaustedSlots(), raising=False)
    monkeypatch.setattr(ap, "PIPELINE_LOCAL_FALLBACK", True, raising=False)

    result = ap.enqueue_pipeline("task_overflow", "问题", 7)

    assert result["accepted"] is False
    assert result["mode"] == "capacity_exhausted"
    assert "capacity exhausted" in result["error"]
    assert ap._get_progress("task_overflow")["status"] == "failed"


def test_run_pipeline_task_signature():
    from app.agent_pipeline import run_pipeline_task
    if run_pipeline_task is None:
        pytest.skip("Celery not installed")
    assert run_pipeline_task.name == "agent_pipeline.run"
    assert callable(run_pipeline_task.delay)


def test_celery_wrapper_preserves_done_terminal_stage(monkeypatch):
    import app.agent_pipeline as ap

    if ap.run_pipeline_task is None:
        pytest.skip("Celery not installed")
    monkeypatch.setattr(ap, "_redis_client", lambda: None)
    monkeypatch.setattr(ap, "run_pipeline", lambda *_: {
        "status": "completed",
        "final_answer": "采集完成",
    })

    result = ap.run_pipeline_task.run("celery_done_task", "问题", 7)
    progress = ap._get_progress("celery_done_task")

    assert result["status"] == "completed"
    assert progress["stage"] == "done"
    assert progress["status"] == "completed"
    assert progress["user_id"] == 7


def test_local_pipeline_config_failure_reaches_error_terminal_stage(monkeypatch):
    import app.agent_pipeline as ap

    monkeypatch.setattr(ap, "_redis_client", lambda: None)
    monkeypatch.setattr(ap, "_load_pipeline_config", lambda force_reload=False: {
        "stages": [],
        "agents": {},
    })

    result = ap.run_pipeline("local_config_error", "问题", 7)
    progress = ap._get_progress("local_config_error")

    assert result["status"] == "failed"
    assert progress["stage"] == "error"
    assert progress["status"] == "failed"
    assert progress["user_id"] == 7


# ── Integration: full import chain works ──────────────────────────────────────

def test_full_module_import_chain():
    """Verify all new modules can be imported without runtime errors."""
    from app.agent_tools import ALL_TOOLS, get_tool_definitions, execute_tool
    from app.agent_pipeline import _load_pipeline_config, _topological_sort, get_progress, run_pipeline_task

    # run_pipeline_task may be None if Celery not installed — that's fine
    cfg = _load_pipeline_config()
    assert "stages" in cfg
    assert "agents" in cfg

    stages = cfg["stages"]
    assert len(stages) >= 4

    ordered = _topological_sort(stages)
    stage_ids = [s["id"] for s in ordered]
    assert stage_ids.index("research") == 0
    assert stage_ids.index("review") == len(stage_ids) - 1

    code_schemas = get_tool_definitions("code_agent")
    assert len(code_schemas) >= 2

    if run_pipeline_task is not None:
        assert run_pipeline_task.name == "agent_pipeline.run"
