"""SQL 安全护栏单测（Text2SQL 关键路径）：只放行单条 SELECT，拦截写/多语句。"""
import pytest
from app.sql_guard import ensure_safe, with_limit, UnsafeSQLError


def test_allow_select():
    assert ensure_safe("SELECT * FROM fact_sales_rank").upper().startswith("SELECT")


@pytest.mark.parametrize("sql", [
    "INSERT INTO t VALUES(1)",
    "UPDATE t SET a=1",
    "DELETE FROM t",
    "DROP TABLE t",
    "SELECT 1; DROP TABLE t",     # 多语句注入
    "CREATE TABLE x(a int)",
])
def test_block_dangerous(sql):
    with pytest.raises(UnsafeSQLError):
        ensure_safe(sql)


def test_with_limit_adds_when_missing():
    assert "LIMIT" in with_limit("SELECT * FROM t").upper()


def test_with_limit_keeps_existing():
    s = "SELECT * FROM t LIMIT 5"
    assert with_limit(s) == s


def test_column_named_update_not_misfired():
    # update_time 这种列名不应被误判为 UPDATE 关键字
    assert ensure_safe("SELECT update_time FROM fact_sales_rank").upper().startswith("SELECT")


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM users",
        "SELECT * FROM pg_catalog.pg_user",
        "SELECT pg_sleep(10)",
        "SELECT * FROM generate_series(1, 1000000)",
        "SELECT * FROM dim_brand CROSS JOIN fact_sales_rank",
        "SELECT * FROM dim_brand JOIN fact_sales_rank",
    ],
)
def test_block_non_analytics_tables_dangerous_functions_and_cross_joins(sql):
    with pytest.raises(UnsafeSQLError):
        ensure_safe(sql)


def test_allow_cte_over_whitelisted_tables():
    sql = (
        "WITH ranked AS (SELECT series_id, volume FROM fact_sales_rank) "
        "SELECT * FROM ranked"
    )
    assert ensure_safe(sql).startswith("WITH")
