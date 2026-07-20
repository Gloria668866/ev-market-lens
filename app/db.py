"""只读数据库连接 + schema introspection。
生产请用只读账号连接；本地 SQLite 默认即可。"""
from sqlalchemy import create_engine, text, inspect
from .config import DATABASE_URL

engine = create_engine(DATABASE_URL, future=True)


def run_query(sql: str, limit: int = 200):
    """执行只读查询，返回 (列名, 行列表)。已在 sql_guard 校验后调用。"""
    with engine.connect() as conn:
        result = conn.execute(text(sql))
        cols = list(result.keys())
        rows = [dict(zip(cols, r)) for r in result.fetchmany(limit)]
    return cols, rows


def get_schema_text() -> str:
    """把库结构导出成文本，喂给 LLM 做 Text2SQL。
    小库直接全量；大库应在 schema_linking 里先做相关性筛选。"""
    insp = inspect(engine)
    lines = []
    for tbl in insp.get_table_names():
        cols = insp.get_columns(tbl)
        col_str = ", ".join(f"{c['name']} {str(c['type'])}" for c in cols)
        lines.append(f"TABLE {tbl}({col_str})")
    return "\n".join(lines)


def get_tables_meta():
    """返回 {表名: [列名...]}，供 schema_linking 使用。"""
    insp = inspect(engine)
    return {t: [c["name"] for c in insp.get_columns(t)] for t in insp.get_table_names()}
