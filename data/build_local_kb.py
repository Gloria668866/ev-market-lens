"""种子语料灌本地向量库 → 前端离线语料导出。
运行一次即可（幂等：同文件名会 supersede）。依赖 jieba；sentence-transformers 可选（无则纯词法）。
用法：python data/build_local_kb.py
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.rag.local_ingest import ingest_bytes
from app.rag.local_store import init_store, list_documents, get_document, get_chunks, stats

SEED_DIR = Path(__file__).parent / "seed_kb"
CORPUS_OUT = Path(__file__).parent.parent / "frontend" / "src" / "api" / "kb_corpus.json"


def build():
    if not SEED_DIR.exists():
        print(f"[skip] 种子语料目录不存在：{SEED_DIR}")
        return

    init_store()
    files = sorted(SEED_DIR.glob("*.md"))
    print(f"种子语料 {len(files)} 篇 → 入库（public=True，公共底座）\n")

    for fp in files:
        data = fp.read_bytes()
        title = fp.stem
        try:
            doc_id, n = ingest_bytes(user_id=None, filename=fp.name, data=data,
                                     file_type="md", title=title, public=True)
            print(f"  ✅ {fp.name}  →  doc_id={doc_id}  {n} chunks")
        except Exception as e:
            print(f"  ❌ {fp.name}  →  {e}")

    d, k = stats()
    print(f"\n知识库：{d} 文档 / {k} chunks")

    # 导出前端离线语料（mock 模式用）
    export_corpus()


def export_corpus():
    """把种子文档 + chunks 导出为前端 mock 可用的 JSON（真实词法检索用）。"""
    docs = list_documents(user_id=None)  # 公共文档
    corpus = []
    for d in docs:
        doc = get_document(d["id"])
        if not doc:
            continue
        # 取该文档的所有可检索子块
        chunks = []
        try:
            raw = get_chunks_by_doc(d["id"])
            for c in raw:
                chunks.append({
                    "chunk_id": c.get("chunk_id"),
                    "content": c.get("content", ""),
                    "heading_path": c.get("heading_path", ""),
                    "page_no": c.get("page_no", 1),
                })
        except Exception:
            pass
        corpus.append({
            "id": doc["id"],
            "filename": doc["filename"],
            "title": doc.get("title") or doc["filename"],
            "file_type": doc.get("file_type", "md"),
            "status": doc.get("status", "ready"),
            "chunks": chunks,
        })

    CORPUS_OUT.parent.mkdir(parents=True, exist_ok=True)
    CORPUS_OUT.write_text(json.dumps(corpus, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n前端离线语料导出 → {CORPUS_OUT}  ({len(corpus)} 文档)")


def get_chunks_by_doc(doc_id):
    """取某文档的所有子块（供导出）"""
    from app.rag.local_store import _conn
    init_store()
    with _conn() as c:
        rows = c.execute(
            "SELECT chunk_id, content, heading_path, page_no FROM kb_chunk "
            "WHERE doc_id=? AND is_retrievable=1 ORDER BY chunk_index", (doc_id,)
        ).fetchall()
    return [dict(r) for r in rows]


if __name__ == "__main__":
    build()
