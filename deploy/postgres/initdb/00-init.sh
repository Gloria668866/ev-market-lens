#!/bin/bash
# ============================================================
# 车市镜 · PostgreSQL 容器初始化（首次启动、数据卷为空时自动跑一次）
# 作用：建「分析库 bi + 应用库 app」两个库 + 读写/只读两个角色，分别建表、装 pgvector、授权。
# 触发：pgvector/pgvector:pg16 镜像的 docker-entrypoint-initdb.d 机制（按文件名排序执行）。
#   - 同目录 sql/ 子目录里的 .sql 不会被入口自动执行，由本脚本用 psql 显式载入到指定库。
# 口令/库名全部来自容器环境变量（见 docker-compose.dev.yml 的 environment，源头是 .env）。
# ============================================================
set -euo pipefail

# 必需的环境变量（缺失即报错退出，避免静默建错）
: "${POSTGRES_USER:?}"
: "${APP_DB_NAME:?}";  : "${APP_DB_USER:?}";       : "${APP_DB_PASSWORD:?}"
: "${BI_DB_NAME:?}";   : "${BI_READONLY_USER:?}";  : "${BI_READONLY_PASSWORD:?}"

SQL_DIR="/docker-entrypoint-initdb.d/sql"
PSQL() { psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" "$@"; }

echo ">> [init] 1/5 创建角色与数据库 ..."
PSQL --dbname "$POSTGRES_DB" <<EOSQL
-- 读写角色：后端应用库用（用户/会话/消息/知识库）
CREATE ROLE ${APP_DB_USER} LOGIN PASSWORD '${APP_DB_PASSWORD}';
-- 只读角色：Text2SQL 查分析库用（生产同款：分析库永远只读）
CREATE ROLE ${BI_READONLY_USER} LOGIN PASSWORD '${BI_READONLY_PASSWORD}';

-- 分析库（只读脑）：dim_*/fact_*
CREATE DATABASE ${BI_DB_NAME} OWNER ${POSTGRES_USER};
-- 应用库（读写）：用户/会话/消息/知识库 + kb_chunk(向量)
CREATE DATABASE ${APP_DB_NAME} OWNER ${APP_DB_USER};
EOSQL

echo ">> [init] 2/5 分析库 ${BI_DB_NAME}：装 pgvector + 建 dim_*/fact_* ..."
PSQL --dbname "$BI_DB_NAME" -c "CREATE EXTENSION IF NOT EXISTS vector;"
PSQL --dbname "$BI_DB_NAME" -f "$SQL_DIR/10-bi-analysis.sql"

echo ">> [init] 3/5 分析库 ${BI_DB_NAME}：授只读角色 ${BI_READONLY_USER} ..."
PSQL --dbname "$BI_DB_NAME" <<EOSQL
GRANT CONNECT ON DATABASE ${BI_DB_NAME} TO ${BI_READONLY_USER};
GRANT USAGE ON SCHEMA public TO ${BI_READONLY_USER};
GRANT SELECT ON ALL TABLES IN SCHEMA public TO ${BI_READONLY_USER};
-- 以后新建的表也自动给只读权限
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO ${BI_READONLY_USER};
EOSQL

echo ">> [init] 4/5 应用库 ${APP_DB_NAME}：装 pgvector + 建表 ..."
PSQL --dbname "$APP_DB_NAME" -c "CREATE EXTENSION IF NOT EXISTS vector;"
PSQL --dbname "$APP_DB_NAME" -f "$SQL_DIR/30-app-schema.sql"

echo ">> [init] 5/5 应用库 ${APP_DB_NAME}：授读写角色 ${APP_DB_USER} ..."
PSQL --dbname "$APP_DB_NAME" <<EOSQL
GRANT USAGE, CREATE ON SCHEMA public TO ${APP_DB_USER};
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO ${APP_DB_USER};
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO ${APP_DB_USER};
-- 以后新建的表/序列也自动给读写权限（FOR ROLE = 建表者 ${POSTGRES_USER}）
ALTER DEFAULT PRIVILEGES FOR ROLE ${POSTGRES_USER} IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ${APP_DB_USER};
ALTER DEFAULT PRIVILEGES FOR ROLE ${POSTGRES_USER} IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO ${APP_DB_USER};
EOSQL

echo ">> [init] 完成：库 ${BI_DB_NAME}(只读 ${BI_READONLY_USER}) / ${APP_DB_NAME}(读写 ${APP_DB_USER}) 就绪，pgvector 已装。"
