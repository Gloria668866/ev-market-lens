"""不启动 Docker 也能守住的生产配置契约。"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_prod_env_selects_real_production_backends():
    env = _text(".env.prod.example")
    assert "APP_ENV=production" in env
    assert "RAG_BACKEND=pg" in env
    assert "MODELS_DIR=../models" in env
    assert "ADMIN_PASSWORD=REPLACE_WITH_STRONG_ADMIN_PASSWORD" in env
    assert "ALLOW_PUBLIC_REGISTRATION=false" in env
    assert "DAILY_QUESTION_LIMIT=30" in env
    assert "PIPELINE_MAX_PARALLEL=2" in env
    assert "EMBED_DIM=1024" in env
    assert "TAVILY_API_KEY=" in env
    assert "BRAVE_SEARCH_API_KEY=" in env
    assert "SEARCH_API_TIMEOUT_SECONDS=8" in env
    assert "TAVILY_SEARCH_DEPTH=basic" in env
    assert "ANALYSIS_MIN_SALES_ROWS=1000" in env
    assert "ANALYSIS_MIN_SALES_MONTHS=12" in env
    assert "deepseek-v4-pro" not in env


def test_compose_uses_strict_readiness_and_resource_controls():
    compose = _text("deploy/docker-compose.prod.yml")
    assert "APP_ENV: production" in compose
    assert "RAG_BACKEND: pg" in compose
    assert 'PIPELINE_LOCAL_FALLBACK: "false"' in compose
    assert "http://localhost:8000/ready" in compose
    assert "${API_WORKERS:-1}" in compose
    assert "${CELERY_CONCURRENCY:-1}" in compose
    assert "${MODELS_DIR:-../models}" in compose
    assert "../data/raw:/app/data/raw" in compose
    assert "crawlraw:" not in compose
    assert "service_completed_successfully" in compose
    assert "deploy/migrate_app_pg.py" in compose
    assert "OMP_NUM_THREADS: ${OMP_NUM_THREADS:-1}" in compose
    assert "MKL_NUM_THREADS: ${MKL_NUM_THREADS:-1}" in compose
    assert "TOKENIZERS_PARALLELISM: ${TOKENIZERS_PARALLELISM:-false}" in compose
    assert "TAVILY_API_KEY: ${TAVILY_API_KEY:-}" in compose
    assert "BRAVE_SEARCH_API_KEY: ${BRAVE_SEARCH_API_KEY:-}" in compose


def test_fresh_clone_keeps_raw_bind_mount_writable():
    gitignore = _text(".gitignore")
    makefile = _text("Makefile")
    assert "data/raw/*" in gitignore
    assert "!data/raw/.gitkeep" in gitignore
    assert (ROOT / "data/raw/.gitkeep").is_file()
    assert "up:" in makefile
    assert "mkdir -p data/raw" in makefile


def test_production_schema_covers_security_memory_and_public_rag():
    ddl = _text("deploy/postgres/initdb/sql/30-app-schema.sql")
    assert "token_version" in ddl
    assert "CREATE TABLE user_profile" in ddl
    assert "CREATE TABLE memory_episode" in ddl
    assert "user_id     BIGINT REFERENCES users(id)" in ddl
    assert "embedding_model_version" in ddl
    assert "embedding_dim" in ddl
    migration = _text(
        "deploy/postgres/migrations/20260729_embedding_lineage.sql",
    )
    assert "ADD COLUMN IF NOT EXISTS embedding_model_version" in migration
    assert "ADD COLUMN IF NOT EXISTS embedding_dim" in migration


def test_frontend_production_default_is_same_origin():
    config = _text("frontend/src/api/config.js")
    assert "import.meta.env.DEV ? 'http://localhost:8000' : ''" in config
    assert "VITE_API_BASE || 'http://localhost:8000'" not in config


def test_api_image_contains_runtime_agent_configs():
    dockerfile = _text("deploy/Dockerfile.api")
    assert "COPY config/ ./config/" in dockerfile
    assert "deploy/migrate_app_pg.py" in dockerfile
    assert "deploy/postgres/migrations/" in dockerfile


def test_make_health_runs_deep_readiness_probe():
    makefile = _text("Makefile")
    assert "/ready?deep=true" in makefile


def test_price_query_uses_postgresql_strict_group_by():
    main = _text("app/main.py")
    assert (
        "GROUP BY b.brand_name, s.series_id, s.series_name, "
        "s.segment, s.endurance_km"
    ) in main


def test_readiness_tracks_required_kb_router():
    main = _text("app/main.py")
    assert "KB_ROUTER_LOADED = False" in main
    assert "and KB_ROUTER_LOADED" in main
    assert '"kb_router": KB_ROUTER_LOADED' in main
    assert 'if IS_PRODUCTION or RAG_BACKEND == "pg":' in main
    assert "FROM fact_sales_rank LIMIT 1" in main
    assert "FROM memory_episode LIMIT 0" in main
    assert "FROM kb_chunk LIMIT 0" in main
    assert '"embedding_store_compatible": embedding_store_compatible' in main
    assert '"web_search_official_api": web_search_official_api' in main
    assert "and web_search_ready" in main
    assert 'embedding_store_stats.get("missing", 0) == 0' in main
    assert 'embedding_store_stats.get("compatible", 0)' in main
    assert 'embedding_store_stats.get("retrievable", 0)' in main
    assert "::vector <=> '[0,0]'::vector" in main


def test_backup_and_restore_fail_closed():
    backup = _text("deploy/backup/backup.sh")
    restore = _text("deploy/backup/restore.sh")
    assert "--entrypoint /bin/sh minio/mc:latest" in backup
    assert "mc mirror" in backup
    assert '" || true' not in backup
    assert 'bi|app)' in restore
    assert '"${COMPOSE[@]}" stop api worker beat' in restore
    assert "trap restart_services EXIT" in restore
    assert "carmirror-api curl -fsS" in restore
