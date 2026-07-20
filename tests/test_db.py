"""只读库执行单测（Text2SQL 执行端关键路径，依赖 bi_demo.db）。"""
import pytest

pytestmark = pytest.mark.integration   # 需 bi_demo.db

from app.db import run_query, get_schema_text  # noqa: E402


def test_run_query_returns_rows():
    cols, rows = run_query("SELECT COUNT(*) AS n FROM fact_sales_rank")
    assert "n" in cols and rows and rows[0]["n"] > 0


def test_schema_text_has_core_tables():
    s = get_schema_text()
    assert "fact_sales_rank" in s and "dim_date" in s
