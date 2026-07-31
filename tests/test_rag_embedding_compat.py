"""Embedding lineage must fail closed across local-store upgrades."""
import sqlite3

import pytest

from app.rag import local_store


@pytest.fixture
def isolated_store(monkeypatch, tmp_path):
    path = tmp_path / "kb.sqlite"
    monkeypatch.setattr(local_store, "LOCAL_KB_PATH", str(path))
    local_store._inited = False
    yield path
    local_store._inited = False


def _chunks():
    return [
        {
            "chunk_index": 0,
            "parent_ref": None,
            "level": "parent",
            "is_retrievable": False,
            "chunk_type": "text",
            "heading_path": "标题",
            "content": "父块证据",
            "content_embed": "父块证据",
            "page_no": 1,
            "token_count": 4,
        },
        {
            "chunk_index": 1,
            "parent_ref": 0,
            "level": "child",
            "is_retrievable": True,
            "chunk_type": "text",
            "heading_path": "标题",
            "content": "子块包含关键证据",
            "content_embed": "标题 子块包含关键证据",
            "page_no": 1,
            "token_count": 8,
        },
    ]


def _insert_document_with_vector():
    doc_id = local_store.create_document(
        None,
        "seed.md",
        "md",
        title="seed",
    )
    local_store.insert_chunks(
        doc_id,
        None,
        _chunks(),
        {1: [0.0] * local_store.EMBED_DIM},
    )
    local_store.set_status(doc_id, "ready", 2)
    return doc_id


def test_old_sqlite_schema_is_migrated_without_losing_content(
    monkeypatch,
    isolated_store,
):
    with sqlite3.connect(isolated_store) as connection:
        connection.executescript(
            """
            CREATE TABLE kb_document (
              id INTEGER PRIMARY KEY,
              user_id INTEGER,
              filename TEXT,
              status TEXT,
              file_type TEXT,
              source_uri TEXT,
              title TEXT,
              chunk_count INTEGER,
              created_at TEXT,
              deleted_at TEXT
            );
            CREATE TABLE kb_chunk (
              chunk_id INTEGER PRIMARY KEY,
              doc_id INTEGER,
              user_id INTEGER,
              chunk_index INTEGER,
              level TEXT,
              parent_chunk_id INTEGER,
              is_retrievable INTEGER,
              chunk_type TEXT,
              heading_path TEXT,
              content TEXT,
              content_embed TEXT,
              embedding BLOB,
              page_no INTEGER,
              token_count INTEGER,
              content_tokens TEXT
            );
            INSERT INTO kb_document(id,filename,status) VALUES(1,'legacy.md','ready');
            INSERT INTO kb_chunk(
              chunk_id,doc_id,is_retrievable,content,embedding
            ) VALUES(1,1,1,'保留的原文',X'00000000');
            """
        )
    local_store.init_store()
    with local_store._conn() as connection:
        columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(kb_chunk)",
            ).fetchall()
        }
        content = connection.execute(
            "SELECT content FROM kb_chunk WHERE chunk_id=1",
        ).fetchone()[0]
    assert {"embedding_model_version", "embedding_dim"} <= columns
    assert content == "保留的原文"


def test_new_vectors_are_tagged_but_parent_chunks_are_not(isolated_store):
    doc_id = _insert_document_with_vector()
    with local_store._conn() as connection:
        rows = connection.execute(
            """
            SELECT level,embedding,embedding_model_version,embedding_dim
            FROM kb_chunk WHERE doc_id=? ORDER BY chunk_index
            """,
            (doc_id,),
        ).fetchall()
    assert rows[0]["level"] == "parent"
    assert rows[0]["embedding"] is None
    assert rows[0]["embedding_model_version"] is None
    assert rows[0]["embedding_dim"] is None
    assert rows[1]["embedding_model_version"] == local_store.EMBED_MODEL_VERSION
    assert rows[1]["embedding_dim"] == local_store.EMBED_DIM


def test_stale_vector_is_excluded_but_keyword_recall_still_works(
    isolated_store,
):
    _insert_document_with_vector()
    with local_store._conn() as connection:
        connection.execute(
            "UPDATE kb_chunk SET embedding_model_version='old-model' "
            "WHERE is_retrievable=1",
        )
        connection.commit()

    assert local_store.search(
        1,
        [0.0] * local_store.EMBED_DIM,
    ) == []
    keyword_hits = local_store.keyword_search(1, "关键证据")
    assert len(keyword_hits) == 1
    stats = local_store.embedding_compatibility_stats()
    assert stats["mismatched"] == 1
    assert stats["compatible"] == 0


def test_partial_lineage_is_counted_as_legacy(isolated_store):
    _insert_document_with_vector()
    with local_store._conn() as connection:
        connection.execute(
            "UPDATE kb_chunk SET embedding_dim=NULL WHERE is_retrievable=1",
        )
        connection.commit()
    stats = local_store.embedding_compatibility_stats()
    assert stats["legacy"] == 1
    assert stats["compatible"] == 0


def test_insert_rejects_wrong_vector_dimension(isolated_store):
    doc_id = local_store.create_document(None, "bad.md", "md")
    with pytest.raises(ValueError, match="vector shape"):
        local_store.insert_chunks(
            doc_id,
            None,
            _chunks(),
            {1: [0.0] * (local_store.EMBED_DIM - 1)},
        )


def test_reindex_recomputes_legacy_vector_atomically(
    monkeypatch,
    isolated_store,
):
    _insert_document_with_vector()
    with local_store._conn() as connection:
        connection.execute(
            """
            UPDATE kb_chunk
            SET embedding_model_version=NULL,embedding_dim=NULL
            WHERE is_retrievable=1
            """,
        )
        connection.commit()

    from data import reindex_embeddings

    monkeypatch.setattr(
        reindex_embeddings.embed,
        "embed_passages",
        lambda texts: [[0.0] * local_store.EMBED_DIM for _ in texts],
    )
    result = reindex_embeddings.reindex(batch_size=2, backend="local")
    assert result["updated"] == 1
    assert result["compatible"] == 1
    assert result["legacy"] == 0
