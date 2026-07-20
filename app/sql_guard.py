"""SQL 安全护栏：用 sqlglot 把 SQL 解析成 AST，在 AST 层判定安全性。

只放行**单条 SELECT**（含 CTE / UNION 等集合查询），拦截一切写操作
（INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/TRUNCATE/GRANT...）与多语句注入。

为什么用 sqlglot AST 而不是正则/关键字匹配：
- AST 级判断语句类型，可靠——不会把列名 `update_time` 误判成 UPDATE 关键字；
- 不会被大小写、注释、空白、换行绕过（解析器已规整）；
- 能遍历子树，连子查询/CTE 里藏的写操作也能揪出来。
这是纵深防御的应用层：配合数据库**只读账号**双保险（即使绕过这层，DB 也写不了）。
"""
import sqlglot
from sqlglot import exp


class UnsafeSQLError(Exception):
    pass


# 顶层语句只放行：SELECT 及其集合操作（UNION/INTERSECT/EXCEPT 仍是只读查询）
_ALLOWED_TOP = (exp.Select, exp.Union, exp.Intersect, exp.Except)

# AST 子树里只要出现这些节点 = 写/DDL/命令，一律拦截（防 CTE/子查询里藏 DML）
_FORBIDDEN = (
    exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Alter, exp.Create,
    exp.TruncateTable, exp.Command,   # GRANT/REVOKE/EXEC 等常被解析成 Command
    exp.Set, exp.Use,
)


def ensure_safe(sql: str) -> str:
    """校验并返回规整后的 SQL；不安全则抛 UnsafeSQLError。"""
    sql = sql.strip().rstrip(";").strip()
    if not sql:
        raise UnsafeSQLError("空 SQL")

    try:
        statements = [s for s in sqlglot.parse(sql) if s is not None]
    except Exception as e:  # 解析失败 = 无法判定安全 → 当作不安全拦下
        raise UnsafeSQLError(f"SQL 解析失败: {e}")

    if len(statements) != 1:                       # 多语句注入：SELECT 1; DROP TABLE t
        raise UnsafeSQLError("只允许执行单条语句")

    stmt = statements[0]
    if not isinstance(stmt, _ALLOWED_TOP):         # 顶层必须是查询
        raise UnsafeSQLError("只允许 SELECT 查询")

    bad = next(stmt.find_all(*_FORBIDDEN), None)    # 遍历整棵 AST，藏在子查询/CTE 里的写操作也拦
    if bad is not None:
        raise UnsafeSQLError(f"检测到禁止的语句类型: {type(bad).__name__}")

    return sql


def with_limit(sql: str, default_limit: int = 200) -> str:
    """没有 LIMIT 时兜底加上，防止全表扫描。"""
    if "LIMIT" not in sql.upper():
        sql = f"{sql}\nLIMIT {default_limit}"
    return sql
