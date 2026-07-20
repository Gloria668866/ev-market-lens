# T14 本地「生产同款」基础设施（docker-compose）

- 负责人：运维
- 日期：2026-05-25
- 关联工单：T14（部署）
- 状态：已完成（2026-05-25 本机装好 Docker 后现场跑通验证，DoD 四条全过）

## 1. 做了什么

用一份 `deploy/docker-compose.dev.yml` 在本地一条命令拉起三件「生产同款」基础设施，给后端联调用：

- **PostgreSQL 16 + pgvector**：建两个库 —— `bi`（分析库，只读脑 Text2SQL 查 `dim_*/fact_*`）和 `app`（应用库，读写：用户/会话/消息/知识库 + 带向量的 `kb_chunk`）。
- **MinIO**：S3 兼容对象存储，存「上传/爬取的原始文档」，自动建好两个桶。
- **Redis**：给 Celery 队列和缓存用，带密码。

涉及文件：

| 文件 | 作用 |
|---|---|
| `deploy/docker-compose.dev.yml` | 三个服务 + 一个建桶一次性容器，全部带 healthcheck |
| `deploy/postgres/initdb/00-init.sh` | PG 首次启动自动跑：建库/建角色/装 pgvector/建表/授权 |
| `deploy/postgres/initdb/sql/10-bi-analysis.sql` | 分析库 `dim_*/fact_*` 建表（源自 `sql/schema.sql`） |
| `deploy/postgres/initdb/sql/30-app-schema.sql` | 应用库 `users/conversation/message/kb_document + kb_chunk` 建表 |
| `.env.example` | 补全 PG/MinIO/Redis 连接串 + infra 容器参数 + SQLite↔PG 切换说明 |
| `.gitattributes` | 强制 `*.sh` / 初始化 SQL 用 LF 行尾（防 Windows CRLF 把容器脚本跑挂） |
| `requirements.txt` | 加 `psycopg[binary]`（PG 驱动，切 PG 才用得上） |

## 2. 为什么这么做

- **为什么两个库 + 只读角色？** 架构上 Text2SQL 只该「查」分析库、绝不该「写」。生产同款就是：分析库 `bi` 给一个**只读角色** `bi_readonly`，应用库 `app` 给**读写角色** `app_rw`，物理隔离把「LLM 生成的 SQL 误写库」这条风险从根上掐掉。对应后端 `.env` 的两个变量：`DATABASE_URL`（只读）和 `APP_DATABASE_URL`（读写）。
- **为什么用 `pgvector/pgvector:pg16` 镜像？** 它＝官方 postgres:16 预装 pgvector 扩展，省得自己编译；`CREATE EXTENSION vector` 直接可用，给 `kb_chunk.embedding vector(1024)`（BGE-large-zh）和 HNSW 向量索引用。
- **应用库为什么不直接套 `sql/schema_app.sql`？**（关键决策）当前后端 `app/models.py`（真正在跑的 ORM）用的是 `users.id / conversation.id / message.conversation_id` 这套**主键叫 `id`** 的命名；而 `sql/schema_app.sql` 是设计稿，用的是 `user_id / conv_id / msg_id / doc_id`。**两套列名不一样**，要是按 schema_app.sql 建表，后端一查 `users.id` 就报「列不存在」，联调直接挂。所以 `30-app-schema.sql` 的四张业务表**对齐 `app/models.py`**，只把 schema_app.sql 里的 `kb_chunk`（父子分块 + 向量，RAG 用）取过来，外键改指 `kb_document(id)`。`kb_document` 还额外补了几列 RAG 元数据（`file_type/source_uri/title/...`，nullable），后端 ORM 不读写它们、互不影响，留给后续 MinerU 入库用。
- **为什么一份 `.env`？** 后端连容器（连接串）和 compose 拉容器（密码/端口）共用一份 `.env`（仓库里只留 `.env.example` 占位，真 `.env` 已 gitignore）。compose 用 `--env-file ../.env` 读它。密钥绝不进仓库。
- **被否方案**：Hadoop（5 人团队过度设计，见 PROJECT-MEMORY/02）；把分析库和应用库塞一个库（破坏只读隔离）。

## 3. 怎么运行 / 怎么验证

> 前置：装好 Docker Desktop（WSL2 后端）。首次准备：把 `.env.example` 复制成根目录 `.env` 并改掉所有 `change_me` 占位密码（`.env` 已 gitignore）。

```bash
# 在 deploy/ 目录下，读取仓库根的 .env
cd deploy
docker compose --env-file ../.env -f docker-compose.dev.yml up -d

# 看状态：postgres / minio / redis 应为 healthy，minio-init 应 exited(0)
docker compose --env-file ../.env -f docker-compose.dev.yml ps

# ① 验 pgvector 可用 + 两库存在
docker exec carmirror-postgres psql -U postgres -d app  -c "SELECT extversion FROM pg_extension WHERE extname='vector';"
docker exec carmirror-postgres psql -U postgres -d bi   -c "SELECT extversion FROM pg_extension WHERE extname='vector';"

# ② 验两份 schema 建表成功
docker exec carmirror-postgres psql -U postgres -d bi  -c "\dt"   # dim_brand/dim_series/dim_date/fact_sales_rank/fact_price/fact_review
docker exec carmirror-postgres psql -U postgres -d app -c "\dt"   # users/conversation/message/kb_document/kb_chunk

# ③ 验只读角色连得上 bi（用连接串）
docker exec carmirror-postgres psql "postgresql://bi_readonly:<密码>@localhost:5432/bi" -c "SELECT count(*) FROM dim_brand;"
# ④ 验读写角色连得上 app
docker exec carmirror-postgres psql "postgresql://app_rw:<密码>@localhost:5432/app" -c "\dt"

# ⑤ 验 Redis
docker exec carmirror-redis redis-cli -a "<REDIS_PASSWORD>" ping   # → PONG

# ⑥ 验 MinIO 控制台：浏览器开 http://localhost:9001 ，用 MINIO_ROOT_USER/PASSWORD 登录，能看到 kb-uploads / crawl-raw 两个桶
```

**预期结果**：`up` 后三个长驻服务 `healthy`、`minio-init` 退出码 0；①返回 `0.x.x`（pgvector 版本号）；②两库表齐；③④只读/读写角色用连接串都能连；⑤返回 `PONG`；⑥控制台能登录并看到两个桶。

**实测结果（2026-05-25，本机 Windows 11 Pro + WSL2 + Docker 29.4.3）**：

```
$ docker compose --env-file ../.env -f docker-compose.dev.yml ps -a
postgres     Up (healthy)
minio        Up (healthy)
redis        Up (healthy)
minio-init   Exited (0)          # 建桶成功后退出

pgvector：bi=0.8.2  app=0.8.2                       ✅
bi  库表：dim_brand/dim_date/dim_series/fact_price/fact_review/fact_sales_rank（6）  ✅
app 库表：users/conversation/message/kb_document/kb_chunk（5）                       ✅
只读角色 bi_readonly 连 bi：可 SELECT，CREATE TABLE 被拒（permission denied）         ✅ 隔离生效
读写角色 app_rw      连 app：可建表可写                                              ✅
向量索引 idx_kbchunk_vec（HNSW）：存在                                              ✅
Redis：PONG                                                                         ✅
MinIO：mc ls 列出 kb-uploads / crawl-raw 两桶；控制台 http://localhost:9001 可登录   ✅
```

## 4. 输入 → 输出

- **输入**：`.env`（密码/端口/库名）+ 两份建表 SQL。
- **输出**：本机 `localhost` 上可连的
  - PG：`postgresql+psycopg://bi_readonly:***@localhost:5432/bi`（只读）、`postgresql+psycopg://app_rw:***@localhost:5432/app`（读写）
  - MinIO：S3 端点 `localhost:9000`、控制台 `localhost:9001`、桶 `kb-uploads`/`crawl-raw`
  - Redis：`redis://:***@localhost:6379/0`
- **后端切过去**：把根 `.env` 的 `DATABASE_URL`/`APP_DATABASE_URL` 从 SQLite 改成上面两条 PG 串，重启后端即可（代码零改动，`app/config.py` 只读这两个变量）。

## 5. 关键实现说明

- **初始化只在「数据卷为空的首次启动」跑一次**：PG 官方镜像的 `docker-entrypoint-initdb.d` 机制。`00-init.sh` 在默认库里建角色、建 `bi`/`app` 两库，再分别 `psql -d bi/-d app` 显式载入子目录 `sql/` 下的建表脚本（子目录文件不会被入口自动执行，避免重复跑或跑错库）。
- **healthcheck**：`postgres` 用 `pg_isready`；`redis` 用 `redis-cli -a $REDIS_PASSWORD ping`；`minio` 打 `/minio/health/live`。`minio-init`（建桶）用 `depends_on: condition: service_healthy` 等 MinIO 健康后再跑，建完即退出。
- **行尾陷阱**：容器里执行的 `00-init.sh` 必须是 LF 行尾，否则 Linux 报 `/bin/bash^M: bad interpreter`。已加 `.gitattributes` 钉死 `*.sh eol=lf`。

## 6. 架构图

```mermaid
flowchart TB
  subgraph dev["开发者本机 (docker compose up)"]
    subgraph pg["PostgreSQL 16 + pgvector :5432"]
      bi[("分析库 bi<br/>dim_* / fact_*<br/>只读角色 bi_readonly")]
      app[("应用库 app<br/>users/conversation/message<br/>kb_document + kb_chunk(vector)<br/>读写角色 app_rw")]
    end
    minio[("MinIO :9000 API / :9001 控制台<br/>桶: kb-uploads / crawl-raw")]
    redis[("Redis :6379<br/>队列 + 缓存")]
  end

  be["后端 FastAPI"] -- "DATABASE_URL (只读)" --> bi
  be -- "APP_DATABASE_URL (读写)" --> app
  be -- "上传/爬取原始文档" --> minio
  be -- "Celery 队列 / 缓存" --> redis

  env[".env (gitignore)<br/>密码/端口/连接串"] -. "--env-file" .-> pg
  env -. "--env-file" .-> minio
  env -. "--env-file" .-> redis
```

```mermaid
flowchart LR
  up["compose up<br/>(数据卷为空)"] --> init["00-init.sh"]
  init --> r["建角色<br/>app_rw / bi_readonly"]
  init --> dbs["建库 bi / app"]
  dbs --> ext["两库 CREATE EXTENSION vector"]
  ext --> t1["bi 载入 10-bi-analysis.sql"]
  ext --> t2["app 载入 30-app-schema.sql"]
  t1 --> g1["授 bi_readonly 只读"]
  t2 --> g2["授 app_rw 读写"]
```

## 7. 踩过的坑

- 本机**没装 Docker Desktop / WSL2**（`docker` 命令不存在，`wsl -l` 报未安装）→ 装 WSL2 + Docker Desktop（需管理员 + 重启），装好再 `up` 验证。
- **`wsl --install` 报 403（已禁止）**：默认走微软商店 / `aka.ms` 跳转被网络挡（CN 网络常见）。解法：`github.com` 网页可直连（只有 `api.github.com` 被限流），从 [WSL releases](https://github.com/microsoft/WSL/releases) 直下 `wsl.2.7.3.0.x64.msi`（243 MB）→ 管理员 `msiexec /i ... /qn` → `dism` 开 `VirtualMachinePlatform`+`Microsoft-Windows-Subsystem-Linux` → 重启即可。专业版亦可改用 Hyper-V 后端（DISM 开 Hyper-V，不联网）绕过 WSL 下载。
- `.env` 由 `.env.example` 生成时**值行别留行内注释**：docker compose 读 `--env-file` 会把「`# 注释`」连空格当成值（密码/桶名出错）。已把 `.env.example` 所有注释改为单独成行。
- 行尾：Windows 上 `.sh` 容易被 git 转成 CRLF → 容器内 `bad interpreter`。已用 `.gitattributes` 钉 LF。
- `sql/schema_app.sql` 列名（user_id/conv_id/...）与后端 `app/models.py`（id/conversation_id）**不一致**：应用库按后端实际 ORM 建表，否则联调全报错（详见第 2 节）。
- MinIO `healthcheck` 用 `curl /minio/health/live`：**2026-05-25 实测 `minio/minio:latest` 自带 curl，healthcheck 正常变 healthy**、minio-init 顺利建桶。若将来换的镜像基础层不带 curl 再改探活方式。
- `MINIO_ROOT_PASSWORD` 必须 ≥ 8 位，否则 MinIO 拒绝启动。

## 8. 待办 / 遗留

- [x] **本机装 Docker 后现场跑通验证**（2026-05-25，DoD 四条全过，实测见第 3 节）。
- [x] 确认 minio 的 curl healthcheck 在所用镜像可用（`minio/minio:latest` 自带 curl，OK）。
- [ ] 把 PG/MinIO/Redis 连接串同步给后端，确认后端把 `.env` 的 `DATABASE_URL`/`APP_DATABASE_URL` 切到 PG 后整链路仍跑通。
- [ ] 生产：镜像钉具体版本（别用 `:latest`）、给应用单独建受限 MinIO access key、PG 角色密码走密管、容器只绑 `127.0.0.1`。
