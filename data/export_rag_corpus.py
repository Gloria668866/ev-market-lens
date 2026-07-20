"""从口碑评论导出 RAG 语料（JSONL 格式，供后续灌库或分析）。

用法：python data/export_rag_corpus.py
产物：data/rag_corpus/dongchedi_koubei_reviews.jsonl
依赖：需先跑过 crawl_koubei.py 采集，且 bi_demo.db 已有数据
"""
import json
import sqlite3
from pathlib import Path

DB_FILE = Path(__file__).parent.parent / "bi_demo.db"
OUT_DIR = Path(__file__).parent / "rag_corpus"


def export_synthetic():
    """当前 bi_demo.db 中的口碑数据是 seed 生成的、无评论文本。
    从 seed_kb/08-口碑精选 中提取内容作为语料导出。"""
    seed_file = Path(__file__).parent / "seed_kb" / "08-口碑精选-热门车系点评.md"
    if not seed_file.exists():
        print(f"[skip] 种子口碑文件不存在：{seed_file}")
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    text = seed_file.read_text(encoding="utf-8")
    out_file = OUT_DIR / "dongchedi_koubei_reviews.jsonl"
    count = 0

    with out_file.open("w", encoding="utf-8") as f:
        # 按 ## 分车系，提取引号内的口碑文本
        sections = text.split("## ")
        for sec in sections:
            lines = sec.strip().split("\n")
            if not lines or not lines[0]:
                continue
            series_name = lines[0].strip()

            # 找「典型口碑」段落中的引号文本
            for line in lines:
                if "「" in line or "」" in line or "\"" in line:
                    quotes = []
                    for q in re.findall(r'["「]([^"」]{30,})["」]', line):
                        quotes.append(q)
                    if not quotes:
                        continue
                    for quote in quotes:
                        f.write(json.dumps({
                            "series": series_name,
                            "content": quote.strip(),
                            "source": "seed_koubei",
                        }, ensure_ascii=False) + "\n")
                        count += 1

    print(f"RAG 语料导出：{count} 条 → {out_file}")


import re


if __name__ == "__main__":
    export_synthetic()
