#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RAG 离线入库管线 E2E 验收（PRD-2 §5 / DoD）。

逐条验：
  1. 带表格的中文 PDF → 解析干净、父子分块入库（含 table chunk、heading_path、page_no）
  2. 子块可按向量相似度检回，并据 parent_chunk_id 换回父块
  3. 引用能带正确页码 + 章节（heading_path + page_no）
  4. 重传同文档不产生重复 chunk（旧版本软删）
  5. 后端①导出的评论语料（data/rag_corpus/）能入库

运行（走 HF 镜像下 BGE 权重，国内更快）：
  HF_ENDPOINT=https://hf-mirror.com PYTHONUTF8=1 .venv/Scripts/python.exe data/rag_ingest_demo.py
"""
import io, json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.rag import pg, ingest, embed

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE_DIR = os.path.join(ROOT, "data", "rag_samples")
os.makedirs(SAMPLE_DIR, exist_ok=True)


def ok(cond, msg):
    print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")
    return cond


# ---------------------------------------------------------------- 造带表格的中文 PDF
def make_sample_pdf() -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    F = "STSong-Light"
    title = ParagraphStyle("t", fontName=F, fontSize=20, leading=26, spaceAfter=14)
    h2 = ParagraphStyle("h2", fontName=F, fontSize=16, leading=22, spaceBefore=12, spaceAfter=8)
    body = ParagraphStyle("b", fontName=F, fontSize=10.5, leading=17, spaceAfter=6)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=20 * mm, bottomMargin=20 * mm)
    el = [
        Paragraph("2025 新能源汽车市场年度报告", title),
        Paragraph("销量概况", h2),
        Paragraph("2025 年中国新能源乘用车市场延续高增长。纯电车型仍是主力，插电混动与增程式增速更快。"
                  "头部车系集中度提升，星愿、Model Y、小米SU7 等长期占据销量榜前列。"
                  "市场整体渗透率持续走高，消费者对续航与智能化的关注度明显上升。", body),
        Paragraph("下表给出 2025 年部分代表车系的年销量与续航上限，供横向对比。", body),
        Table([["车系", "年销量(辆)", "续航上限(km)", "级别"],
               ["星愿", "465775", "410", "小型车"],
               ["Model Y", "425337", "688", "中型SUV"],
               ["小米SU7", "460536", "830", "中大型车"],
               ["理想L6", "387948", "1390", "中大型SUV"]],
              style=TableStyle([
                  ("FONTNAME", (0, 0), (-1, -1), F), ("FONTSIZE", (0, 0), (-1, -1), 10),
                  ("GRID", (0, 0), (-1, -1), 0.6, colors.black),
                  ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                  ("ALIGN", (1, 0), (-1, -1), "CENTER")])),
        Spacer(1, 10),
        Paragraph("价格分析", h2),
        Paragraph("价格带方面，10-20 万元区间竞争最激烈，是走量主力区间。20-30 万元区间由 Model Y、"
                  "小米SU7 等支撑。30 万元以上高端市场由理想、问界等占据，增程式在中大型 SUV 上优势明显。"
                  "经销商终端折扣对实际成交价影响较大，指导价与成交价存在差异。", body),
    ]
    doc.build(el)
    pdf = buf.getvalue()
    with open(os.path.join(SAMPLE_DIR, "市场报告_sample.pdf"), "wb") as f:
        f.write(pdf)
    return pdf


def ensure_pg_user(username="rag_demo") -> int:
    """RAG 的 kb_document.user_id 外键指向 PG users(id)；验收先确保该用户在 PG 存在。"""
    with pg.conn() as c:
        c.execute("INSERT INTO users(username,password_hash) VALUES(%s,'x') "
                  "ON CONFLICT(username) DO NOTHING", (username,))
        c.commit()
        return c.execute("SELECT id FROM users WHERE username=%s", (username,)).fetchone()[0]


def count_chunks(user_id, filename):
    with pg.conn() as c:
        return c.execute(
            "SELECT count(*) FROM kb_chunk k JOIN kb_document d ON k.doc_id=d.id "
            "WHERE d.user_id=%s AND d.filename=%s AND d.deleted_at IS NULL", (user_id, filename)).fetchone()[0]


def main():
    uid = ensure_pg_user()
    print(f"PG 测试用户 id={uid}")

    # ============ 1) 带表格 PDF 入库 ============
    print("\n=== 1) 带表格 PDF 解析 + 父子分块入库 ===")
    pdf = make_sample_pdf()
    doc_id = ingest.ingest_bytes(uid, "市场报告.pdf", pdf, "pdf", title="2025新能源市场年度报告")
    doc = pg.get_document(doc_id)
    with pg.conn() as c:
        rows = c.execute("SELECT level,chunk_type,heading_path,page_no,token_count,"
                         "(embedding IS NOT NULL) has_emb FROM kb_chunk WHERE doc_id=%s "
                         "ORDER BY chunk_index", (doc_id,)).fetchall()
    parents = [r for r in rows if r[0] == "parent"]
    children = [r for r in rows if r[0] == "child"]
    tables = [r for r in rows if r[1] == "table"]
    ok(doc["status"] == "ready", f"文档 status=ready（实际 {doc['status']}）")
    ok(len(parents) >= 2 and len(children) >= 2, f"父块={len(parents)} 子块={len(children)}")
    ok(len(tables) >= 1, f"表格成块 table chunk={len(tables)}（表格整体保留）")
    ok(all(r[5] for r in children), "所有子块有 embedding")
    ok(all(not r[5] for r in parents), "所有父块无 embedding（不进检索）")
    ok(all(r[2] for r in children), "子块都带 heading_path（标题增强/溯源）")
    ok(all(r[4] <= 512 for r in rows), f"所有 chunk token<=512（max={max(r[4] for r in rows)}）")
    # 表格内容确实抽到了
    with pg.conn() as c:
        tbl_txt = c.execute("SELECT content FROM kb_chunk WHERE doc_id=%s AND chunk_type='table' LIMIT 1",
                            (doc_id,)).fetchone()[0]
    ok("Model Y" in tbl_txt and "425337" in tbl_txt, "表格数据解析干净（含 Model Y/425337）")

    # ============ 2)+3) 向量检回子块 → 换父块 → 引用页码+章节 ============
    print("\n=== 2)+3) 向量检索子块 → parent_chunk_id 换父块 → 引用页码+章节 ===")
    q = "纯电和增程车型的续航大概多少"
    hits = pg.search(uid, embed.embed_query(q), top_k=3)
    ok(len(hits) >= 1, f"查询「{q}」检回 {len(hits)} 个子块")
    top = hits[0]
    print(f"    命中子块 score={top['score']:.3f} 章节=「{top['heading_path']}」 页码={top['page_no']}")
    print(f"    子块内容: {top['content'][:60]}...")
    parent = pg.get_chunks([top["parent_chunk_id"]]).get(top["parent_chunk_id"]) if top["parent_chunk_id"] else None
    ok(parent is not None and parent["level"] == "parent", "据 parent_chunk_id 换回父块")
    if parent:
        print(f"    父块(回填上下文) 页码={parent['page_no']} 长度={len(parent['content'])}字")
    ok(bool(top["heading_path"]) and top["page_no"] is not None, "引用带正确章节 + 页码")

    # ============ 4) 重传不产生重复 chunk ============
    print("\n=== 4) 重传同文档不产生重复 chunk（旧版本软删）===")
    before = count_chunks(uid, "市场报告.pdf")
    ingest.ingest_bytes(uid, "市场报告.pdf", pdf, "pdf", title="重传")
    after = count_chunks(uid, "市场报告.pdf")
    with pg.conn() as c:
        live_docs = c.execute("SELECT count(*) FROM kb_document WHERE user_id=%s AND filename=%s "
                              "AND deleted_at IS NULL", (uid, "市场报告.pdf")).fetchone()[0]
    ok(after == before, f"重传后活跃 chunk 数不变（{before}→{after}，无重复）")
    ok(live_docs == 1, f"同名活跃文档仅 1 个（旧版本已软删），实际 {live_docs}")

    # ============ 5) 评论语料入库 ============
    print("\n=== 5) 后端①导出的评论语料能入库 ===")
    corpus = os.path.join(ROOT, "data", "rag_corpus", "dongchedi_koubei_reviews.jsonl")
    if not os.path.exists(corpus):
        print("    跳过：未找到评论语料（先跑 data/export_rag_corpus.py）")
    else:
        # 取一个车系的评论，拼成一篇 Markdown 文档入库（heading=车系名，每条评论一段）
        target_sid, revs = None, []
        for line in open(corpus, encoding="utf-8"):
            r = json.loads(line)
            if target_sid is None:
                target_sid = r["series_id"]
            if r["series_id"] == target_sid:
                revs.append(r)
            elif len(revs) >= 8:
                break
        name = revs[0]["series_name"]
        md = f"# {name} 车主口碑\n\n" + "\n\n".join(
            f"## 车主点评 {i+1}（{rv['metadata'].get('location') or '—'}）\n\n{rv['text']}"
            for i, rv in enumerate(revs))
        cid = ingest.ingest_bytes(uid, f"koubei_{name}.md", md.encode("utf-8"), "md",
                                  title=f"{name}口碑语料")
        cdoc = pg.get_document(cid)
        with pg.conn() as c:
            cn = c.execute("SELECT count(*) FROM kb_chunk WHERE doc_id=%s", (cid,)).fetchone()[0]
        ok(cdoc["status"] == "ready" and cn > 0, f"评论语料入库 status={cdoc['status']} chunks={cn}（车系={name}）")
        hits2 = pg.search(uid, embed.embed_query(f"{name} 这车开起来怎么样"), top_k=2)
        ok(len(hits2) >= 1, f"评论语料可被检回（{len(hits2)} 命中）")

    print("\n✅ 验收脚本跑完。")


if __name__ == "__main__":
    main()
