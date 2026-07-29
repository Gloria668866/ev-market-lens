#!/usr/bin/env python3
"""把仓库内 8 篇公开种子语料幂等灌入生产 PostgreSQL/pgvector 知识库。

应在已经启动的 API 容器内执行：
    docker compose --env-file ../.env.prod -f docker-compose.prod.yml \
      exec api python data/build_pg_kb.py

同名文件再次执行会 supersede 旧版本，不会产生重复可检索分块。
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import RAG_BACKEND  # noqa: E402
from app.agent_tools import ingest_text_as_document  # noqa: E402

SEED_DIR = Path(__file__).parent / "seed_kb"


def build() -> tuple[int, int]:
    if RAG_BACKEND != "pg":
        raise RuntimeError(
            f"RAG_BACKEND={RAG_BACKEND!r}；生产种子入库必须显式设置 RAG_BACKEND=pg"
        )
    files = sorted(SEED_DIR.glob("*.md"))
    if not files:
        raise FileNotFoundError(f"种子语料不存在：{SEED_DIR}")

    total_chunks = 0
    for path in files:
        doc_id, chunk_count = ingest_text_as_document(
            title=path.stem,
            text=path.read_text(encoding="utf-8"),
            filename=path.name,
            source_url=f"seed://{path.name}",
            user_id=0,  # public=True 会在 PG 中规范化为 NULL 公共所有者
            public=True,
        )
        total_chunks += chunk_count
        print(f"  OK {path.name} -> doc_id={doc_id}, chunks={chunk_count}")

    print(f"知识库种子完成：documents={len(files)}, chunks={total_chunks}")
    return len(files), total_chunks


if __name__ == "__main__":
    build()
