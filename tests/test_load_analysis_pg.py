"""生产分析库加载器的纯单测：导入契约、清洗口径与快照幂等。"""
import json


def _sales_row(*, count, crawl_time):
    return {
        "_month": "202501",
        "_new_energy_type": 1,
        "_crawl_time": crawl_time,
        "series_id": 101,
        "series_name": "测试车",
        "brand_id": 10,
        "brand_name": "测试品牌",
        "rank": 1,
        "last_rank": 2,
        "count": count,
        "min_price": 10.0,
        "max_price": 12.0,
        "price": "10-12万",
        "dealer_price": "9-11万",
        "has_dealer_price": True,
        "descender_price": 1.0,
        "car_review_count": 20,
    }


def test_loader_imports_and_build_dedupes_raw_rows(tmp_path):
    from deploy import load_analysis_pg as loader

    raw_file = tmp_path / "sales.jsonl"
    raw_file.write_text(
        "\n".join(
            json.dumps(row, ensure_ascii=False)
            for row in (
                _sales_row(count=10, crawl_time="2026-01-01T00:00:00+00:00"),
                _sales_row(count=20, crawl_time="2026-01-02T00:00:00+00:00"),
            )
        )
        + "\n",
        encoding="utf-8",
    )

    db, ds, dd, sales, prices, reviews = loader.build(raw_file=raw_file, koubei={})

    assert list(db) == [10]
    assert ds[101][5] == "纯电"
    assert list(dd) == [202501]
    assert len(sales) == len(prices) == len(reviews) == 1
    assert sales[0][6] == 20
    assert prices[0][6] == "9-11万"


def test_build_rejects_empty_or_all_invalid_sales_snapshot(tmp_path):
    from deploy import load_analysis_pg as loader
    import pytest

    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="原始快照为空"):
        loader.build(raw_file=empty, koubei={})

    invalid = tmp_path / "invalid.jsonl"
    invalid.write_text(
        json.dumps(_sales_row(count=0, crawl_time="2026-01-01T00:00:00+00:00"))
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="销量事实仅 0 行"):
        loader.build(raw_file=invalid, koubei={})


class _RecordingCursor:
    def __init__(self):
        self.calls = []

    def executemany(self, sql, params):
        self.calls.append((sql, list(params)))

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        return self


def test_replace_snapshot_rows_deletes_key_then_inserts_latest():
    from deploy import load_analysis_pg as loader

    cursor = _RecordingCursor()
    older = (101, 202501, "2025-01-01", 10.0)
    newer = (101, 202501, "2025-01-01", 11.0)

    loader.replace_snapshot_rows(
        cursor,
        table="fact_price",
        columns=("series_id", "date_id", "snapshot_date", "guide_price_min"),
        rows=[older, newer],
    )

    delete_sql, delete_params = cursor.calls[0]
    insert_sql, insert_params = cursor.calls[1]
    assert delete_sql == "DELETE FROM fact_price WHERE series_id=%s AND date_id=%s"
    assert delete_params == [(101, 202501)]
    assert insert_sql.startswith("INSERT INTO fact_price(")
    assert insert_params == [newer]


class _RecordingConnection:
    def __init__(self):
        self.cursor_instance = _RecordingCursor()
        self.committed = False

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.committed = True


def test_load_connection_replaces_all_fact_tables_before_insert(tmp_path):
    from deploy import load_analysis_pg as loader

    raw_file = tmp_path / "sales.jsonl"
    raw_file.write_text(
        json.dumps(_sales_row(count=20, crawl_time="2026-01-02T00:00:00+00:00"))
        + "\n",
        encoding="utf-8",
    )
    connection = _RecordingConnection()
    loader.load_connection(connection, loader.build(raw_file=raw_file, koubei={}))

    statements = [sql for sql, _ in connection.cursor_instance.calls]
    for table in ("fact_sales_rank", "fact_price", "fact_review"):
        assert f"DELETE FROM {table}" in statements
    assert connection.committed is True


def test_load_connection_rejects_empty_payload_before_delete():
    from deploy import load_analysis_pg as loader
    import pytest

    connection = _RecordingConnection()
    with pytest.raises(ValueError, match="销量事实仅 0 行"):
        loader.load_connection(connection, ({}, {}, {}, [], [], []))

    assert connection.cursor_instance.calls == []
    assert connection.committed is False
