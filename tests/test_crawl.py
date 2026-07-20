"""采集纯函数单测（T3 关键路径）：月份枚举。"""
import pytest

cs = pytest.importorskip("crawl_sales")  # data/crawl_sales.py


def test_month_range_cross_year():
    assert cs.month_range("202411", "202502") == ["202411", "202412", "202501", "202502"]


def test_month_range_single():
    assert cs.month_range("202501", "202501") == ["202501"]
