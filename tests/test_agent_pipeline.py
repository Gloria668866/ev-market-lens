"""Tests for agent pipeline: tools, DAG execution, pipeline runner."""
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
    with patch("app.agent_tools.httpx.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body>Test page content</body></html>"
        mock_resp.headers = {"content-type": "text/html"}
        mock_get.return_value = mock_resp

        result = execute_tool("http_get", {"url": "https://example.com"})
        assert result["status"] == "success"
        assert result["status_code"] == 200
        assert "Test page content" in result["content"]


def test_execute_tool_http_get_http_error():
    from app.agent_tools import execute_tool
    with patch("app.agent_tools.httpx.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.text = "Forbidden"
        mock_get.return_value = mock_resp

        result = execute_tool("http_get", {"url": "https://blocked.example.com"})
        assert result["status"] == "failed"
        assert result["status_code"] == 403


def test_execute_tool_http_get_timeout():
    from app.agent_tools import execute_tool
    import httpx
    with patch("app.agent_tools.httpx.get", side_effect=httpx.TimeoutException("timeout")):
        result = execute_tool("http_get", {"url": "https://slow.example.com"})
        assert result["status"] == "failed"
        assert "timeout" in result.get("error", "").lower()


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


def test_run_pipeline_task_signature():
    from app.agent_pipeline import run_pipeline_task
    if run_pipeline_task is None:
        pytest.skip("Celery not installed")
    assert run_pipeline_task.name == "agent_pipeline.run"
    assert callable(run_pipeline_task.delay)


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
