"""kb_document / kb_chunk 的 PostgreSQL(pgvector) 持久层（原生 psycopg）。

为什么不走 ORM：kb_chunk.embedding 是 vector(1024)，SQLite 建不了、ORM 跨库也别扭；
RAG 一律连 PG（config.RAG_DATABASE_URL），用 psycopg + pgvector，干净可控。

关键实现：
- 重传软删（§5.8）：同 (user_id, filename) 再传 → 旧 kb_document 置 deleted_at + 删其 kb_chunk，
  再建新文档 → **不产生重复 chunk**。
- 父子两段写：先插 parent 拿真实 chunk_id，再插 child 时把 parent_ref(列表下标) 换成真实 parent_chunk_id。
- 检索预过滤（§5.8）：WHERE is_retrievable AND user_id=? 先筛租户再向量搜，避免 HNSW 后过滤召回不足。
"""
import psycopg
from pgvector.psycopg import register_vector

from ..config import (
    EMBED_DIM,
    EMBED_MODEL_VERSION,
    RAG_DATABASE_URL,
)
from .text import tokens_for_index, query_terms


def conn():
    c = psycopg.connect(RAG_DATABASE_URL)
    register_vector(c)
    return c


# ---------------------------------------------------------------- kb_document
def supersede_existing(c, user_id: int | None, filename: str):
    """重传：把同名旧文档软删 + 删其 chunk（防重复）。返回被软删的旧 doc_id 列表。"""
    rows = c.execute(
        "SELECT id FROM kb_document WHERE user_id IS NOT DISTINCT FROM %s "
        "AND filename=%s AND deleted_at IS NULL",
        (user_id, filename)).fetchall()
    old_ids = [r[0] for r in rows]
    for did in old_ids:
        c.execute("DELETE FROM kb_chunk WHERE doc_id=%s", (did,))
        c.execute("UPDATE kb_document SET deleted_at=now(), status='superseded' WHERE id=%s", (did,))
    return old_ids


def create_document(user_id: int | None, filename: str, file_type: str, source_uri: str,
                    title: str = None, supersede: bool = True) -> int:
    """建 kb_document(status=parsing)，返回 doc_id。supersede=True 时先软删同名旧版本。"""
    with conn() as c:
        if supersede:
            supersede_existing(c, user_id, filename)
        row = c.execute(
            "INSERT INTO kb_document(user_id,filename,status,file_type,source_uri,title,chunk_count) "
            "VALUES(%s,%s,'parsing',%s,%s,%s,0) RETURNING id",
            (user_id, filename, file_type, source_uri, title)).fetchone()
        c.commit()
        return row[0]


def soft_delete(doc_id: int) -> bool:
    """软删除文档：置 deleted_at（检索 JOIN kb_document WHERE deleted_at IS NULL 自动排除其 chunk）。"""
    with conn() as c:
        n = c.execute("UPDATE kb_document SET deleted_at=now(), status='deleted' "
                      "WHERE id=%s AND deleted_at IS NULL", (doc_id,)).rowcount
        c.commit()
    return n > 0


def set_status(doc_id: int, status: str, chunk_count: int = None):
    with conn() as c:
        if chunk_count is None:
            c.execute("UPDATE kb_document SET status=%s WHERE id=%s", (status, doc_id))
        else:
            c.execute("UPDATE kb_document SET status=%s, chunk_count=%s WHERE id=%s",
                      (status, chunk_count, doc_id))
        c.commit()


def get_document(doc_id: int):
    with conn() as c:
        r = c.execute("SELECT id,user_id,filename,status,file_type,source_uri,title,chunk_count,"
                      "created_at,deleted_at FROM kb_document WHERE id=%s", (doc_id,)).fetchone()
        if not r:
            return None
        keys = ["id", "user_id", "filename", "status", "file_type", "source_uri", "title",
                "chunk_count", "created_at", "deleted_at"]
        return dict(zip(keys, r))


# ---------------------------------------------------------------- kb_chunk
def insert_chunks(doc_id: int, user_id: int | None, chunks, embeddings_by_index: dict) -> int:
    """写父子 chunk。chunks 按文档顺序（parent 在其 child 之前）；
    embeddings_by_index={chunk_index: vector}（仅子块有）。回填 parent_chunk_id。返回写入条数。"""
    sql = ("INSERT INTO kb_chunk(doc_id,user_id,chunk_index,level,parent_chunk_id,is_retrievable,"
           "chunk_type,heading_path,content,content_embed,embedding,embedding_model_version,"
           "embedding_dim,page_no,token_count,content_tokens) "
           "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING chunk_id")
    n = 0
    with conn() as c:
        idx_to_id = {}                       # chunk_index(下标) → 真实 chunk_id
        for ch in chunks:
            parent_id = idx_to_id.get(ch["parent_ref"]) if ch["parent_ref"] is not None else None
            emb = embeddings_by_index.get(ch["chunk_index"])      # None=父块/无向量
            if emb is None:
                embedding_version = None
                embedding_dim = None
            else:
                if len(emb) != EMBED_DIM:
                    raise ValueError(
                        f"chunk {ch['chunk_index']} vector length {len(emb)}, "
                        f"expected {EMBED_DIM}"
                    )
                embedding_version = EMBED_MODEL_VERSION
                embedding_dim = EMBED_DIM
            cid = c.execute(sql, (
                doc_id, user_id, ch["chunk_index"], ch["level"], parent_id, ch["is_retrievable"],
                ch["chunk_type"], ch["heading_path"], ch["content"], ch["content_embed"],
                emb, embedding_version, embedding_dim, ch["page_no"], ch["token_count"],
                tokens_for_index(ch["content"]),  # jieba 分词供全文检索
            )).fetchone()[0]
            idx_to_id[ch["chunk_index"]] = cid
            n += 1
        c.commit()
    return n


_HIT_KEYS = ["chunk_id", "parent_chunk_id", "doc_id", "heading_path", "content", "page_no", "score"]


def search(user_id: int, query_vec, top_k: int = 20):
    """向量召回公共知识 + 当前用户私有知识，并在向量排序前完成租户过滤。"""
    if query_vec is None:
        return []
    if len(query_vec) != EMBED_DIM:
        raise ValueError(
            f"query vector length {len(query_vec)}, expected {EMBED_DIM}"
        )
    sql = ("SELECT k.chunk_id, k.parent_chunk_id, k.doc_id, k.heading_path, k.content, k.page_no, "
           "1 - (k.embedding <=> %s::vector) AS score "
           "FROM kb_chunk k JOIN kb_document d ON k.doc_id=d.id "
           "WHERE k.is_retrievable AND (k.user_id IS NULL OR k.user_id=%s) "
           "AND d.deleted_at IS NULL AND k.embedding IS NOT NULL "
           "AND k.embedding_model_version=%s AND k.embedding_dim=%s "
           "ORDER BY k.embedding <=> %s::vector LIMIT %s")
    with conn() as c:
        rows = c.execute(
            sql,
            (
                query_vec,
                user_id,
                EMBED_MODEL_VERSION,
                EMBED_DIM,
                query_vec,
                top_k,
            ),
        ).fetchall()
    return [dict(zip(_HIT_KEYS, r)) for r in rows]


def keyword_search(user_id: int, query: str, top_k: int = 20):
    """关键词召回：对 jieba 分词后的 content_tokens 做 PG 全文检索（补向量对型号/数字/专名/政策的弱项）。
    query 也 jieba 切词、用 OR(|) 组 tsquery 提召回；user_id + deleted_at 预过滤。"""
    terms = query_terms(query)
    if not terms:
        return []
    tsq = " | ".join(terms)        # OR 语义：任一词命中即召回，ts_rank 按命中数排序
    sql = ("SELECT k.chunk_id, k.parent_chunk_id, k.doc_id, k.heading_path, k.content, k.page_no, "
           "ts_rank_cd(to_tsvector('simple', k.content_tokens), to_tsquery('simple', %s)) AS score "
           "FROM kb_chunk k JOIN kb_document d ON k.doc_id=d.id "
           "WHERE k.is_retrievable AND (k.user_id IS NULL OR k.user_id=%s) "
           "AND d.deleted_at IS NULL "
           "AND to_tsvector('simple', k.content_tokens) @@ to_tsquery('simple', %s) "
           "ORDER BY score DESC LIMIT %s")
    with conn() as c:
        rows = c.execute(sql, (tsq, user_id, tsq, top_k)).fetchall()
    return [dict(zip(_HIT_KEYS, r)) for r in rows]


def get_parents_full(parent_ids):
    """取父块全字段 + 文档元数据（来源头用）。返回 {chunk_id: {...}}。"""
    if not parent_ids:
        return {}
    sql = ("SELECT k.chunk_id, k.doc_id, k.chunk_index, k.heading_path, k.content, k.page_no, "
           "d.filename, d.title, d.created_at "
           "FROM kb_chunk k JOIN kb_document d ON k.doc_id=d.id WHERE k.chunk_id = ANY(%s)")
    keys = ["chunk_id", "doc_id", "chunk_index", "heading_path", "content", "page_no",
            "filename", "title", "created_at"]
    with conn() as c:
        rows = c.execute(sql, (list(parent_ids),)).fetchall()
    return {r[0]: dict(zip(keys, r)) for r in rows}


def doc_parent_order(doc_id: int):
    """文档内父块按 chunk_index 的有序 chunk_id 列表（情形B 判相邻用）。"""
    with conn() as c:
        rows = c.execute("SELECT chunk_id FROM kb_chunk WHERE doc_id=%s AND level='parent' "
                         "ORDER BY chunk_index", (doc_id,)).fetchall()
    return [r[0] for r in rows]


def list_documents(user_id: int):
    """列当前用户文档 + 系统公共种子文档（user_id IS NULL）。"""
    with conn() as c:
        rows = c.execute(
            "SELECT id,user_id,filename,status,file_type,source_uri,title,chunk_count,created_at "
            "FROM kb_document WHERE (user_id=%s OR user_id IS NULL) AND deleted_at IS NULL "
            "ORDER BY CASE WHEN user_id IS NULL THEN 0 ELSE 1 END, created_at DESC",
            (user_id,),
        ).fetchall()
    keys = ["id", "user_id", "filename", "status", "file_type", "source_uri",
            "title", "chunk_count", "created_at"]
    return [dict(zip(keys, r)) for r in rows]


def purge_user_documents(user_id: int) -> int:
    """Delete one user's private chunks, metadata and MinIO source objects."""
    with conn() as c:
        rows = c.execute(
            "SELECT id, source_uri FROM kb_document WHERE user_id=%s",
            (user_id,),
        ).fetchall()
        if rows:
            from . import store

            for _, source_uri in rows:
                if source_uri:
                    store.remove_source(source_uri)
            doc_ids = [row[0] for row in rows]
            c.execute("DELETE FROM kb_chunk WHERE doc_id = ANY(%s)", (doc_ids,))
        c.execute("DELETE FROM kb_document WHERE user_id=%s", (user_id,))
        c.commit()
    return len(rows)


def get_chunks(chunk_ids):
    """按 chunk_id 取（父块回填用）。返回 {chunk_id: row dict}。"""
    if not chunk_ids:
        return {}
    with conn() as c:
        rows = c.execute("SELECT chunk_id, doc_id, level, heading_path, content, page_no "
                         "FROM kb_chunk WHERE chunk_id = ANY(%s)", (list(chunk_ids),)).fetchall()
    keys = ["chunk_id", "doc_id", "level", "heading_path", "content", "page_no"]
    return {r[0]: dict(zip(keys, r)) for r in rows}


def embedding_compatibility_stats() -> dict:
    """Return active-vector lineage counts and the pgvector column dimension."""
    with conn() as c:
        vector_type = c.execute(
            """
            SELECT format_type(a.atttypid, a.atttypmod)
            FROM pg_attribute a
            JOIN pg_class t ON t.oid=a.attrelid
            WHERE t.relname='kb_chunk'
              AND a.attname='embedding'
              AND a.attnum > 0
              AND NOT a.attisdropped
            """
        ).fetchone()
        row = c.execute(
            """
            SELECT
              COUNT(*) AS retrievable,
              COUNT(*) FILTER (WHERE k.embedding IS NULL) AS missing,
              COUNT(*) FILTER (
                WHERE k.embedding IS NOT NULL
                  AND (
                    k.embedding_model_version IS NULL
                    OR k.embedding_dim IS NULL
                  )
              ) AS legacy,
              COUNT(*) FILTER (
                WHERE k.embedding IS NOT NULL
                  AND k.embedding_model_version=%s
                  AND k.embedding_dim=%s
              ) AS compatible,
              COUNT(*) FILTER (
                WHERE k.embedding IS NOT NULL
                  AND k.embedding_model_version IS NOT NULL
                  AND k.embedding_dim IS NOT NULL
                  AND (
                    k.embedding_model_version IS DISTINCT FROM %s
                    OR k.embedding_dim IS DISTINCT FROM %s
                  )
              ) AS mismatched
            FROM kb_chunk k
            JOIN kb_document d ON d.id=k.doc_id
            WHERE d.deleted_at IS NULL AND k.is_retrievable
            """,
            (
                EMBED_MODEL_VERSION,
                EMBED_DIM,
                EMBED_MODEL_VERSION,
                EMBED_DIM,
            ),
        ).fetchone()
    vector_type_name = str(vector_type[0]) if vector_type else ""
    match = __import__("re").fullmatch(r"vector\((\d+)\)", vector_type_name)
    column_dim = int(match.group(1)) if match else None
    keys = ("retrievable", "missing", "legacy", "compatible", "mismatched")
    return {
        **{key: int(value or 0) for key, value in zip(keys, row)},
        "column_dim": column_dim,
    }
