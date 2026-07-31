#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给 kb_chunk 回填 content_tokens（jieba 分词），并建中文全文检索 GIN 索引。

为什么：评测发现 PG simple 不切中文→中文 query 全文召回 0→混合召回退化纯向量。
本脚本对现有 chunk 用 jieba 切词写进 content_tokens，让全文检索通道对中文生效（无需重算向量）。
运行：PYTHONUTF8=1 .venv/Scripts/python.exe data/rag_fts_backfill.py
"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.rag import pg
from app.rag.text import tokens_for_index


def main():
    with pg.conn() as c:
        rows = c.execute("SELECT chunk_id, content FROM kb_chunk WHERE content_tokens IS NULL").fetchall()
        print(f"待回填 chunk: {len(rows)}")
        n = 0
        for cid, content in rows:
            c.execute("UPDATE kb_chunk SET content_tokens=%s WHERE chunk_id=%s",
                      (tokens_for_index(content or ""), cid))
            n += 1
            if n % 2000 == 0:
                c.commit(); print(f"  …{n}")
        c.commit()
        print(f"回填完成: {n}")
        # 重建中文全文检索索引（旧 idx_kbchunk_fts 建在未分词的 content 上，换到 content_tokens）
        c.execute("DROP INDEX IF EXISTS idx_kbchunk_fts")
        c.execute("CREATE INDEX idx_kbchunk_fts ON kb_chunk USING gin (to_tsvector('simple', content_tokens))")
        c.commit()
        print("✅ content_tokens GIN 索引已建")
        # 自检
        uid = c.execute("SELECT id FROM users WHERE username='rag_demo'").fetchone()[0]
    for q in ["疲劳驾驶新规", "广东智能网联汽车", "续航"]:
        print(f"  全文召回「{q}」: {len(pg.keyword_search(uid, q, 10))} 条")


if __name__ == "__main__":
    main()
