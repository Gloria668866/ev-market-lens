"""Backfill missing vectors in the active local knowledge base.

Use after repairing or changing the local embedding model:
    python data/backfill_local_embeddings.py
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import EMBED_DIM
from app.rag import embed
from app.rag import local_store as store


def backfill(batch_size: int = 16) -> dict:
    store.init_store()
    with store._conn() as conn:
        rows = conn.execute(
            "SELECT k.chunk_id,k.content_embed FROM kb_chunk k "
            "JOIN kb_document d ON d.id=k.doc_id "
            "WHERE d.deleted_at IS NULL AND k.is_retrievable=1 "
            "AND k.embedding IS NULL ORDER BY k.chunk_id"
        ).fetchall()

    updated = 0
    for start in range(0, len(rows), batch_size):
        batch = rows[start:start + batch_size]
        vectors = embed.embed_passages([row["content_embed"] for row in batch])
        if len(vectors) != len(batch):
            raise RuntimeError(
                f"embedding batch mismatch: expected {len(batch)}, got {len(vectors)}"
            )
        payload = []
        for row, vector in zip(batch, vectors):
            array = np.asarray(vector, dtype=np.float32)
            if array.shape != (EMBED_DIM,):
                raise RuntimeError(
                    f"chunk {row['chunk_id']} vector shape {array.shape}, expected {(EMBED_DIM,)}"
                )
            payload.append((array.tobytes(), row["chunk_id"]))
        with store._conn() as conn:
            conn.executemany(
                "UPDATE kb_chunk SET embedding=? WHERE chunk_id=?",
                payload,
            )
            conn.commit()
        updated += len(payload)

    with store._conn() as conn:
        coverage = conn.execute(
            "SELECT "
            "SUM(CASE WHEN k.is_retrievable=1 THEN 1 ELSE 0 END) AS retrievable,"
            "SUM(CASE WHEN k.is_retrievable=1 AND k.embedding IS NOT NULL THEN 1 ELSE 0 END) AS vectorized "
            "FROM kb_chunk k JOIN kb_document d ON d.id=k.doc_id "
            "WHERE d.deleted_at IS NULL"
        ).fetchone()
    return {
        "updated": updated,
        "retrievable": int(coverage["retrievable"] or 0),
        "vectorized": int(coverage["vectorized"] or 0),
    }


if __name__ == "__main__":
    print(backfill())
