-- Existing PostgreSQL volumes do not rerun docker-entrypoint-initdb.d.
-- Preserve legacy vectors but leave their lineage NULL so vector search
-- safely excludes them until data/reindex_embeddings.py recomputes them.
ALTER TABLE kb_chunk
  ADD COLUMN IF NOT EXISTS embedding_model_version VARCHAR(128);

ALTER TABLE kb_chunk
  ADD COLUMN IF NOT EXISTS embedding_dim INTEGER;
