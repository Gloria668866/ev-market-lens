"""月度刷新任务必须调用可编程CLI入口，且先采集再加载。"""


def test_monthly_refresh_calls_crawler_with_empty_argv_then_loader(monkeypatch):
    import data.crawl_sales as crawl_sales
    import deploy.load_analysis_pg as load_analysis_pg
    from app.tasks_cron import monthly_sales_refresh

    calls = []
    monkeypatch.setattr(crawl_sales, "main", lambda argv=None: calls.append(("crawl", argv)))
    monkeypatch.setattr(load_analysis_pg, "main", lambda: calls.append(("load", None)))

    assert monthly_sales_refresh.run() == "refreshed"
    assert calls == [("crawl", []), ("load", None)]
    assert monthly_sales_refresh.max_retries == 3


def test_sales_refresh_waits_for_source_publication_window():
    from app.celery_app import celery

    schedule = celery.conf.beat_schedule["monthly-sales-refresh"]["schedule"]
    assert schedule.day_of_month == {8, 15}
    assert schedule.hour == {3}
    assert schedule.minute == {0}
