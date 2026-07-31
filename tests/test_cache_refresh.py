"""Regression tests for database-derived prompt metadata caches."""
from app import db
from app import schema_linking
from app import text2sql


def test_catalog_cache_refreshes_after_ttl(monkeypatch):
    calls = {"brand": 0, "series": 0}
    requested_limits = []
    now = [100.0]

    def fake_query(sql, limit=200):
        requested_limits.append(limit)
        if "brand_name" in sql:
            calls["brand"] += 1
            return ["brand_name"], [{"brand_name": f"品牌{calls['brand']}"}]
        calls["series"] += 1
        return ["series_name"], [{"series_name": f"车系{calls['series']}"}]

    monkeypatch.setattr(text2sql, "run_query", fake_query)
    monkeypatch.setattr(text2sql.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(text2sql, "CATALOG_CACHE_TTL_SECONDS", 10)
    text2sql.clear_catalog_caches()

    assert text2sql._brand_catalog() == ("品牌1",)
    assert text2sql._brand_catalog() == ("品牌1",)
    assert text2sql._series_catalog() == ("车系1",)
    assert text2sql._series_catalog() == ("车系1",)
    assert calls == {"brand": 1, "series": 1}
    assert requested_limits == [5000, 5000]

    now[0] = 111.0
    assert text2sql._brand_catalog() == ("品牌2",)
    assert text2sql._series_catalog() == ("车系2",)
    assert calls == {"brand": 2, "series": 2}

    text2sql.clear_catalog_caches()


def test_schema_snapshot_reuses_one_inspection_and_refreshes(monkeypatch):
    calls = {"inspect": 0}
    now = [200.0]

    class FakeInspector:
        def get_table_names(self):
            return ["fact_sales_rank", "dim_date"]

        def get_columns(self, table):
            return [{"name": "id", "type": "INTEGER"}]

    def fake_inspect(_engine):
        calls["inspect"] += 1
        return FakeInspector()

    monkeypatch.setattr(db, "inspect", fake_inspect)
    monkeypatch.setattr(db.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(db, "SCHEMA_CACHE_TTL_SECONDS", 10)
    db.clear_schema_cache()

    schema_text, metadata = db.get_schema_snapshot()
    assert "TABLE fact_sales_rank(id INTEGER)" in schema_text
    assert metadata["dim_date"] == ["id"]
    assert db.get_schema_text() == schema_text
    assert db.get_tables_meta() == metadata
    assert calls["inspect"] == 1

    now[0] = 211.0
    db.get_schema_snapshot()
    assert calls["inspect"] == 2

    db.clear_schema_cache()


def test_schema_linking_requests_one_snapshot(monkeypatch):
    calls = {"snapshot": 0}

    def fake_snapshot():
        calls["snapshot"] += 1
        return (
            "TABLE dim_date(date_id)\nTABLE fact_sales_rank(volume)",
            {
                "dim_date": ["date_id"],
                "fact_sales_rank": ["volume"],
            },
        )

    monkeypatch.setattr(schema_linking, "get_schema_snapshot", fake_snapshot)
    result = schema_linking.link_schema("2026年销量")
    assert "fact_sales_rank" in result
    assert calls["snapshot"] == 1
