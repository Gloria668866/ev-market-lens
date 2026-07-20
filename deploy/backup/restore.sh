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

echo "⚠️  将把 $DUMP 恢复进库 [$DB]（覆盖现有数据）。Ctrl-C 取消，5 秒后开始…"; sleep 5
# 重建库（断开连接→drop→create），再灌入
docker exec carmirror-postgres psql -U "$SU" -d postgres -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$DB' AND pid<>pg_backend_pid();" || true
docker exec carmirror-postgres psql -U "$SU" -d postgres -c "DROP DATABASE IF EXISTS $DB;"
docker exec carmirror-postgres psql -U "$SU" -d postgres -c "CREATE DATABASE $DB;"
gunzip -c "$DUMP" | docker exec -i carmirror-postgres psql -U "$SU" -d "$DB"
echo "✅ 已从 $DUMP 恢复库 [$DB]。注意：角色/权限若丢失，可重跑 initdb 或手动授权。"
echo "   MinIO 恢复：docker run --rm --network container:carmirror-minio -e MC_HOST_s=... -v \$PWD/backups/minio_XXX:/b minio/mc mc mirror /b/kb-uploads s/kb-uploads"
