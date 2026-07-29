"""PostgreSQL RAG 的公共知识与租户隔离 SQL 回归。"""
from contextlib import contextmanager

from app.rag import pg


class _Rows:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class _FakeConnection:
    def __init__(self, rows=()):
        self.rows = rows
        self.calls = []
        self.committed = False

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        return _Rows(self.rows)

    def commit(self):
        self.committed = True


def _install_fake_conn(monkeypatch, rows=()):
    fake = _FakeConnection(rows)

    @contextmanager
    def fake_conn():
        yield fake

    monkeypatch.setattr(pg, "conn", fake_conn)
    return fake


def test_vector_search_includes_public_and_current_user(monkeypatch):
    fake = _install_fake_conn(monkeypatch)
    pg.search(user_id=7, query_vec=[0.0] * pg.EMBED_DIM, top_k=3)

    sql, params = fake.calls[0]
    assert "(k.user_id IS NULL OR k.user_id=%s)" in sql
    assert params[1] == 7
    assert "k.embedding_model_version=%s" in sql
    assert "k.embedding_dim=%s" in sql
    assert params[2] == pg.EMBED_MODEL_VERSION
    assert params[3] == pg.EMBED_DIM


def test_insert_tags_child_vector_lineage(monkeypatch):
    fake = _install_fake_conn(monkeypatch, rows=[(1,)])
    chunks = [{
        "chunk_index": 0,
        "parent_ref": None,
        "level": "child",
        "is_retrievable": True,
        "chunk_type": "text",
        "heading_path": "标题",
        "content": "内容",
        "content_embed": "标题 内容",
        "page_no": 1,
        "token_count": 2,
    }]
    pg.insert_chunks(
        3,
        7,
        chunks,
        {0: [0.0] * pg.EMBED_DIM},
    )
    sql, params = fake.calls[0]
    assert "embedding_model_version" in sql
    assert "embedding_dim" in sql
    assert params[11] == pg.EMBED_MODEL_VERSION
    assert params[12] == pg.EMBED_DIM


def test_keyword_search_includes_public_and_current_user(monkeypatch):
    fake = _install_fake_conn(monkeypatch)
    monkeypatch.setattr(pg, "query_terms", lambda _query: ["比亚迪"])
    pg.keyword_search(user_id=9, query="比亚迪", top_k=4)

    sql, params = fake.calls[0]
    assert "(k.user_id IS NULL OR k.user_id=%s)" in sql
    assert params[1] == 9


def test_document_list_uses_null_as_public_owner(monkeypatch):
    fake = _install_fake_conn(monkeypatch)
    pg.list_documents(user_id=11)

    sql, params = fake.calls[0]
    assert "user_id IS NULL" in sql
    assert params == (11,)


def test_purge_user_documents_deletes_objects_chunks_and_metadata(monkeypatch):
    fake = _install_fake_conn(monkeypatch, rows=[(17, "kb-uploads/u7/source.md")])
    removed = []
    monkeypatch.setattr(
        "app.rag.store.remove_source",
        lambda source_uri: removed.append(source_uri) or True,
    )

    assert pg.purge_user_documents(7) == 1
    assert removed == ["kb-uploads/u7/source.md"]
    statements = [sql for sql, _ in fake.calls]
    assert any("DELETE FROM kb_chunk" in sql for sql in statements)
    assert any("DELETE FROM kb_document" in sql for sql in statements)
    assert fake.committed is True
