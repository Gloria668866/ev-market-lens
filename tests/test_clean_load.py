"""清洗纯函数单测（T4 关键路径）：价格/月份/排名/续航/评分/文本规整。"""
import json
import sqlite3

import pytest

cl = pytest.importorskip("clean_load")  # data/clean_load.py（conftest 已把 data/ 加入 path）


def test_parse_price_range():
    assert cl.parse_price_range("5.98-8.98万") == (5.98, 8.98)
    assert cl.parse_price_range("7.99万") == (7.99, 7.99)   # 单值 min==max
    assert cl.parse_price_range("暂无报价") == (None, None)
    assert cl.parse_price_range(None) == (None, None)


def test_parse_month():
    assert cl.parse_month("202503") == (202503, 2025, 3, 1, "2025-03")
    assert cl.parse_month("202512")[3] == 4   # quarter
    assert cl.parse_month("202601")[1] == 2026


def test_clean_rank_new_entry():
    assert cl.clean_rank(0) == (None, True)
    assert cl.clean_rank(None) == (None, True)
    assert cl.clean_rank(5) == (5, False)


def test_parse_endurance():
    assert cl.parse_endurance("593-821km") == 821   # 区间取上限
    assert cl.parse_endurance("500km") == 500
    assert cl.parse_endurance("-") is None


def test_norm_score():
    assert cl.norm_score(404) == 4.0   # ×100 还原
    assert cl.norm_score(0) is None
    assert cl.norm_score(None) is None


def test_norm_text():
    assert cl.norm_text("  x ") == "x"
    assert cl.norm_text("   ") is None


def test_run_replaces_stale_fact_rows(tmp_path, monkeypatch):
    raw = tmp_path / "sales.jsonl"
    db = tmp_path / "bi.db"
    base = {
        "_month": "202606",
        "_new_energy_type": 1,
        "brand_id": 1,
        "brand_name": "测试品牌",
        "price": "10-20万",
        "min_price": 10,
        "max_price": 20,
        "rank": 1,
        "last_rank": 2,
        "count": 100,
    }
    rows = [
        {**base, "series_id": 11, "series_name": "车型A"},
        {**base, "series_id": 12, "series_name": "车型B", "rank": 2},
    ]
    raw.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows),
        encoding="utf-8",
    )
    monkeypatch.setattr(cl, "RAW_FILE", raw)
    monkeypatch.setattr(cl, "DB_FILE", db)
    monkeypatch.setattr(cl, "load_koubei", lambda: {})

    cl.run()
    raw.write_text(json.dumps(rows[0], ensure_ascii=False) + "\n", encoding="utf-8")
    cl.run()

    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM fact_sales_rank").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM fact_price").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM fact_review").fetchone()[0] == 1
