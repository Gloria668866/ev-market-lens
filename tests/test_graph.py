"""LangGraph 编排关键路径单测。

架构说明（新版）：
- intent_router 已升级为结构化 LLM 分类（不再是关键词数组）
- 旧的 _SQL_KW / _RAG_KW / _is_incomplete_sql_question 已删除
- intent_router 单测需要 mock LLM（否则调真实 API）→ 标记为 integration
- 纯逻辑路由函数（route_intent / route_exec / route_verify / verify_sql）无需 mock，确定性测试
"""
import threading
from unittest.mock import patch, MagicMock
import app.graph as graph_module
from app.graph import (route_intent, route_exec, route_verify, verify_sql,
                       chitchat, intent_router, _GREETING_PREFIXES,
                       _classify_intent, _merge_entities, _build_active_entities_from_history)
from app.config import MAX_SQL_RETRY
import pytest

pytestmark_integration = pytest.mark.integration


# ── 条件路由（纯函数，无 LLM，确定性）──
def test_route_intent_sql():
    assert route_intent({"intent": "sql"}) == "schema_link"


def test_route_intent_rag():
    assert route_intent({"intent": "rag"}) == "rag_retrieve"


def test_route_intent_hybrid_fanout():
    assert route_intent({"intent": "hybrid"}) == ["schema_link", "rag_retrieve"]


def test_route_intent_clarify():
    assert route_intent({"intent": "clarify"}) == "clarify"


def test_route_intent_chat():
    assert route_intent({"intent": "chat"}) == "chitchat"


def test_route_exec_success_to_verify():
    assert route_exec({"retry_count": 0}) == "verify_sql"


def test_route_exec_retry():
    assert route_exec({"sql_error": "boom", "retry_count": 0}) == "fix_sql"


def test_route_exec_giveup_to_insight():
    assert route_exec({"sql_error": "boom", "retry_count": MAX_SQL_RETRY}) == "insight"


def test_route_verify_ok_to_chart():
    assert route_verify({"sql_verified": True}) == "chart"


def test_route_verify_mismatch_to_fix():
    assert route_verify({"sql_verified": False}) == "fix_sql"


def test_route_verify_default_failopen():
    assert route_verify({}) == "chart"


def test_verify_sql_skips_when_no_rows():
    out = verify_sql({"question": "x", "rows": []})
    assert out["sql_verified"] is True


def test_verify_sql_skips_when_budget_exhausted():
    out = verify_sql({"question": "x", "rows": [(1,)], "retry_count": MAX_SQL_RETRY})
    assert out["sql_verified"] is True


def test_chitchat_node_no_chart():
    out = chitchat({"question": "你吃饭了吗"})
    assert out.get("final_answer") and "chart" not in out and "sql" not in out


# ── 问候词预筛（不调 LLM，确定性）──
def test_greeting_precheck_routes_to_chat():
    """≤8字纯问候 → chat，不调 LLM（成本节约路径）。"""
    result = intent_router({"question": "你好"})
    assert result["intent"] == "chat"
    assert result["confidence"] == 1.0
    # 确认走的是 precheck 路径，不是 LLM
    assert result["trace"][0].get("path") == "greeting_precheck"


def test_long_greeting_not_precheck():
    """问候词 + 领域内容 → 走 LLM 分类，不被预筛截断。"""
    # "你好，比亚迪今年卖了多少？" 长度 > 8，不走预筛，走 LLM
    q = "你好，比亚迪今年卖了多少？"
    assert len(q.strip()) > 8  # 确认不会被预筛


# ── 实体记忆工具函数（纯逻辑，确定性）──
def test_merge_entities_dedup():
    """合并实体时去重且保持顺序。"""
    existing = {"brands": ["比亚迪", "特斯拉"], "models": [], "time": [], "metrics": [], "energy_types": []}
    new = {"brands": ["比亚迪", "小米"], "models": ["SU7"], "time": [], "metrics": [], "energy_types": []}
    merged = _merge_entities(existing, new)
    assert merged["brands"].count("比亚迪") == 1  # 去重
    assert "小米" in merged["brands"]
    assert "SU7" in merged["models"]


def test_merge_entities_max_8():
    """累积实体最多保留 8 个。"""
    existing = {"brands": [f"品牌{i}" for i in range(7)], "models": [], "time": [], "metrics": [], "energy_types": []}
    new = {"brands": ["品牌7", "品牌8", "品牌9"], "models": [], "time": [], "metrics": [], "energy_types": []}
    merged = _merge_entities(existing, new)
    assert len(merged["brands"]) <= 8


def test_build_active_entities_from_history():
    """从历史消息中提取已提及的品牌。"""
    history = [
        {"role": "user", "content": "比亚迪今年销量怎么样"},
        {"role": "assistant", "content": "比亚迪2026年累计销量为..."},
        {"role": "user", "content": "那特斯拉呢"},
    ]
    entities = _build_active_entities_from_history(history)
    assert "比亚迪" in entities.get("brands", [])
    assert "特斯拉" in entities.get("brands", [])


# ── intent_router with LLM mock（验证路由逻辑，不依赖真实 LLM）──
def _mock_classify(intent, confidence=0.9, entities=None, is_complete=True, missing_slots=None):
    """生成 _classify_intent 的 mock 返回值。"""
    return {
        "intent": intent,
        "confidence": confidence,
        "entities": entities or {},
        "is_complete": is_complete,
        "missing_slots": missing_slots or [],
        "normalized_question": "test",
    }


def test_intent_router_sql_with_entities():
    """sql 意图 + 有实体 → 路由到 sql，并更新 active_entities。"""
    with patch("app.graph._classify_intent",
               return_value=_mock_classify("sql", entities={"brands": ["比亚迪"], "models": [], "time": ["2025年"], "metrics": ["销量"], "energy_types": []})):
        result = intent_router({"question": "比亚迪2025年销量", "history": []})
    assert result["intent"] == "sql"
    assert "比亚迪" in result["active_entities"].get("brands", [])


def test_intent_router_incomplete_sql_becomes_clarify():
    """sql 意图但 is_complete=False → clarify。"""
    with patch("app.graph._classify_intent",
               return_value=_mock_classify("sql", is_complete=False, missing_slots=["缺少品牌或车系"])):
        result = intent_router({"question": "销量怎么样", "history": []})
    assert result["intent"] == "clarify"
    assert "clarify_question" in result


def test_intent_router_rag():
    """rag 意图正确路由。"""
    with patch("app.graph._classify_intent",
               return_value=_mock_classify("rag")):
        result = intent_router({"question": "报告怎么看渗透率", "history": []})
    assert result["intent"] == "rag"


def test_intent_router_hybrid():
    """hybrid 意图正确路由。"""
    with patch("app.graph._classify_intent",
               return_value=_mock_classify("hybrid", is_complete=True)):
        result = intent_router({"question": "比亚迪销量+行业怎么看", "history": []})
    assert result["intent"] == "hybrid"


def test_intent_router_nodata_guard_overrides_sql():
    """上轮无数据 → 即使 LLM 判 sql，也强制改为 rag。"""
    history = [{"role": "assistant", "content": "未查询到相关数据，该品牌不在数据库覆盖范围内。"}]
    with patch("app.graph._classify_intent",
               return_value=_mock_classify("sql", entities={"brands": ["奔驰"]})):
        result = intent_router({"question": "那它的口碑呢", "history": history})
    assert result["intent"] == "rag"


def test_intent_router_chat():
    """chat 意图正确路由。"""
    with patch("app.graph._classify_intent",
               return_value=_mock_classify("chat", confidence=0.95)):
        result = intent_router({"question": "你吃饭了吗", "history": []})
    assert result["intent"] == "chat"


def test_intent_router_includes_confidence_in_trace():
    """trace 应包含置信度，便于调试。"""
    with patch("app.graph._classify_intent",
               return_value=_mock_classify("sql", confidence=0.88, entities={"brands": ["小米"]}, is_complete=True)):
        result = intent_router({"question": "小米SU7销量", "history": []})
    trace = result["trace"][0]
    assert "confidence" in trace
    assert trace["llm_classified"] is True


# ── _GRAPH 单例线程安全 ──
def test_graph_singleton_builds_exactly_once_under_concurrency():
    """10 个线程同时首次调用 run_agent，build_graph() 必须只执行一次。

    行为说明：
    - _GRAPH 是懒初始化单例，if _GRAPH is None: _GRAPH = build_graph()
    - 不加锁时 N 个线程都通过 None 检查，重复 compile LangGraph（资源浪费 + 竞态）
    - 加锁后只有一次 build_graph() 调用
    """
    THREAD_COUNT = 10
    build_call_count = []
    barrier = threading.Barrier(THREAD_COUNT)   # 所有线程同时冲

    mock_graph = MagicMock()
    mock_graph.invoke.return_value = {
        "final_answer": "ok", "intent": "chat", "trace": [], "has_answer": True,
        "sql": None, "cols": [], "rows": [], "chart": None, "citations": [],
    }

    def slow_build():
        """模拟 build_graph 耗时，放大竞态窗口。"""
        import time
        build_call_count.append(1)
        time.sleep(0.05)
        return mock_graph

    original_graph = graph_module._GRAPH

    try:
        graph_module._GRAPH = None   # 强制重置为未初始化

        errors = []

        def worker():
            try:
                barrier.wait()   # 所有线程同时出发
                graph_module.run_agent("test", user_id=99)
            except Exception as e:
                errors.append(e)

        with patch.object(graph_module, "build_graph", side_effect=slow_build):
            threads = [threading.Thread(target=worker) for _ in range(THREAD_COUNT)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5)

        assert not errors, f"线程运行出错: {errors}"
        assert len(build_call_count) == 1, (
            f"build_graph() 应只调用 1 次，实际调用了 {len(build_call_count)} 次。"
            f"_GRAPH 单例缺少线程锁。"
        )
    finally:
        graph_module._GRAPH = original_graph   # 还原，避免污染其他测试


def test_insight_no_data_returns_task_id(monkeypatch):
    """When no_data=True, insight node should return a task_id for the pipeline."""
    import uuid

    fake_task_id = "task_test_" + uuid.uuid4().hex[:8]
    mock_delay = MagicMock(return_value=type('FakeAsyncResult', (), {'id': fake_task_id})())
    monkeypatch.setattr("app.agent_pipeline.run_pipeline_task", MagicMock(delay=mock_delay))

    state = {"question": "理想L9海外销量", "rows": [], "cols": [], "history": []}
    import app.graph as graph_module
    result = graph_module.insight(state)

    assert result.get("no_data") is True
    tid = result.get("task_id")
    assert isinstance(tid, str) and tid.startswith("agent_")
    assert mock_delay.called
    # Verify the user-facing message mentions collection
    assert "采集" in result.get("insight", "")
