"""数据质量门禁单测（依赖 bi_demo.db 满载数据）：GE 等价 expectations 套件须全通过。

跳过条件：bi_demo.db 行数少于 5000（说明是 seed/demo 库，非满载生产数据），
避免「数据没跑进来」误报成「代码有问题」。
"""
import os
import sqlite3
import pytest

pytestmark = pytest.mark.integration   # 需 bi_demo.db，CI 默认跳过


def _fact_count():
    """返回 fact_sales_rank 当前行数，数据库不存在时返回 0。"""
    db = os.path.join(os.path.dirname(os.path.dirname(__file__)), "bi_demo.db")
    if not os.path.exists(db):
        return 0
    try:
        conn = sqlite3.connect(db)
        n = conn.execute("SELECT COUNT(*) FROM fact_sales_rank").fetchone()[0]
        conn.close()
        return n
    except Exception:
        return 0


@pytest.mark.skipif(
    _fact_count() < 5000,
    reason=f"bi_demo.db 仅有 {_fact_count()} 行（< 5000），非满载数据库，跳过质量门禁。"
           "请先运行 data/crawl_sales.py + data/clean_load.py 填入完整数据。",
)
def test_all_expectations_pass():
    from eval.data_quality import run
    results = run()
    failed = [r["expectation"] for r in results if not r["success"]]
    assert not failed, f"数据质量未通过：{failed}"
