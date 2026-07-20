"""应用层读写库连接（用户/会话/知识库）。

与 app/db.py 区分：
- app/db.py     = 只读分析库（DATABASE_URL），供 Text2SQL 查 dim_*/fact_*，不写入。
- app/database.py = 读写应用库（APP_DATABASE_URL），存用户/会话/消息/知识库元数据。
"""
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, Session

from .config import APP_DATABASE_URL
from .models import Base

# SQLite 在多线程（uvicorn）下需要关掉 same-thread 检查；其它库无需此参数
_connect_args = {"check_same_thread": False} if APP_DATABASE_URL.startswith("sqlite") else {}
app_engine = create_engine(APP_DATABASE_URL, future=True, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=app_engine, autoflush=False, expire_on_commit=False, future=True)


def _migrate() -> None:
    """轻量幂等迁移：给已存在的 users 表补 role/disabled 列（create_all 不会改已存在的表）。
    SQLite 与 PostgreSQL 均适用；列已存在则跳过。"""
    insp = inspect(app_engine)
    if "users" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("users")}
    is_pg = app_engine.dialect.name == "postgresql"
    stmts = []
    if "role" not in cols:
        stmts.append("ALTER TABLE users ADD COLUMN role VARCHAR(16) DEFAULT 'user'")
    if "disabled" not in cols:
        stmts.append("ALTER TABLE users ADD COLUMN disabled BOOLEAN DEFAULT " + ("FALSE" if is_pg else "0"))
    if "token_version" not in cols:
        stmts.append("ALTER TABLE users ADD COLUMN token_version INTEGER DEFAULT 0")
    if stmts:
        with app_engine.begin() as conn:
            for s in stmts:
                conn.execute(text(s))


def init_db() -> None:
    """建表（幂等）+ 轻量迁移。生产用 schema.sql / 迁移工具时可不调用。"""
    Base.metadata.create_all(app_engine)
    _migrate()


def get_db():
    """FastAPI 依赖：每请求一个会话，结束自动关闭。"""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
