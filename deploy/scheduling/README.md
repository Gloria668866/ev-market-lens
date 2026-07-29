# 定时采集：公开销量数据保持常新

生产调度只有一个事实源：`app/celery_app.py`；任务实现位于
`app/tasks_cron.py`。每月 8 日和 15 日 03:00，Celery Beat 投递
`cron.monthly_sales_refresh`，worker 依次执行：

1. `data/crawl_sales.py` 增量采集懂车帝公开销量 JSON；
2. `deploy/load_analysis_pg.py` 幂等写入 PostgreSQL 分析库。

## 当前增量语义

`data/crawl_sales.py` 的 `main()` 默认覆盖 `202401` 到上一个完整自然月：

- 补齐所有缺失的「月份 × 能源类型」分区；
- 每次强制刷新最近 2 个完整月；
- 读取源站 `sells_rank_month`，请求月份晚于最新已发布月份时拒绝写入，防止
  源站把上月结果静默回退后被错误标成新月；
- 按 `(_month, _new_energy_type, series_id)` 去重；
- 新分区抓取为空时保留旧快照，成功后使用临时文件 + `fsync` + `os.replace`
  原子替换，重复运行不会追加重复记录。

这条销量主链路调用公开 JSON API，使用 Python 标准库 HTTP，不依赖浏览器。
「结构化数据缺失后」Agent 的可选网页采集工具优先使用容器中随镜像安装的
Playwright Chromium，并对每次跳转和浏览器子请求执行公网地址校验；浏览器不可用时
降级到同样执行地址校验的 httpx 链路。

## 生产方式：Celery Beat（推荐）

`deploy/docker-compose.prod.yml` 已分别启动 worker 与 beat，并共用 Redis：

```bash
cd /opt/carmirror
make logs s=beat
make logs s=worker
```

2C8G 演示机在 `.env.prod` 保持：

```dotenv
API_WORKERS=1
CELERY_CONCURRENCY=1
PIPELINE_MAX_PARALLEL=2
```

4C8G 及以上在压测通过后可改为 `2/2`。不要同时再挂一份 cron，否则会产生
重复调度；即使写入是幂等的，也会浪费外部请求和机器资源。

## 首次导入与人工补跑

第一次上线必须先准备真实 `data/raw/sales_rank_raw.jsonl`，再执行
`make load-analysis`。可在开发机采好后把 `data/raw` 用 `scp` 传到服务器，
也可直接在服务器运行：

```bash
cd /opt/carmirror
python3 data/crawl_sales.py
python3 -m venv .venv
.venv/bin/pip install "psycopg[binary]>=3.1"
make load-analysis
```

需要人工补跑时，优先在 worker 容器中触发已注册任务，而不是另建第二套调度：

```bash
cd /opt/carmirror/deploy
docker compose --env-file ../.env.prod -f docker-compose.prod.yml \
  exec worker celery -A app.celery_app.celery call cron.monthly_sales_refresh
```

运行后检查 worker 日志，并用真实 SQL/API 查询确认最新月份已经进入 `bi` 库；
“任务发送成功”本身不等于数据已完成更新。
