# 车市镜 · 生产运维一键命令（在仓库根目录跑 make <目标>）。详见 deploy/DEPLOY.md。
# 约定：密钥在 ./.env.prod（已 gitignore）；compose 文件在 deploy/。
ENV  := --env-file ../.env.prod
FILE := -f docker-compose.prod.yml
DC   := docker compose $(ENV) $(FILE)

.PHONY: help models build up down ps logs load-analysis reindex-embeddings register backup restore migrate-app health

help:               ## 列出所有命令
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n",$$1,$$2}'

models:             ## 下载 BGE+reranker 权重到 ./models（约 2.8GB，跑一次）
	bash deploy/download_models.sh

build:              ## 构建镜像（后端 + 前端）
	cd deploy && $(DC) build

up:                 ## 拉起全栈（后台）
	@mkdir -p data/raw
	cd deploy && $(DC) up -d

down:               ## 停（保留数据卷）
	cd deploy && $(DC) down

ps:                 ## 看服务状态
	cd deploy && $(DC) ps

logs:               ## 跟随日志（make logs s=api）
	cd deploy && $(DC) logs -f $(s)

load-analysis:      ## 把 data/raw 清洗加载进 PG 分析库 bi（当前快照 8402 行 / 后续刷新）
	set -a; . ./.env.prod; set +a; \
	ANALYSIS_PG_URL="postgresql://$$POSTGRES_SUPER_USER:$$POSTGRES_SUPER_PASSWORD@127.0.0.1:5432/$$BI_DB_NAME" \
	  .venv/bin/python deploy/load_analysis_pg.py

migrate-app:        ## 对已有 PG 数据卷执行幂等应用库迁移
	cd deploy && $(DC) run --rm migrate

reindex-embeddings: ## 按当前模型版本重建旧/缺失 RAG 向量
	cd deploy && $(DC) exec api python data/reindex_embeddings.py --backend pg

register:           ## 管理员建受控账号  make register u=alice p=secret n=爱丽丝
	@test -n "$(u)" -a -n "$(p)" || (echo "用法: make register u=alice p=至少6位密码 n=爱丽丝"; exit 2)
	@set -a; . ./.env.prod; set +a; \
	  BASE="https://$$DOMAIN"; \
	  TOKEN=$$(curl -fsS -X POST "$$BASE/api/auth/login" -H 'Content-Type: application/json' \
	    -d "{\"username\":\"$$ADMIN_USERNAME\",\"password\":\"$$ADMIN_PASSWORD\"}" \
	    | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])'); \
	  curl -fsS -X POST "$$BASE/api/admin/users" \
	    -H "Authorization: Bearer $$TOKEN" -H 'Content-Type: application/json' \
	    -d "{\"username\":\"$(u)\",\"password\":\"$(p)\",\"nickname\":\"$(n)\",\"role\":\"user\"}" \
	    && echo " ✅ 已创建受控账号 $(u)"

backup:             ## 备份 PG + MinIO 到 ./backups
	bash deploy/backup/backup.sh

restore:            ## 恢复库  make restore db=bi f=backups/pg_bi_xxx.sql.gz
	bash deploy/backup/restore.sh $(db) $(f)

health:             ## 健康检查
	@curl -fsS "https://$$(grep ^DOMAIN= .env.prod|cut -d= -f2)/ready?deep=true" && echo " ✅ API + DB + 队列 + BGE/reranker healthy"
