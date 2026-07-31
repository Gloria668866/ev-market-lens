"""kb_document / kb_chunk 的**本地** SQLite + numpy 持久层 —— pg.py 的免依赖替身。

为什么有它：真 RAG 架构用 PostgreSQL+pgvector，但本机/演示常没有跑着的 PG。本模块用 SQLite 存
chunk + BGE 向量（float32 BLOB），查询时载入 numpy 做余弦检索；**接口与 pg.py 完全一致**
（search / keyword_search / get_parents_full / doc_parent_order / insert_chunks / list_documents …），
因此 retrieve.py 的混合召回·重排·父块归并·带引用生成逻辑**一行不改**即可复用。

公共种子语料：user_id 为 NULL 的文档对所有用户可见（路②"公共底座"）。检索/列表都按
`user_id = ? OR user_id IS NULL` 取，即"我的上传 + 公共知识库"。
切换由 config.RAG_BACKEND 决定（默认 local；设 pg 则走 pgvector）。
"""
import os
import sqlite3
import threading

import numpy as np

from ..config import (
    EMBED_DIM,
    EMBED_MODEL_VERSION,
    LOCAL_KB_PATH,
)
from .text import tokens_for_index, query_terms

_lock = threading.Lock()
_inited = False


def _conn():
    os.makedirs(os.path.dirname(os.path.abspath(LOCAL_KB_PATH)) or ".", exist_ok=True)
    c = sqlite3.connect(LOCAL_KB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init_store():
    """幂等建表（首次使用时自动调用）。"""
    global _inited
    if _inited:
        return
    with _lock:
        if _inited:
            return
        with _conn() as c:
            # P0 FIX: WAL 模式允许并发读写（多用户同时上传文件时不再 "database is locked"）
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript(
                """
                CREATE TABLE IF NOT EXISTS kb_document (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,                 -- NULL = 公共种子库
                    filename TEXT NOT NULL,
                    status TEXT DEFAULT 'parsing',
                    file_type TEXT,
                    source_uri TEXT,
                    title TEXT,
                    chunk_count INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now')),
                    deleted_at TEXT
                );
                CREATE TABLE IF NOT EXISTS kb_chunk (
                    chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    doc_id INTEGER NOT NULL,
                    user_id INTEGER,
                    chunk_index INTEGER,
                    level TEXT,                       -- parent / child
                    parent_chunk_id INTEGER,
                    is_retrievable INTEGER DEFAULT 0,
                    chunk_type TEXT,
                    heading_path TEXT,
                    content TEXT,
                    content_embed TEXT,
                    embedding BLOB,                   -- float32 bytes（仅子块）
                    embedding_model_version TEXT,
                    embedding_dim INTEGER,
                    page_no INTEGER,
                    token_count INTEGER,
                    content_tokens TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_kbc_doc ON kb_chunk(doc_id);
                CREATE INDEX IF NOT EXISTS idx_kbc_user ON kb_chunk(user_id);
                CREATE INDEX IF NOT EXISTS idx_kbd_user ON kb_document(user_id);
                """
            )
            # Existing SQLite files predate vector lineage.  ALTER is
            # intentionally idempotent and preserves every document/chunk.
            columns = {
                row["name"]
                for row in c.execute("PRAGMA table_info(kb_chunk)").fetchall()
            }
            if "embedding_model_version" not in columns:
                c.execute(
                    "ALTER TABLE kb_chunk "
                    "ADD COLUMN embedding_model_version TEXT"
                )
            if "embedding_dim" not in columns:
                c.execute(
                    "ALTER TABLE kb_chunk ADD COLUMN embedding_dim INTEGER"
                )
            c.commit()
        _inited = True


# ---------------------------------------------------------------- kb_document
def supersede_existing(c, user_id, filename):
    cur = c.execute(
        "SELECT id FROM kb_document WHERE filename=? AND deleted_at IS NULL AND "
        + ("user_id IS NULL" if user_id is None else "user_id=?"),
        (filename,) if user_id is None else (filename, user_id))
    old = [r[0] for r in cur.fetchall()]
    for did in old:
        c.execute("DELETE FROM kb_chunk WHERE doc_id=?", (did,))
        c.execute("UPDATE kb_document SET deleted_at=datetime('now'), status='superseded' WHERE id=?", (did,))
    return old


def create_document(user_id, filename, file_type, source_uri=None, title=None, supersede=True):
    init_store()
    with _conn() as c:
        if supersede:
            supersede_existing(c, user_id, filename)
        cur = c.execute(
            "INSERT INTO kb_document(user_id,filename,status,file_type,source_uri,title,chunk_count) "
            "VALUES(?,?,'parsing',?,?,?,0)", (user_id, filename, file_type, source_uri, title))
        c.commit()
        return cur.lastrowid


def soft_delete(doc_id):
    init_store()
    with _conn() as c:
        n = c.execute("UPDATE kb_document SET deleted_at=datetime('now'), status='deleted' "
                      "WHERE id=? AND deleted_at IS NULL", (doc_id,)).rowcount
        c.commit()
    return n > 0


def set_status(doc_id, status, chunk_count=None):
    init_store()
    with _conn() as c:
        if chunk_count is None:
            c.execute("UPDATE kb_document SET status=? WHERE id=?", (status, doc_id))
        else:
            c.execute("UPDATE kb_document SET status=?, chunk_count=? WHERE id=?", (status, chunk_count, doc_id))
        c.commit()


def get_document(doc_id):
    init_store()
    with _conn() as c:
        r = c.execute("SELECT id,user_id,filename,status,file_type,source_uri,title,chunk_count,"
                      "created_at,deleted_at FROM kb_document WHERE id=?", (doc_id,)).fetchone()
    return dict(r) if r else None


def list_documents(user_id):
    """当前用户未软删的文档 + 公共种子库（user_id IS NULL）。"""
    init_store()
    with _conn() as c:
        rows = c.execute(
            "SELECT id,user_id,filename,status,file_type,source_uri,title,chunk_count,created_at "
            "FROM kb_document "
            "WHERE deleted_at IS NULL AND (user_id IS NULL OR user_id=?) ORDER BY user_id IS NULL DESC, created_at DESC",
            (user_id,)).fetchall()
    return [dict(r) for r in rows]


def purge_user_documents(user_id: int) -> int:
    """Hard-delete all private local documents and chunks for one deleted user."""
    init_store()
    with _conn() as c:
        doc_ids = [
            row[0]
            for row in c.execute(
                "SELECT id FROM kb_document WHERE user_id=?",
                (user_id,),
            ).fetchall()
        ]
        if doc_ids:
            placeholders = ",".join("?" * len(doc_ids))
            c.execute(
                f"DELETE FROM kb_chunk WHERE doc_id IN ({placeholders})",
                doc_ids,
            )
        c.execute("DELETE FROM kb_document WHERE user_id=?", (user_id,))
        c.commit()
    return len(doc_ids)


# ---------------------------------------------------------------- kb_chunk
def insert_chunks(doc_id, user_id, chunks, embeddings_by_index):
    """写父子 chunk（父块在前），回填 parent_chunk_id；embeddings_by_index={chunk_index: vec(list)}。"""
    init_store()
    n = 0
    with _conn() as c:
        idx_to_id = {}
        for ch in chunks:
            parent_id = idx_to_id.get(ch["parent_ref"]) if ch["parent_ref"] is not None else None
            vec = embeddings_by_index.get(ch["chunk_index"])
            if vec is None:
                emb_blob = None
                embedding_version = None
                embedding_dim = None
            else:
                array = np.asarray(vec, dtype=np.float32)
                if array.shape != (EMBED_DIM,):
                    raise ValueError(
                        f"chunk {ch['chunk_index']} vector shape {array.shape}, "
                        f"expected {(EMBED_DIM,)}"
                    )
                emb_blob = array.tobytes()
                embedding_version = EMBED_MODEL_VERSION
                embedding_dim = EMBED_DIM
            cur = c.execute(
                "INSERT INTO kb_chunk(doc_id,user_id,chunk_index,level,parent_chunk_id,is_retrievable,"
                "chunk_type,heading_path,content,content_embed,embedding,embedding_model_version,"
                "embedding_dim,page_no,token_count,content_tokens) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (doc_id, user_id, ch["chunk_index"], ch["level"], parent_id,
                 1 if ch["is_retrievable"] else 0, ch["chunk_type"], ch["heading_path"],
                 ch["content"], ch["content_embed"], emb_blob, embedding_version,
                 embedding_dim, ch["page_no"], ch["token_count"],
                 tokens_for_index(ch["content"])))
            idx_to_id[ch["chunk_index"]] = cur.lastrowid
            n += 1
        c.commit()
    return n


_HIT_KEYS = ["chunk_id", "parent_chunk_id", "doc_id", "heading_path", "content", "page_no", "score"]


def _retrievable_rows(c, user_id, *, compatible_vectors_only: bool = False):
    """取所有可检索子块（我的 + 公共，未软删）。"""
    compatibility = ""
    params = [user_id]
    if compatible_vectors_only:
        compatibility = (
            " AND k.embedding IS NOT NULL "
            "AND k.embedding_model_version=? AND k.embedding_dim=? "
            "AND length(k.embedding)=?"
        )
        params.extend([
            EMBED_MODEL_VERSION,
            EMBED_DIM,
            EMBED_DIM * np.dtype(np.float32).itemsize,
        ])
    return c.execute(
        "SELECT k.chunk_id,k.parent_chunk_id,k.doc_id,k.heading_path,k.content,k.page_no,"
        "k.embedding,k.content_tokens FROM kb_chunk k JOIN kb_document d ON k.doc_id=d.id "
        "WHERE k.is_retrievable=1 AND d.deleted_at IS NULL "
        f"AND (k.user_id IS NULL OR k.user_id=?){compatibility}",
        tuple(params)).fetchall()


def search(user_id, query_vec, top_k=20):
    """向量召回：numpy 余弦（BGE 已归一化 → 点积即余弦）。返回与 pg.search 同结构。"""
    init_store()
    if query_vec is None:          # 无向量模型 → 跳过向量召回（走纯词法）
        return []
    qv = np.asarray(query_vec, dtype=np.float32)
    if qv.shape != (EMBED_DIM,):
        raise ValueError(
            f"query vector shape {qv.shape}, expected {(EMBED_DIM,)}"
        )
    with _conn() as c:
        rows = _retrievable_rows(c, user_id, compatible_vectors_only=True)
    if not rows:
        return []
    mat = np.stack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows])
    scores = mat @ qv
    order = np.argsort(-scores)[:top_k]
    out = []
    for i in order:
        r = rows[int(i)]
        out.append({"chunk_id": r["chunk_id"], "parent_chunk_id": r["parent_chunk_id"],
                    "doc_id": r["doc_id"], "heading_path": r["heading_path"],
                    "content": r["content"], "page_no": r["page_no"], "score": float(scores[int(i)])})
    return out


def keyword_search(user_id, query, top_k=20):
    """关键词召回：jieba 切词后在 content_tokens 上按命中词数打分（补向量对专名/数字的弱项）。"""
    init_store()
    terms = query_terms(query)
    if not terms:
        return []
    with _conn() as c:
        rows = _retrievable_rows(c, user_id)
    scored = []
    for r in rows:
        toks = (r["content_tokens"] or "")
        hit = sum(1 for t in terms if t in toks)
        if hit:
            scored.append((hit, r))
    scored.sort(key=lambda x: -x[0])
    out = []
    for hit, r in scored[:top_k]:
        out.append({"chunk_id": r["chunk_id"], "parent_chunk_id": r["parent_chunk_id"],
                    "doc_id": r["doc_id"], "heading_path": r["heading_path"],
                    "content": r["content"], "page_no": r["page_no"], "score": float(hit)})
    return out


def get_parents_full(parent_ids):
    init_store()
    ids = [p for p in parent_ids if p is not None]
    if not ids:
        return {}
    ph = ",".join("?" * len(ids))
    with _conn() as c:
        rows = c.execute(
            f"SELECT k.chunk_id,k.doc_id,k.chunk_index,k.heading_path,k.content,k.page_no,"
            f"d.filename,d.title,d.created_at FROM kb_chunk k JOIN kb_document d ON k.doc_id=d.id "
            f"WHERE k.chunk_id IN ({ph})", ids).fetchall()
    return {r["chunk_id"]: dict(r) for r in rows}


def doc_parent_order(doc_id):
    init_store()
    with _conn() as c:
        rows = c.execute("SELECT chunk_id FROM kb_chunk WHERE doc_id=? AND level='parent' "
                         "ORDER BY chunk_index", (doc_id,)).fetchall()
    return [r[0] for r in rows]


def get_chunks(chunk_ids):
    init_store()
    ids = list(chunk_ids)
    if not ids:
        return {}
    ph = ",".join("?" * len(ids))
    with _conn() as c:
        rows = c.execute(f"SELECT chunk_id,doc_id,level,heading_path,content,page_no "
                         f"FROM kb_chunk WHERE chunk_id IN ({ph})", ids).fetchall()
    return {r["chunk_id"]: dict(r) for r in rows}


def stats():
    """Return active document/chunk counts for build output and health checks."""
    init_store()
    with _conn() as c:
        d = c.execute("SELECT COUNT(*) FROM kb_document WHERE deleted_at IS NULL").fetchone()[0]
        k = c.execute(
            "SELECT COUNT(*) FROM kb_chunk k JOIN kb_document d ON d.id=k.doc_id "
            "WHERE d.deleted_at IS NULL"
        ).fetchone()[0]
    return d, k


def embedding_compatibility_stats() -> dict:
    """Describe active child vectors without trusting unversioned legacy rows."""
    init_store()
    expected_bytes = EMBED_DIM * np.dtype(np.float32).itemsize
    with _conn() as c:
        row = c.execute(
            """
            SELECT
              COUNT(*) AS retrievable,
              SUM(CASE WHEN k.embedding IS NULL THEN 1 ELSE 0 END) AS missing,
              SUM(CASE WHEN k.embedding IS NOT NULL
                        AND (
                          k.embedding_model_version IS NULL
                          OR k.embedding_dim IS NULL
                        )
                       THEN 1 ELSE 0 END) AS legacy,
              SUM(CASE WHEN k.embedding IS NOT NULL
                        AND k.embedding_model_version=?
                        AND k.embedding_dim=?
                        AND length(k.embedding)=?
                       THEN 1 ELSE 0 END) AS compatible,
              SUM(CASE WHEN k.embedding IS NOT NULL
                        AND k.embedding_model_version IS NOT NULL
                        AND k.embedding_dim IS NOT NULL
                        AND (
                          k.embedding_model_version<>?
                          OR k.embedding_dim<>?
                          OR length(k.embedding)<>?
                        )
                       THEN 1 ELSE 0 END) AS mismatched
            FROM kb_chunk k
            JOIN kb_document d ON d.id=k.doc_id
            WHERE d.deleted_at IS NULL AND k.is_retrievable=1
            """,
            (
                EMBED_MODEL_VERSION,
                EMBED_DIM,
                expected_bytes,
                EMBED_MODEL_VERSION,
                EMBED_DIM,
                expected_bytes,
            ),
        ).fetchone()
    return {
        key: int(row[key] or 0)
        for key in ("retrievable", "compatible", "legacy", "mismatched", "missing")
    }
