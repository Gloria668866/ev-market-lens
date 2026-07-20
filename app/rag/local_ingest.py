"""本地（免 Celery/MinIO/PG）同步入库：解析 → 结构感知父子分块 → BGE 向量化 → 写 local_store。

复用既有 chunk.build_chunks 与 embed（BGE），只把"存哪"换成 SQLite。用于：
- 种子语料一次性灌库（data/build_local_kb.py，public=True 公共可见）；
- RAG_BACKEND=local 时用户上传的同步入库（app/kb.py，归属上传用户）。
"""
import os
import re

from . import embed, local_store as store
from .chunk import build_chunks


def _stem(filename: str) -> str:
    return os.path.splitext(os.path.basename(filename or "文档"))[0]


def _parse_markdown(text: str):
    """Markdown → blocks（# 标题分节、空行分段；表格按文本处理）。heading_path 为标题栈。"""
    blocks, stack, buf = [], [], []
    section_no, cur_page = 0, 1
    cur_path = []

    def flush():
        nonlocal buf
        para = "\n".join(buf).strip()
        if para:
            blocks.append({"type": "text", "heading_path": list(cur_path), "text": para, "page_no": cur_page})
        buf = []

    for raw in text.splitlines():
        m = re.match(r"^(#{1,4})\s+(.*)$", raw.strip())
        if m:
            flush()
            level, title = len(m.group(1)), m.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            cur_path = [t for _, t in stack]
            section_no += 1
            cur_page = section_no
            blocks.append({"type": "heading", "heading_path": list(cur_path), "text": title, "page_no": cur_page})
        elif not raw.strip():
            flush()
        else:
            buf.append(raw)
    flush()
    return blocks


def _parse_text(text: str, title: str):
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    return [{"type": "text", "heading_path": [title], "text": p, "page_no": 1} for p in paras]


def _parse_pdf(data: bytes, title: str):
    import fitz  # pymupdf
    blocks = []
    doc = fitz.open(stream=data, filetype="pdf")
    for i, page in enumerate(doc, 1):
        txt = page.get_text().strip()
        if txt:
            blocks.append({"type": "text", "heading_path": [title], "text": txt, "page_no": i})
    return blocks


def parse_blocks(data, file_type: str, filename: str):
    title = _stem(filename)
    if file_type == "pdf":
        return _parse_pdf(data, title)
    text = data.decode("utf-8", errors="ignore") if isinstance(data, (bytes, bytearray)) else str(data)
    if file_type in ("md", "markdown"):
        return _parse_markdown(text)
    return _parse_text(text, title)   # txt / html(粗) 等


def ingest_bytes(user_id, filename, data, file_type, title=None, public=False):
    """同步入库一份文档，返回 (doc_id, chunk_count)。public=True → user_id 存 NULL（公共种子库）。"""
    owner = None if public else user_id
    doc_id = store.create_document(owner, filename, file_type, title=title or filename)
    try:
        blocks = parse_blocks(data, file_type, filename)
        chunks = build_chunks(blocks, count_tokens=embed.count_tokens)
        children = [c for c in chunks if c["is_retrievable"]]
        vecs = embed.embed_passages([c["content_embed"] for c in children]) if children else []
        emb_by_idx = {c["chunk_index"]: v for c, v in zip(children, vecs)}
        n = store.insert_chunks(doc_id, owner, chunks, emb_by_idx)
        store.set_status(doc_id, "ready", chunk_count=n)
        return doc_id, n
    except Exception:
        store.set_status(doc_id, "failed")
        raise
