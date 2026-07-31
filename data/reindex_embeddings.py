"""Recompute active child embeddings whose vector lineage is missing/stale.

The document text, parent/child chunks and keyword index are preserved.  Only
the reproducible embedding column and its lineage metadata are updated.

Usage:
    python data/reindex_embeddings.py
    RAG_BACKEND=pg python data/reindex_embeddings.py --batch-size 32
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import (  # noqa: E402
    EMBED_DIM,
    EMBED_MODEL_VERSION,
    RAG_BACKEND,
)
from app.rag import embed  # noqa: E402


def _validate_batch(rows, vectors) -> list[tuple]:
    if len(vectors) != len(rows):
        raise RuntimeError(
            f"embedding batch mismatch: expected {len(rows)}, got {len(vectors)}"
        )
    output = []
    for row, vector in zip(rows, vectors):
        array = np.asarray(vector, dtype=np.float32)
        if array.shape != (EMBED_DIM,):
            raise RuntimeError(
                f"chunk {row['chunk_id']} vector shape {array.shape}, "
                f"expected {(EMBED_DIM,)}"
            )
        output.append((row["chunk_id"], array))
    return output


def _reindex_local(batch_size: int) -> dict:
    from app.rag import local_store as store

    store.init_store()
    expected_bytes = EMBED_DIM * np.dtype(np.float32).itemsize
    with store._conn() as connection:
        rows = connection.execute(
            """
            SELECT k.chunk_id, COALESCE(k.content_embed, k.content) AS content_embed
            FROM kb_chunk k
            JOIN kb_document d ON d.id=k.doc_id
            WHERE d.deleted_at IS NULL
              AND k.is_retrievable=1
              AND (
                k.embedding IS NULL
                OR k.embedding_model_version IS NULL
                OR k.embedding_model_version<>?
                OR k.embedding_dim IS NULL
                OR k.embedding_dim<>?
                OR length(k.embedding)<>?
              )
            ORDER BY k.chunk_id
            """,
            (EMBED_MODEL_VERSION, EMBED_DIM, expected_bytes),
        ).fetchall()

    updated = 0
    for start in range(0, len(rows), batch_size):
        batch = rows[start:start + batch_size]
        vectors = embed.embed_passages([row["content_embed"] for row in batch])
        payload = [
            (
                array.tobytes(),
                EMBED_MODEL_VERSION,
                EMBED_DIM,
                chunk_id,
            )
            for chunk_id, array in _validate_batch(batch, vectors)
        ]
        # Metadata is written in the same transaction as the vector.  A failed
        # batch remains legacy and therefore excluded from vector search.
        with store._conn() as connection:
            connection.executemany(
                """
                UPDATE kb_chunk
                SET embedding=?,
                    embedding_model_version=?,
                    embedding_dim=?
                WHERE chunk_id=?
                """,
                payload,
            )
            connection.commit()
        updated += len(payload)

    return {"backend": "local", "updated": updated, **store.embedding_compatibility_stats()}


def _reindex_pg(batch_size: int) -> dict:
    from app.rag import pg

    with pg.conn() as connection:
        raw_rows = connection.execute(
            """
            SELECT k.chunk_id, COALESCE(k.content_embed, k.content) AS content_embed
            FROM kb_chunk k
            JOIN kb_document d ON d.id=k.doc_id
            WHERE d.deleted_at IS NULL
              AND k.is_retrievable
              AND (
                k.embedding IS NULL
                OR k.embedding_model_version IS DISTINCT FROM %s
                OR k.embedding_dim IS DISTINCT FROM %s
              )
            ORDER BY k.chunk_id
            """,
            (EMBED_MODEL_VERSION, EMBED_DIM),
        ).fetchall()
    rows = [
        {"chunk_id": row[0], "content_embed": row[1]}
        for row in raw_rows
    ]

    updated = 0
    for start in range(0, len(rows), batch_size):
        batch = rows[start:start + batch_size]
        vectors = embed.embed_passages([row["content_embed"] for row in batch])
        payload = [
            (
                array.tolist(),
                EMBED_MODEL_VERSION,
                EMBED_DIM,
                chunk_id,
            )
            for chunk_id, array in _validate_batch(batch, vectors)
        ]
        with pg.conn() as connection:
            connection.executemany(
                """
                UPDATE kb_chunk
                SET embedding=%s,
                    embedding_model_version=%s,
                    embedding_dim=%s
                WHERE chunk_id=%s
                """,
                payload,
            )
            connection.commit()
        updated += len(payload)

    return {"backend": "pg", "updated": updated, **pg.embedding_compatibility_stats()}


def reindex(batch_size: int = 16, backend: str | None = None) -> dict:
    selected = (backend or RAG_BACKEND).lower()
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    if selected == "local":
        return _reindex_local(batch_size)
    if selected == "pg":
        return _reindex_pg(batch_size)
    raise ValueError(f"unsupported RAG backend: {selected}")


def main() -> None:
    parser = argparse.ArgumentParser(description="重建不兼容的 RAG embedding")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--backend", choices=["local", "pg"])
    args = parser.parse_args()
    print(reindex(batch_size=args.batch_size, backend=args.backend))


if __name__ == "__main__":
    main()
