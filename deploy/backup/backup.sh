#!/usr/bin/env bash
# 车市镜 · 备份：PostgreSQL(bi+app) + MinIO 对象，落本地 backups/ 并按天轮转。
# 用法：从仓库根目录跑（读 .env.prod 取 MinIO 口令）：  bash deploy/backup/backup.sh
# 建议挂 host cron 每天 02:30：  30 2 * * * cd /opt/carmirror && bash deploy/backup/backup.sh >> /var/log/carmirror-backup.log 2>&1
set -euo pipefail
cd "$(dirname "$0")/../.."                 # 切到仓库根
set -a; [ -f .env.prod ] && . ./.env.prod; set +a
BACKUP_DIR=${BACKUP_DIR:-./backups}
KEEP_DAYS=${KEEP_DAYS:-14}
TS=$(date +%Y%m%d_%H%M%S)
mkdir -p "$BACKUP_DIR"

echo ">> [backup $TS] PostgreSQL bi/app …"
# 容器内本地连接走 trust，无需密码；dump 后 gzip
docker exec carmirror-postgres pg_dump -U "${POSTGRES_SUPER_USER:-postgres}" -d "${BI_DB_NAME:-bi}"  | gzip > "$BACKUP_DIR/pg_bi_$TS.sql.gz"
docker exec carmirror-postgres pg_dump -U "${POSTGRES_SUPER_USER:-postgres}" -d "${APP_DB_NAME:-app}" | gzip > "$BACKUP_DIR/pg_app_$TS.sql.gz"

echo ">> [backup $TS] MinIO 对象 …"
# 借 minio 容器的网络命名空间，用 mc 镜像把桶同步到本地
docker run --rm --network "container:carmirror-minio" \
  -e MC_HOST_s="http://${MINIO_ROOT_USER}:${MINIO_ROOT_PASSWORD}@localhost:9000" \
  -v "$(pwd)/$BACKUP_DIR/minio_$TS:/backup" minio/mc:latest \
  sh -c "mc mirror --quiet s/${MINIO_BUCKET_UPLOADS:-kb-uploads} /backup/${MINIO_BUCKET_UPLOADS:-kb-uploads}; \
         mc mirror --quiet s/${MINIO_BUCKET_RAW:-crawl-raw} /backup/${MINIO_BUCKET_RAW:-crawl-raw}" || true

echo ">> 轮转：删除 ${KEEP_DAYS} 天前的备份"
find "$BACKUP_DIR" -name 'pg_*.sql.gz' -mtime +"$KEEP_DAYS" -delete 2>/dev/null || true
find "$BACKUP_DIR" -maxdepth 1 -name 'minio_*' -type d -mtime +"$KEEP_DAYS" -exec rm -rf {} + 2>/dev/null || true
echo "✅ 备份完成 → $BACKUP_DIR (pg_bi_$TS / pg_app_$TS / minio_$TS)"
