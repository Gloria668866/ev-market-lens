"""入库编排：把一个文档变成可检索的父子分块向量。

流程（PRD-2 §5.2，五步）：
  存 MinIO → 解析(parse) → 父子分块(chunk) → BGE 向量化(只给子块) → 写 kb_chunk → kb_document.status=ready
  任一步抛错 → status=failed（前端轮询能看到）。

两个入口：
  ingest_bytes(...)  上传/拉取场景：先存 MinIO + 建 kb_document(parsing)，再 ingest_document。
  ingest_document(doc_id)  纯解析入库（Celery 任务调它）；幂等：失败可重跑（重跑前调用方应已软删旧 chunk）。
"""
from . import store, pg, embed
from .parse import parse_document
from .chunk import build_chunks


def ingest_document(doc_id: int) -> dict:
    """对已建档(status=parsing)的文档跑解析→分块→向量化→写库。返回统计。"""
    doc = pg.get_document(doc_id)
    if doc is None:
        raise ValueError(f"kb_document {doc_id} 不存在")
    try:
        data = store.get_bytes(doc["source_uri"])
        blocks = parse_document(data, doc["file_type"])
        if not blocks:
            raise ValueError("解析得到 0 个内容块（空文档或解析失败）")
        chunks = build_chunks(blocks, count_tokens=embed.count_tokens)

        # 只给子块(is_retrievable)算 embedding；父块不算（§5.3.2）
        children = [c for c in chunks if c["is_retrievable"]]
        vecs = embed.embed_passages([c["content_embed"] for c in children])
        emb_by_index = {c["chunk_index"]: v for c, v in zip(children, vecs)}

        n = pg.insert_chunks(doc_id, doc["user_id"], chunks, emb_by_index)
        pg.set_status(doc_id, "ready", chunk_count=n)
        return {"doc_id": doc_id, "blocks": len(blocks), "chunks": n,
                "children": len(children), "parents": n - len(children), "status": "ready"}
    except Exception as e:
        pg.set_status(doc_id, "failed")
        raise RuntimeError(f"ingest 文档 {doc_id} 失败：{e}") from e


def ingest_bytes(user_id: int, filename: str, data: bytes, file_type: str,
                 title: str = None, content_type="application/octet-stream") -> int:
    """存 MinIO + 建档(parsing) + 同步入库。返回 doc_id。（API 走 Celery 时只做前两步再异步）"""
    source_uri = store.put_bytes(user_id, filename, data, content_type)
    doc_id = pg.create_document(user_id, filename, file_type, source_uri, title=title)
    ingest_document(doc_id)
    return doc_id


def stage_for_async(user_id: int, filename: str, data: bytes, file_type: str, title: str = None):
    """上传 API 用：只存 MinIO + 建档(parsing)，返回 doc_id，解析交 Celery 异步。"""
    source_uri = store.put_bytes(user_id, filename, data)
    return pg.create_document(user_id, filename, file_type, source_uri, title=title)
