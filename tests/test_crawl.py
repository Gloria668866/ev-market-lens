"""采集纯函数单测（T3 关键路径）：动态月份、增量刷新与幂等落盘。"""
import json
from datetime import date, datetime, timezone

import pytest

cs = pytest.importorskip("crawl_sales")  # data/crawl_sales.py


def test_month_range_cross_year():
    assert cs.month_range("202411", "202502") == ["202411", "202412", "202501", "202502"]


def test_month_range_single():
    assert cs.month_range("202501", "202501") == ["202501"]


def test_previous_complete_month_is_dynamic():
    assert cs.previous_complete_month(date(2026, 7, 27)) == "202606"
    assert cs.previous_complete_month(date(2026, 1, 1)) == "202512"


def test_market_date_uses_shanghai_timezone_at_month_boundary():
    instant = datetime(2026, 6, 30, 19, 0, tzinfo=timezone.utc)
    assert cs.market_date(instant) == date(2026, 7, 1)
    assert cs.previous_complete_month(cs.market_date(instant)) == "202606"


def test_plan_batches_fills_missing_partitions_and_refreshes_latest_two():
    existing = [
        {"_month": month, "_new_energy_type": energy_type, "series_id": 1}
        for month in ("202601", "202602", "202603")
        for energy_type in (1, 2, 3)
        if not (month == "202601" and energy_type == 3)
    ]

    assert cs.plan_batches(
        existing,
        "202601",
        "202603",
        energy_types=(1, 2, 3),
        refresh_months=2,
    ) == [
        ("202601", 3),
        ("202602", 1),
        ("202602", 2),
        ("202602", 3),
        ("202603", 1),
        ("202603", 2),
        ("202603", 3),
    ]


def test_run_refreshes_partitions_dedupes_and_atomically_replaces(tmp_path):
    out_file = tmp_path / "sales_rank_raw.jsonl"
    existing = [
        {"_month": "202501", "_new_energy_type": 1, "series_id": 1, "count": 1},
        {"_month": "202501", "_new_energy_type": 1, "series_id": 1, "count": 2},
        {"_month": "202502", "_new_energy_type": 1, "series_id": 1, "count": 3},
        {"_month": "202503", "_new_energy_type": 1, "series_id": 1, "count": 4},
    ]
    out_file.write_text(
        "\n".join(json.dumps(row) for row in existing) + "\n",
        encoding="utf-8",
    )
    calls = []

    def fake_fetch(month, energy_type):
        calls.append((month, energy_type))
        if month == "202502":
            return [
                {"_month": month, "_new_energy_type": energy_type, "series_id": 1, "count": 20},
                {"_month": month, "_new_energy_type": energy_type, "series_id": 1, "count": 21},
                {"_month": month, "_new_energy_type": energy_type, "series_id": 2, "count": 8},
            ]
        return [
            {"_month": month, "_new_energy_type": energy_type, "series_id": 1, "count": 30}
        ]

    summary = cs.run(
        "202501",
        "202503",
        out_file=out_file,
        fetcher=fake_fetch,
        energy_types=(1,),
        refresh_months=2,
    )

    rows = [json.loads(line) for line in out_file.read_text(encoding="utf-8").splitlines()]
    assert calls == [("202502", 1), ("202503", 1)]
    assert [(row["_month"], row["series_id"], row["count"]) for row in rows] == [
        ("202501", 1, 2),
        ("202502", 1, 21),
        ("202502", 2, 8),
        ("202503", 1, 30),
    ]
    assert summary["total_rows"] == 4
    assert list(tmp_path.glob(".sales_rank_raw.jsonl.*.tmp")) == []


def test_main_accepts_explicit_argv(monkeypatch):
    captured = {}

    def fake_run(start, end, **kwargs):
        captured.update(start=start, end=end)
        return {"ok": True}

    monkeypatch.setattr(cs, "run", fake_run)
    assert cs.main(["--start", "202501", "--end", "202502"]) == {"ok": True}
    assert captured == {"start": "202501", "end": "202502"}


def test_standard_library_request_has_timeout_and_finite_retries():
    attempts = []
    sleeps = []

    class Response:
        def read(self):
            return b'{"data":{"list":[]}}'

        def close(self):
            pass

    def opener(request, timeout):
        attempts.append((request.full_url, timeout))
        if len(attempts) < 3:
            raise TimeoutError("temporary timeout")
        return Response()

    payload = cs._request_json(
        "https://example.test/rank",
        opener=opener,
        timeout=7,
        retries=3,
        sleep=sleeps.append,
    )

    assert payload == {"data": {"list": []}}
    assert attempts == [
        ("https://example.test/rank", 7),
        ("https://example.test/rank", 7),
        ("https://example.test/rank", 7),
    ]
    assert sleeps == [1.0, 2.0]


def test_latest_published_month_ignores_aggregate_selectors():
    assert cs.latest_published_month({
        "data": {
            "sells_rank_month": [
                {"month": 202606},
                {"month": 202605},
                {"month": 500},
                {"month": 1000},
            ]
        }
    }) == "202606"


def test_fetch_month_rejects_nonempty_silent_fallback():
    class Response:
        def read(self):
            return json.dumps({
                "data": {
                    "sells_rank_month": [{"month": 202606}, {"month": 202605}],
                    "list": [{
                        "series_id": 1,
                        "series_name": "回退数据",
                        "rank": 1,
                        "count": 999,
                    }],
                }
            }).encode()

        def close(self):
            pass

    rows = cs.fetch_month(
        "202607",
        1,
        opener=lambda request, timeout: Response(),
        retries=1,
        sleep=lambda _: None,
        page_delay=0,
    )
    assert rows == []


def test_fetch_month_accepts_historical_month_older_than_selector_window():
    class Response:
        def read(self):
            return json.dumps({
                "data": {
                    "sells_rank_month": [{"month": 202606}, {"month": 202605}],
                    "list": [{
                        "series_id": 1,
                        "series_name": "历史数据",
                        "rank": 1,
                        "count": 123,
                    }],
                }
            }).encode()

        def close(self):
            pass

    rows = cs.fetch_month(
        "202401",
        1,
        opener=lambda request, timeout: Response(),
        retries=1,
        sleep=lambda _: None,
        page_delay=0,
    )
    assert len(rows) == 1
    assert rows[0]["_month"] == "202401"
    assert rows[0]["count"] == 123
