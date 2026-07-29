"""只读数据库连接 + schema introspection。
生产请用只读账号连接；本地 SQLite 默认即可。"""
import time
from functools import lru_cache

from sqlalchemy import create_engine, text, inspect
from .config import (
    DATABASE_URL,
    SCHEMA_CACHE_TTL_SECONDS,
    SQL_STATEMENT_TIMEOUT_MS,
)

_engine_options = {"future": True}
if DATABASE_URL.startswith("postgresql"):
    _engine_options["connect_args"] = {
        "options": (
            f"-c statement_timeout={max(SQL_STATEMENT_TIMEOUT_MS, 1000)} "
            "-c default_transaction_read_only=on"
        )
    }
engine = create_engine(DATABASE_URL, **_engine_options)


def run_query(sql: str, limit: int = 200):
    """执行只读查询，返回 (列名, 行列表)。已在 sql_guard 校验后调用。"""
    with engine.connect() as conn:
        result = conn.execute(text(sql))
        cols = list(result.keys())
        rows = [dict(zip(cols, r)) for r in result.fetchmany(limit)]
    return cols, rows


def _schema_cache_bucket() -> int:
    return int(time.monotonic() // SCHEMA_CACHE_TTL_SECONDS)


@lru_cache(maxsize=2)
def _load_schema_snapshot(
    _bucket: int,
) -> tuple[str, tuple[tuple[str, tuple[str, ...]], ...]]:
    """Inspect once and cache an immutable schema snapshot for one TTL bucket."""
    insp = inspect(engine)
    lines = []
    metadata = []
    for tbl in sorted(insp.get_table_names()):
        cols = insp.get_columns(tbl)
        col_str = ", ".join(f"{c['name']} {str(c['type'])}" for c in cols)
        lines.append(f"TABLE {tbl}({col_str})")
        metadata.append((tbl, tuple(str(c["name"]) for c in cols)))
    return "\n".join(lines), tuple(metadata)


def get_schema_snapshot() -> tuple[str, dict[str, list[str]]]:
    """Return schema text and table metadata from the same introspection pass."""
    schema_text, immutable_meta = _load_schema_snapshot(_schema_cache_bucket())
    # Callers may filter the metadata; never expose the cached object itself.
    return schema_text, {table: list(columns) for table, columns in immutable_meta}


def clear_schema_cache() -> None:
    """Explicit invalidation hook for migrations/tests in this process."""
    _load_schema_snapshot.cache_clear()


def get_schema_text() -> str:
    """把库结构导出成文本，喂给 LLM 做 Text2SQL。
    小库直接全量；大库应在 schema_linking 里先做相关性筛选。"""
    schema_text, _ = get_schema_snapshot()
    return schema_text


def get_tables_meta():
    """返回 {表名: [列名...]}，供 schema_linking 使用。"""
    _, metadata = get_schema_snapshot()
    return metadata
