#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Celery + Beat 定时调度示例：每月自动跑一次增量采集。
生产部署在服务器上（Docker 里）随应用一起跑。

启动（两个进程）：
  celery -A celery_app worker --loglevel=info        # 干活的 worker
  celery -A celery_app beat   --loglevel=info        # 定时触发器（Beat）

依赖：pip install celery redis ；需要 Redis 在跑。
"""
from celery import Celery
from celery.schedules import crontab

# broker/backend 用 Redis（与项目其它队列共用）
app = Celery("cheshijing", broker="redis://localhost:6379/0",
             backend="redis://localhost:6379/1")
app.conf.timezone = "Asia/Shanghai"
app.conf.enable_utc = False


@app.task(name="crawl.sales_incremental")
def crawl_sales_incremental():
    """调用增量采集。crawl_sales.py 的 main() 自带增量逻辑：
    只补新月 + 刷最近月，跑多少次都幂等，不会重复或脏。"""
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    from data.crawl_sales import main
    main()
    return "ok"


# 定时表：每月 1 号 03:00 跑一次增量采集
app.conf.beat_schedule = {
    "monthly-sales-crawl": {
        "task": "crawl.sales_incremental",
        "schedule": crontab(day_of_month=1, hour=3, minute=0),
    },
    # 如想更勤，可改成每周一刷新（最近月数据更及时）：
    # "weekly-sales-refresh": {
    #     "task": "crawl.sales_incremental",
    #     "schedule": crontab(day_of_week=1, hour=3, minute=0),
    # },
}
