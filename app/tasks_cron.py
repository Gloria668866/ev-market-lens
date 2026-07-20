"""Celery Beat 定时任务（生产）：月度增量采集 + 加载进 PG 分析库。

为什么定时：销量榜每月更新，crawl_sales 自带增量（只补新月+刷最近月，幂等）；
采完再 load 进 PG bi，Text2SQL 就一直查到最新数据。beat 触发、worker 执行。
"""
from app.celery_app import celery


@celery.task(name="cron.monthly_sales_refresh", bind=True, max_retries=1)
def monthly_sales_refresh(self):
    """① 增量采集销量榜（刷新 data/raw）② 清洗加载进 PG 分析库 bi。"""
    from data.crawl_sales import main as crawl_main
    crawl_main()
    from deploy.load_analysis_pg import main as load_main
    load_main()
    return "refreshed"
