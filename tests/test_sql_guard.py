"""SQL 安全护栏单测（Text2SQL 关键路径）：只放行单条 SELECT，拦截写/多语句。"""
import pytest
from app.sql_guard import ensure_safe, with_limit, UnsafeSQLError


def test_allow_select():
    assert ensure_safe("SELECT * FROM t").upper().startswith("SELECT")


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
    assert ensure_safe("SELECT update_time FROM t").upper().startswith("SELECT")
