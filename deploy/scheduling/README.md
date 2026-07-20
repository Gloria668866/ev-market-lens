# 定时采集（保持数据常新）

增量逻辑在 `data/crawl_sales.py`：**每跑一次只补新月 + 刷最近 2 个月**，幂等。
配上定时任务，数据就一直是新的。三种挂法，任选其一。

## 方式 A：Celery Beat（推荐，跟项目一起跑在 Docker 里）
见 `celery_app.py`。每月 1 号 03:00 自动触发。
```bash
celery -A celery_app worker --loglevel=info   # 执行
celery -A celery_app beat   --loglevel=info   # 定时触发
```
> 生产用 docker-compose 各起一个 worker / beat 容器；与项目共用 Redis。

## 方式 B：Linux cron（最简单）
`crontab -e` 加一行（用 scrapling 专用 venv 的 python）：
```cron
# 每月 1 号 03:00 跑增量采集
0 3 1 * * cd /app && /app/.venv-scrapling/bin/python data/crawl_sales.py >> /var/log/crawl_sales.log 2>&1
```
cron 五位含义：`分 时 日 月 周`。`0 3 1 * *` = 每月 1 号 3 点 0 分。

## 方式 C：Windows 计划任务（本地 Windows 测试用）
任务计划程序 → 创建任务 → 触发器：每月 → 操作：
```
程序：C:\Users\Lenovo\.claude\skills\scrapling\.venv\Scripts\python.exe
参数：crawl_sales.py
起始于：D:\lgb\t1\bi-agent-starter\data
```
或 PowerShell 一次性注册：
```powershell
$action  = New-ScheduledTaskAction -Execute "C:\Users\Lenovo\.claude\skills\scrapling\.venv\Scripts\python.exe" -Argument "crawl_sales.py" -WorkingDirectory "D:\lgb\t1\bi-agent-starter\data"
$trigger = New-ScheduledTaskTrigger -Monthly -DaysOfMonth 1 -At 3am
Register-ScheduledTask -TaskName "cheshijing-crawl" -Action $action -Trigger $trigger
```

## 为什么这样设计
- 历史月销量是定死的 → 跳过不重爬，省时省流量。
- 当月数据还在更新 → 最近 2 月每次重刷，保证及时。
- 文件按月分区 + 入库 UPSERT → 重复跑安全、可追溯。
