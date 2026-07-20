"""Celery 应用：RAG 解析/切块/向量化(worker) + 定时增量采集(beat)。

启动（生产 docker-compose 各起一个）：
  worker: celery -A app.celery_app.celery worker --concurrency=2 -l info
  beat:   celery -A app.celery_app.celery beat -l info
（Windows 本地 worker 用 --pool=solo 避免 fork 问题）
"""
from celery import Celery
from celery.schedules import crontab

from .config import CELERY_BROKER_URL, CELERY_RESULT_BACKEND

celery = Celery("carmirror", broker=CELERY_BROKER_URL, backend=CELERY_RESULT_BACKEND)
celery.conf.update(
    task_track_started=True,
    task_ignore_result=True,        # 入库任务 fire-and-forget：状态走 kb_document.status，不依赖 celery 结果
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    broker_connection_retry_on_startup=True,
)

# Beat 定时表：每月 1 号 03:00 增量采集销量并加载进 PG（历史月幂等跳过、刷最近月）
celery.conf.beat_schedule = {
    "monthly-sales-refresh": {
        "task": "cron.monthly_sales_refresh",
        "schedule": crontab(day_of_month=1, hour=3, minute=0),
    },
}

# 注册任务模块
import app.rag.tasks           # noqa: E402,F401  RAG 入库任务
import app.tasks_cron          # noqa: E402,F401  定时采集任务
import app.agent_pipeline      # noqa: E402,F401  oh-my-openagent pipeline tasks
