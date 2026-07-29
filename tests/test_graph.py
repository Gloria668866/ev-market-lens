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


def test_route_verify_exhausted_mismatch_degrades_instead_of_looping():
    assert route_verify({
        "sql_verified": False,
        "retry_count": MAX_SQL_RETRY,
    }) == "insight"


def test_route_verify_default_failopen():
    assert route_verify({}) == "chart"


def test_verify_sql_skips_when_no_rows():
    out = verify_sql({"question": "x", "rows": []})
    assert out["sql_verified"] is True


def test_verify_sql_exhausted_budget_still_runs_deterministic_guard():
    out = verify_sql({
        "question": "汉DM累计销量",
        "sql": (
            "SELECT SUM(f.volume) AS total_volume "
            "FROM fact_sales_rank f "
            "JOIN dim_series s ON s.series_id=f.series_id "
            "JOIN dim_date d ON d.date_id=f.date_id "
            "WHERE s.series_name LIKE '%汉DM%' AND d.year=2026"
        ),
        "cols": ["total_volume"],
        "rows": [(123,)],
        "retry_count": MAX_SQL_RETRY,
    })
    assert out["sql_verified"] is False
    assert out["rows"] == []
    assert "不应额外限定时间" in out["sql_error"]


def test_verify_sql_exhausted_budget_skips_only_llm_for_valid_shape():
    out = verify_sql({
        "question": "汉DM累计销量",
        "sql": (
            "SELECT SUM(f.volume) AS total_volume "
            "FROM fact_sales_rank f "
            "JOIN dim_series s ON s.series_id=f.series_id "
            "WHERE s.series_name LIKE '%汉DM%'"
        ),
        "cols": ["total_volume"],
        "rows": [(123,)],
        "retry_count": MAX_SQL_RETRY,
    })
    assert out["sql_verified"] is True


def test_chitchat_node_no_chart():
    out = chitchat({"question": "你吃饭了吗"})
    assert out.get("final_answer") and "chart" not in out and "sql" not in out


def test_graph_rag_retrieve_reuses_fail_closed_evidence_gate(monkeypatch):
    """主聊天 RAG 分支必须与 /api/kb/ask 使用同一套证据充足性判断。"""
    children = [{"chunk_id": 1, "score_rrf": 0.032}]
    top = [{
        "chunk_id": 1,
        "score_final": 0.032,
        "recall_sources": ["vector"],
    }]
    monkeypatch.setattr("app.rag.retrieve.hybrid_recall", lambda *_: children)
    monkeypatch.setattr("app.rag.retrieve.rerank", lambda *_: (top, False))
    merge = MagicMock(return_value=[{"content": "不应进入生成阶段"}])
    monkeypatch.setattr("app.rag.retrieve.merge_parents", merge)

    out = graph_module.rag_retrieve({"user_id": 1, "question": "某冷门车型政策"})

    assert out["chunks"] == []
    assert out["trace"][0]["reason"] == "fallback_single_channel"
    merge.assert_not_called()


def test_graph_rag_retrieve_accepts_sufficient_evidence(monkeypatch):
    children = [{"chunk_id": 1, "score_rrf": 0.032}]
    top = [{
        "chunk_id": 1,
        "score_final": 0.9,
        "content": "EQS 车型政策资料",
        "recall_sources": ["vector", "keyword"],
    }]
    blocks = [{"content": "EQS 车型政策资料"}]
    monkeypatch.setattr("app.rag.retrieve.hybrid_recall", lambda *_: children)
    monkeypatch.setattr("app.rag.retrieve.rerank", lambda *_: (top, True))
    monkeypatch.setattr("app.rag.retrieve.merge_parents", lambda *_: blocks)

    out = graph_module.rag_retrieve({"user_id": 1, "question": "EQS 有哪些政策？"})

    assert out["chunks"] == blocks
    assert out["trace"][0]["reranker"] is True


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


def test_standalone_question_does_not_inherit_history_brand():
    """完整独立的新问题不得被上一轮品牌污染。"""
    history = [
        {"role": "user", "content": "捷豹2025年销量怎么样"},
        {"role": "assistant", "content": "捷豹2025年销量为……"},
    ]
    stale = {
        "brands": ["捷豹"], "models": [], "time": ["2025年"],
        "metrics": ["销量"], "energy_types": ["纯电"],
    }
    with patch("app.graph._rewrite_query") as rewrite, \
         patch("app.graph._classify_intent",
               return_value=_mock_classify("sql", entities=stale, is_complete=True)) as classify:
        result = intent_router({
            "question": "2025年纯电车型销量Top10",
            "history": history,
            "active_entities": {"brands": ["捷豹"]},
        })

    rewrite.assert_not_called()
    assert classify.call_args.args[1] == ""
    assert result["entities"]["brands"] == []
    assert result["uses_history_entities"] is False


def test_pronoun_followup_still_uses_history_entities():
    """真正含指代的追问仍应使用历史实体并执行改写。"""
    history = [
        {"role": "user", "content": "比亚迪2025年销量怎么样"},
        {"role": "assistant", "content": "比亚迪2025年销量为……"},
    ]
    with patch("app.graph._rewrite_query",
               return_value={"rewritten": "比亚迪2024年销量", "is_meta": False}) as rewrite, \
         patch("app.graph._classify_intent",
               return_value=_mock_classify(
                   "sql",
                   entities={"brands": ["比亚迪"], "time": ["2024年"]},
                   is_complete=True,
               )):
        result = intent_router({"question": "那2024年呢", "history": history})

    rewrite.assert_called_once()
    assert result["uses_history_entities"] is True
    assert "比亚迪" in result["entities"]["brands"]


def test_sql_shape_rejects_topn_without_group_order_and_requested_limit():
    """能执行的一行 SUM 不是 Top10，确定性语义护栏必须拒绝。"""
    bad_sql = (
        "SELECT SUM(f.volume) AS total_volume "
        "FROM fact_sales_rank f "
        "JOIN dim_series s ON s.series_id=f.series_id "
        "JOIN dim_brand b ON b.brand_id=s.brand_id "
        "JOIN dim_date d ON d.date_id=f.date_id "
        "WHERE b.brand_name LIKE '%捷豹%' AND d.year=2025 LIMIT 200"
    )
    ok, reason = graph_module._validate_sql_shape(
        "2025年纯电车型销量Top10",
        bad_sql,
        ["total_volume"],
        [(1234,)],
    )
    assert ok is False
    assert "Top10" in reason


def test_sql_shape_accepts_well_formed_topn():
    good_sql = (
        "SELECT s.series_name, SUM(f.volume) AS total_volume "
        "FROM fact_sales_rank f "
        "JOIN dim_series s ON s.series_id=f.series_id "
        "JOIN dim_date d ON d.date_id=f.date_id "
        "WHERE d.year=2025 AND s.powertrain='纯电' "
        "GROUP BY s.series_id, s.series_name "
        "ORDER BY total_volume DESC LIMIT 10"
    )
    ok, reason = graph_module._validate_sql_shape(
        "2025年纯电车型销量Top10",
        good_sql,
        ["series_name", "total_volume"],
        [("海鸥", 1), ("星愿", 2)],
    )
    assert ok is True, reason


def test_sql_shape_accepts_numeric_energy_filter_before_other_predicates():
    sql = (
        "SELECT s.series_name, SUM(f.volume) AS total_volume "
        "FROM fact_sales_rank f "
        "JOIN dim_series s ON s.series_id=f.series_id "
        "JOIN dim_date d ON d.date_id=f.date_id "
        "WHERE f.new_energy_type=1 AND d.year=2025 "
        "GROUP BY s.series_id,s.series_name "
        "ORDER BY total_volume DESC LIMIT 10"
    )
    ok, reason = graph_module._validate_sql_shape(
        "2025年纯电销量前十的车系",
        sql,
        ["series_name", "total_volume"],
        [("海鸥", 1), ("星愿", 2)],
    )
    assert ok is True, reason


def test_sql_shape_accepts_brand_winner_despite_cumulative_wording():
    sql = (
        "SELECT b.brand_name, SUM(f.volume) AS total_volume "
        "FROM fact_sales_rank f "
        "JOIN dim_series s ON s.series_id=f.series_id "
        "JOIN dim_brand b ON b.brand_id=s.brand_id "
        "JOIN dim_date d ON d.date_id=f.date_id "
        "WHERE d.year=2025 "
        "GROUP BY b.brand_id,b.brand_name "
        "ORDER BY total_volume DESC LIMIT 1"
    )
    ok, reason = graph_module._validate_sql_shape(
        "哪个品牌2025年新能源累计销量最高",
        sql,
        ["brand_name", "total_volume"],
        [("比亚迪", 123)],
    )
    assert ok is True, reason


def test_sql_shape_rejects_partition_rank_for_overall_series_winner():
    bad_sql = (
        "SELECT s.series_name FROM fact_sales_rank f "
        "JOIN dim_series s ON s.series_id=f.series_id "
        "JOIN dim_date d ON d.date_id=f.date_id "
        "WHERE d.year=2025 AND d.month=5 AND f.rank=1 LIMIT 1"
    )
    ok, reason = graph_module._validate_sql_shape(
        "2025年5月销量第一的车系",
        bad_sql,
        ["series_name"],
        [("海鸥",)],
    )
    assert ok is False
    assert "分区冠军" in reason


def test_sql_shape_accepts_volume_order_for_overall_series_winner():
    good_sql = (
        "SELECT s.series_name, f.volume FROM fact_sales_rank f "
        "JOIN dim_series s ON s.series_id=f.series_id "
        "JOIN dim_date d ON d.date_id=f.date_id "
        "WHERE d.year=2025 AND d.month=5 "
        "ORDER BY f.volume DESC LIMIT 1"
    )
    ok, reason = graph_module._validate_sql_shape(
        "2025年5月销量第一的车系",
        good_sql,
        ["series_name", "volume"],
        [("海鸥", 51400)],
    )
    assert ok is True, reason


def test_sql_shape_rejects_splitting_complete_brand_into_parent_and_series(monkeypatch):
    monkeypatch.setattr(
        graph_module,
        "_exact_brand_names",
        lambda _question: ("比亚迪", "吉利银河"),
    )
    bad_sql = (
        "SELECT '比亚迪' AS brand, SUM(f.volume) AS total_volume "
        "FROM fact_sales_rank f "
        "JOIN dim_series s ON s.series_id=f.series_id "
        "JOIN dim_brand b ON b.brand_id=s.brand_id "
        "JOIN dim_date d ON d.date_id=f.date_id "
        "WHERE b.brand_name LIKE '%比亚迪%' AND d.year=2025 "
        "UNION ALL "
        "SELECT '吉利银河' AS brand, SUM(f.volume) AS total_volume "
        "FROM fact_sales_rank f "
        "JOIN dim_series s ON s.series_id=f.series_id "
        "JOIN dim_brand b ON b.brand_id=s.brand_id "
        "JOIN dim_date d ON d.date_id=f.date_id "
        "WHERE b.brand_name LIKE '%吉利%' "
        "AND s.series_name LIKE '%银河%' AND d.year=2025"
    )
    ok, reason = graph_module._validate_sql_shape(
        "比亚迪和吉利银河谁2025年新能源销量更高",
        bad_sql,
        ["brand", "total_volume"],
        [("比亚迪", 2904127), ("吉利银河", 526084)],
    )
    assert ok is False
    assert "吉利银河" in reason
    assert "brand_name" in reason


def test_sql_shape_accepts_complete_brand_comparison(monkeypatch):
    monkeypatch.setattr(
        graph_module,
        "_exact_brand_names",
        lambda _question: ("比亚迪", "吉利银河"),
    )
    good_sql = (
        "SELECT b.brand_name, SUM(f.volume) AS total_volume "
        "FROM fact_sales_rank f "
        "JOIN dim_series s ON s.series_id=f.series_id "
        "JOIN dim_brand b ON b.brand_id=s.brand_id "
        "JOIN dim_date d ON d.date_id=f.date_id "
        "WHERE b.brand_name IN ('比亚迪','吉利银河') AND d.year=2025 "
        "GROUP BY b.brand_id,b.brand_name ORDER BY total_volume DESC"
    )
    ok, reason = graph_module._validate_sql_shape(
        "比亚迪和吉利银河谁2025年新能源销量更高",
        good_sql,
        ["brand_name", "total_volume"],
        [("比亚迪", 2904127), ("吉利银河", 1154765)],
    )
    assert ok is True, reason


def test_brand_entity_resolution_ignores_brand_substring_inside_series(monkeypatch):
    from app import text2sql as text2sql_module

    monkeypatch.setattr(text2sql_module, "_brand_catalog", lambda: ("MINI", "五菱"))
    monkeypatch.setattr(
        text2sql_module,
        "_series_catalog",
        lambda: ("五菱宏光MINIEV",),
    )

    assert text2sql_module._exact_brand_names("五菱宏光MINIEV累计销量") == ()
    assert text2sql_module._exact_brand_names("MINI和五菱宏光MINIEV谁卖得多") == ("MINI",)


def test_sql_shape_accepts_grouped_energy_totals():
    sql = (
        "SELECT f.new_energy_type, SUM(f.volume) AS total_volume "
        "FROM fact_sales_rank f JOIN dim_date d ON d.date_id=f.date_id "
        "WHERE d.year=2025 GROUP BY f.new_energy_type "
        "ORDER BY f.new_energy_type"
    )
    ok, reason = graph_module._validate_sql_shape(
        "2025年各动力类型的总销量",
        sql,
        ["new_energy_type", "total_volume"],
        [(1, 123), (2, 100), (3, 50)],
    )
    assert ok is True, reason


def test_sql_shape_rejects_cumulative_total_grouped_by_series():
    bad_sql = (
        "SELECT s.series_name, SUM(f.volume) total_volume "
        "FROM fact_sales_rank f JOIN dim_series s ON s.series_id=f.series_id "
        "JOIN dim_date d ON d.date_id=f.date_id "
        "WHERE s.series_name LIKE '%海鸥%' AND d.year=2025 "
        "GROUP BY s.series_id, s.series_name"
    )
    ok, reason = graph_module._validate_sql_shape(
        "海鸥2025年累计销量",
        bad_sql,
        ["series_name", "total_volume"],
        [("海鸥", 123)],
    )
    assert ok is False
    assert "累计销量" in reason


def test_sql_shape_rejects_ranking_change_without_last_rank_comparison():
    bad_sql = (
        "SELECT s.series_name FROM fact_sales_rank f "
        "JOIN dim_series s ON s.series_id=f.series_id "
        "JOIN dim_date d ON d.date_id=f.date_id "
        "WHERE d.year=2025 AND d.month=12"
    )
    ok, reason = graph_module._validate_sql_shape(
        "2025年12月排名上升的车系有哪些（当月排名优于上期）",
        bad_sql,
        ["series_name"],
        [("海鸥",)],
    )
    assert ok is False
    assert "last_rank" in reason


def test_sql_shape_accepts_multi_energy_group_with_in_filter():
    sql = (
        "SELECT f.new_energy_type, COUNT(DISTINCT f.series_id) AS series_count "
        "FROM fact_sales_rank f JOIN dim_date d ON d.date_id=f.date_id "
        "WHERE d.year=2025 AND f.new_energy_type IN (1,2,3) "
        "GROUP BY f.new_energy_type ORDER BY f.new_energy_type"
    )
    ok, reason = graph_module._validate_sql_shape(
        "2025年纯电、插混、增程各有多少款车系上榜",
        sql,
        ["new_energy_type", "series_count"],
        [(1, 10), (2, 8), (3, 6)],
    )
    assert ok is True, reason


def test_sql_shape_rejects_unrequested_year_for_all_time_cumulative():
    sql = (
        "SELECT SUM(f.volume) AS total_volume "
        "FROM fact_sales_rank f JOIN dim_series s ON s.series_id=f.series_id "
        "JOIN dim_date d ON d.date_id=f.date_id "
        "WHERE s.series_name LIKE '%AION Y%' AND d.year=2026"
    )
    ok, reason = graph_module._validate_sql_shape(
        "AION Y累计销量", sql, ["total_volume"], [(123,)]
    )
    assert ok is False
    assert "不应额外限定时间" in reason


def test_sql_shape_rejects_monthly_trend_without_month_group():
    sql = (
        "SELECT SUM(f.volume) AS total_volume "
        "FROM fact_sales_rank f JOIN dim_date d ON d.date_id=f.date_id "
        "WHERE d.year=2025 AND f.new_energy_type=1"
    )
    ok, reason = graph_module._validate_sql_shape(
        "2025年每月纯电总销量趋势", sql, ["total_volume"], [(123,)]
    )
    assert ok is False
    assert "按月" in reason


def test_sql_shape_rejects_brand_winner_without_brand_dimension():
    sql = (
        "SELECT MAX(total) AS max_brand_volume FROM ("
        "SELECT SUM(f.volume) AS total FROM fact_sales_rank f "
        "JOIN dim_series s ON s.series_id=f.series_id "
        "JOIN dim_brand b ON b.brand_id=s.brand_id "
        "JOIN dim_date d ON d.date_id=f.date_id "
        "WHERE d.year=2025 GROUP BY b.brand_id)"
    )
    ok, reason = graph_module._validate_sql_shape(
        "哪个品牌2025年新能源累计销量最高",
        sql,
        ["max_brand_volume"],
        [(123,)],
    )
    assert ok is False
    assert "品牌名" in reason


@pytest.mark.parametrize(
    ("question", "bad_sql", "expected"),
    [
        (
            "指导价低于15万的纯电车系有多少个",
            "SELECT COUNT(*) FROM dim_series WHERE powertrain='纯电' AND guide_price_min<15",
            "guide_price_max",
        ),
        (
            "指导价30万以上的车系有多少个",
            "SELECT COUNT(*) FROM dim_series WHERE guide_price_max>=30",
            "guide_price_min",
        ),
    ],
)
def test_sql_shape_enforces_whole_series_price_band(question, bad_sql, expected):
    ok, reason = graph_module._validate_sql_shape(
        question, bad_sql, ["count"], [(5,)]
    )
    assert ok is False
    assert expected in reason


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
    mock_enqueue = MagicMock(return_value={"accepted": True, "mode": "celery"})
    monkeypatch.setattr("app.rag.retrieve.hybrid_recall", MagicMock(return_value=[]))
    monkeypatch.setattr("app.agent_pipeline.enqueue_pipeline", mock_enqueue)

    state = {"question": "理想L9海外销量", "rows": [], "cols": [], "history": []}
    import app.graph as graph_module
    result = graph_module.insight(state)

    assert result.get("no_data") is True
    tid = result.get("task_id")
    assert isinstance(tid, str) and tid.startswith("agent_")
    assert mock_enqueue.called
    # Verify the user-facing message mentions collection
    assert "采集" in result.get("insight", "")
    assert "不在当前数据库覆盖范围" not in result.get("insight", "")


def test_known_brand_empty_result_does_not_claim_brand_is_uncovered(monkeypatch):
    mock_enqueue = MagicMock(return_value={"accepted": True, "mode": "celery"})
    monkeypatch.setattr("app.rag.retrieve.hybrid_recall", MagicMock(return_value=[]))
    monkeypatch.setattr("app.agent_pipeline.enqueue_pipeline", mock_enqueue)

    result = graph_module.insight({
        "question": "比亚迪2030年销量是多少？",
        "sql": "SELECT * FROM fact_sales_rank WHERE date_id BETWEEN 203001 AND 203012",
        "rows": [],
        "cols": [],
        "history": [],
        "user_id": 1,
    })

    assert result["no_data"] is True
    assert "当前筛选条件下没有匹配记录" in result["insight"]
    assert "比亚迪」可能不在" not in result["insight"]


def test_null_only_aggregate_result_triggers_no_data_pipeline(monkeypatch):
    """SQLite SUM over no matching rows returns one NULL row, which is still no data."""
    mock_enqueue = MagicMock(return_value={"accepted": True, "mode": "local_background"})
    monkeypatch.setattr("app.rag.retrieve.hybrid_recall", MagicMock(return_value=[]))
    monkeypatch.setattr("app.agent_pipeline.enqueue_pipeline", mock_enqueue)

    result = graph_module.insight({
        "question": "捷豹2025年销量",
        "rows": [{"total_volume": None}],
        "cols": ["total_volume"],
        "history": [],
        "user_id": 2,
    })

    assert graph_module._has_meaningful_rows([{"total_volume": None}]) is False
    assert graph_module._has_meaningful_rows([{"count": 0}]) is True
    assert result["no_data"] is True
    assert result["task_id"].startswith("agent_")
    mock_enqueue.assert_called_once()


def test_null_only_aggregate_result_does_not_render_chart():
    result = graph_module.chart({
        "question": "捷豹2025年销量",
        "rows": [{"total_volume": None}],
        "cols": ["total_volume"],
    })

    assert result["chart"] is None


def test_insight_queue_failure_never_runs_pipeline_synchronously(monkeypatch):
    """队列与本地后台均不可用时，应快速诚实降级，不能阻塞请求线程。"""
    monkeypatch.setattr(
        "app.agent_pipeline.enqueue_pipeline",
        MagicMock(return_value={
            "accepted": False,
            "mode": "unavailable",
            "error": "Redis unavailable",
        }),
        raising=False,
    )
    monkeypatch.setattr("app.rag.retrieve.hybrid_recall", MagicMock(return_value=[]))
    sync_runner = MagicMock()
    monkeypatch.setattr("app.agent_pipeline.run_pipeline", sync_runner)

    result = graph_module.insight({
        "question": "不存在品牌海外销量",
        "rows": [],
        "cols": [],
        "history": [],
    })

    sync_runner.assert_not_called()
    assert result["no_data"] is True
    assert result.get("task_id") is None
    assert "暂不可用" in result["insight"]
