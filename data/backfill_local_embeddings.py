"""Compatibility wrapper; use ``data/reindex_embeddings.py`` for new work."""
from data.reindex_embeddings import reindex


def backfill(batch_size: int = 16) -> dict:
    result = reindex(batch_size=batch_size, backend="local")
    return {
        **result,
        "vectorized": result["compatible"],
    }


if __name__ == "__main__":
    print(backfill())
