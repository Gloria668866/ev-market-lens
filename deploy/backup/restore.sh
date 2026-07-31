#!/usr/bin/env bash
# 车市镜 · 恢复：从备份的 .sql.gz 恢复某个库。MinIO 用 mc mirror 反向同步即可。
# 用法：  bash deploy/backup/restore.sh bi  backups/pg_bi_20260525_023000.sql.gz
#         bash deploy/backup/restore.sh app backups/pg_app_20260525_023000.sql.gz
set -euo pipefail
cd "$(dirname "$0")/../.."
set -a; [ -f .env.prod ] && . ./.env.prod; set +a
DB="${1:?用法: restore.sh <bi|app> <dump.sql.gz>}"
DUMP="${2:?缺少 dump 文件路径}"
SU="${POSTGRES_SUPER_USER:-postgres}"

case "$DB" in
  bi|app) ;;
  *) echo "❌ 仅允许恢复 bi 或 app 数据库" >&2; exit 2 ;;
esac
[ -f "$DUMP" ] || { echo "❌ 备份文件不存在：$DUMP" >&2; exit 2; }

echo "⚠️  将把 $DUMP 恢复进库 [$DB]（覆盖现有数据）。Ctrl-C 取消，5 秒后开始…"; sleep 5
# 停止所有会读写 PostgreSQL 的应用进程，避免恢复过程中出现并发写入或半恢复读。
COMPOSE=(docker compose --env-file .env.prod -f deploy/docker-compose.prod.yml)
echo ">> 停止 api / worker / beat …"
"${COMPOSE[@]}" stop api worker beat
restart_services() {
  echo ">> 启动 api / worker / beat …"
  "${COMPOSE[@]}" up -d api worker beat
}
trap restart_services EXIT

# 重建库（断开残留连接→drop→create），再灌入
docker exec carmirror-postgres psql -U "$SU" -d postgres -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$DB' AND pid<>pg_backend_pid();" || true
docker exec carmirror-postgres psql -U "$SU" -d postgres -c "DROP DATABASE IF EXISTS $DB;"
docker exec carmirror-postgres psql -U "$SU" -d postgres -c "CREATE DATABASE $DB;"
gunzip -c "$DUMP" | docker exec -i carmirror-postgres psql -U "$SU" -d "$DB"
trap - EXIT
restart_services
echo ">> 等待深度就绪检查 …"
for _ in $(seq 1 30); do
  if docker exec carmirror-api curl -fsS http://127.0.0.1:8000/ready?deep=true >/dev/null; then
    echo "✅ 已从 $DUMP 恢复库 [$DB]，应用重新就绪。"
    exit 0
  fi
  sleep 2
done
echo "❌ 数据已恢复，但应用未在 60 秒内通过深度就绪检查；请执行 make logs s=api" >&2
exit 1
