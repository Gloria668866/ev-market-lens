"""pytest 公共配置：把项目根与 data/ 加入 sys.path，离线跑模型。"""
import os
import sys
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "data")):
    if p not in sys.path:
        sys.path.insert(0, p)
os.environ.setdefault("HF_HUB_OFFLINE", "1")

# 测试必须与开发/演示 app.db 彻底隔离。此前每次集成测试都会永久创建数十个
# prod_test_/task_owner_ 账号，管理员后台很快被测试垃圾淹没。
_TEST_APP_DB = Path(ROOT) / ".tmp" / f"pytest-app-{os.getpid()}.db"
_TEST_APP_DB.parent.mkdir(parents=True, exist_ok=True)
os.environ["APP_DATABASE_URL"] = f"sqlite:///{_TEST_APP_DB.as_posix()}"


def pytest_sessionstart(session):
    from app.database import SessionLocal, init_db
    from app.auth import bootstrap_admin

    init_db()
    with SessionLocal() as db:
        bootstrap_admin(db)


def pytest_sessionfinish(session, exitstatus):
    database = sys.modules.get("app.database")
    if database is not None:
        database.app_engine.dispose()
    for path in (
        _TEST_APP_DB,
        Path(str(_TEST_APP_DB) + "-wal"),
        Path(str(_TEST_APP_DB) + "-shm"),
    ):
        path.unlink(missing_ok=True)
