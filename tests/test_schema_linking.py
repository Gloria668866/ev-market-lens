"""Schema Linking 单测（依赖只读分析库 bi_demo.db）。"""
import pytest

pytestmark = pytest.mark.integration   # 需 bi_demo.db

from app.schema_linking import link_schema  # noqa: E402


def test_small_db_returns_full_schema():
    s = link_schema("2025年纯电销量排名")
    assert "fact_sales_rank" in s and "dim_series" in s
