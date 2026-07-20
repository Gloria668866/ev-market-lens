"""图表描述符规则引擎单测（T8 关键路径）。"""
from app.charts import recommend_chart


def test_empty_returns_none():
    assert recommend_chart([], [], "q") is None


def test_no_numeric_is_table():
    spec = recommend_chart(["series_name", "note"], [{"series_name": "A", "note": "x"}], "q")
    assert spec["default_type"] == "table"


def test_text_dimension_is_bar():
    rows = [{"series_name": f"S{i}", "v": i + 1} for i in range(5)]
    spec = recommend_chart(["series_name", "v"], rows, "销量")
    assert spec["default_type"] == "bar"
    assert spec["dimension"] == "series_name" and "v" in spec["measures"]


def test_many_categories_is_hbar():
    rows = [{"s": f"S{i}", "v": i + 1} for i in range(20)]
    spec = recommend_chart(["s", "v"], rows, "q")
    assert spec["default_type"] == "hbar"


def test_few_categories_single_measure_adds_pie():
    rows = [{"s": f"S{i}", "v": i + 1} for i in range(5)]
    spec = recommend_chart(["s", "v"], rows, "q")
    assert "pie" in spec["applicable_types"]


def test_time_only_is_line():
    rows = [{"ym": f"2025-0{i}", "v": i} for i in range(1, 6)]
    spec = recommend_chart(["ym", "v"], rows, "趋势")
    assert spec["default_type"] == "line"
