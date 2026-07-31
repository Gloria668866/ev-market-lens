#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建企业级 RAG 知识库：多页研报 PDF + 乘联会种子文章(HTML/md) + 全量口碑语料 → 入库。

把三类真实/多格式语料灌进 kb_chunk（父子分块 + 向量），给在线检索（retrieve.py）提供有体量的库：
  ① 多页年度报告 PDF（多章节/多表格/跨页，代表「上传的研报」）
  ② 乘联会种子文章 data/rag_samples/seed/*.md（crawl_seed_corpus.py 爬的真实行业新闻/政策）
  ③ 全量懂车帝口碑语料（data/rag_corpus/，按车系成文档，UGC 口碑）

运行：HF_HUB_OFFLINE=1 PYTHONUTF8=1 .venv/Scripts/python.exe data/rag_build_kb.py [口碑车系上限]
"""
import io, json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.rag import pg, ingest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEED_DIR = os.path.join(ROOT, "data", "rag_samples", "seed")
CORPUS = os.path.join(ROOT, "data", "rag_corpus", "dongchedi_koubei_reviews.jsonl")
DEMO_USER = "rag_demo"


def ensure_user():
    with pg.conn() as c:
        c.execute("INSERT INTO users(username,password_hash) VALUES(%s,'x') "
                  "ON CONFLICT(username) DO NOTHING", (DEMO_USER,))
        c.commit()
        return c.execute("SELECT id FROM users WHERE username=%s", (DEMO_USER,)).fetchone()[0]


# ---------------------------------------------------------------- 多页研报 PDF
def make_report_pdf() -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    F = "STSong-Light"
    H1 = ParagraphStyle("h1", fontName=F, fontSize=20, leading=26, spaceAfter=14)
    H2 = ParagraphStyle("h2", fontName=F, fontSize=15, leading=21, spaceBefore=12, spaceAfter=8)
    BODY = ParagraphStyle("b", fontName=F, fontSize=10.5, leading=17, spaceAfter=6)

    def tbl(data, aligns="CENTER"):
        return Table(data, style=TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), F), ("FONTSIZE", (0, 0), (-1, -1), 9.5),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef5")),
            ("ALIGN", (1, 0), (-1, -1), aligns)]))

    el = [Paragraph("2025 中国新能源汽车市场年度报告", H1),
          Paragraph("本报告基于懂车帝公开销量榜与口碑数据整理，涵盖销量格局、价格带、续航与技术、"
                    "渠道与政策影响及 2026 展望，供行业研究参考。", BODY),

          Paragraph("一、销量总览", H2),
          Paragraph("2025 年新能源乘用车延续高增长，纯电仍是主力，插混与增程增速更快。头部车系集中度提升，"
                    "星愿、小米SU7、Model Y、理想L6 长期位居销量榜前列。", BODY),
          tbl([["车系", "年销量(辆)", "动力", "级别"],
               ["星愿", "465,775", "纯电", "小型车"],
               ["小米SU7", "460,536", "纯电", "中大型车"],
               ["Model Y", "425,337", "纯电", "中型SUV"],
               ["理想L6", "387,948", "增程", "中大型SUV"]]),
          Paragraph("从能源结构看，纯电占比约六成，插混与增程合计约四成且份额持续上行，反映用户对补能"
                    "便利与长途场景的诉求。", BODY),

          Paragraph("二、品牌格局", H2),
          Paragraph("自主新势力与传统自主新能源品牌主导市场，合资品牌加速电动化追赶。比亚迪系、吉利银河、"
                    "理想、小米、鸿蒙智行等构成第一梯队。", BODY),
          tbl([["品牌阵营", "代表", "特征"],
               ["新势力", "理想/蔚来/小鹏/小米", "智能化与用户运营强"],
               ["传统自主", "比亚迪/吉利银河/长安深蓝", "规模与供应链优势"],
               ["合资", "大众/丰田", "电动化转型中"]], aligns="LEFT"),
          PageBreak(),

          Paragraph("三、价格带分析", H2),
          Paragraph("10-20 万元区间竞争最激烈，是走量主力；20-30 万元由 Model Y、小米SU7 等支撑；"
                    "30 万元以上高端市场由理想、问界等占据，增程在中大型 SUV 优势明显。"
                    "经销商终端折扣对成交价影响较大，指导价与成交价存在差异。", BODY),
          tbl([["价格带(万元)", "竞争强度", "代表车系"],
               ["10-20", "极高", "星愿/秦PLUS/元UP"],
               ["20-30", "高", "Model Y/小米SU7"],
               ["30以上", "中", "理想L系/问界M系"]], aligns="LEFT"),

          Paragraph("四、续航与技术趋势", H2),
          Paragraph("主流纯电车型续航上限普遍进入 600-800km，部分旗舰超 1000km。800V 高压平台、"
                    "磷酸铁锂与三元锂并行、超快充网络扩张是 2025 年技术主线。智能驾驶辅助成为购车决策"
                    "的重要权重。", BODY),
          tbl([["技术方向", "现状", "趋势"],
               ["续航", "600-800km 主流", "向 1000km 与快充并重"],
               ["电池", "磷酸铁锂为主", "兼顾安全与成本"],
               ["平台", "800V 渗透", "快充体验提升"]], aligns="LEFT"),
          PageBreak(),

          Paragraph("五、渠道与口碑", H2),
          Paragraph("直营与经销并行，新势力以直营+商超店触达用户。用户口碑中，外观、空间、智能化得分较高，"
                    "对续航达成率与售后体验关注度上升。口碑总分多在 4.0 分以上(满分5)。", BODY),

          Paragraph("六、政策影响", H2),
          Paragraph("购置税减免延续、双积分政策、地方补贴与牌照政策是新能源市场的关键变量。充电基础设施"
                    "建设持续加码，截至 2025 年底充电桩规模大幅增长，缓解补能焦虑。", BODY),

          Paragraph("七、2026 展望", H2),
          Paragraph("预计 2026 年新能源渗透率进一步提升，增程与插混在中大型车继续放量，"
                    "智能化与补能体验成为竞争焦点；价格战趋于理性，头部集中度或进一步提高。", BODY)]

    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, topMargin=18 * mm, bottomMargin=18 * mm).build(el)
    return buf.getvalue()


def main():
    limit = next((int(a) for a in sys.argv[1:] if a.isdigit()), None)   # 口碑车系上限(None=全量)
    uid = ensure_user()
    print(f"知识库归属用户 id={uid}（{DEMO_USER}）")

    # ① 多页研报 PDF
    print("\n[1] 多页年度报告 PDF…")
    did = ingest.ingest_bytes(uid, "2025新能源汽车市场年度报告.pdf", make_report_pdf(), "pdf",
                              title="2025中国新能源汽车市场年度报告")
    print(f"    入库 doc_id={did}")

    # ② 乘联会种子文章
    print("\n[2] 乘联会种子文章(md)…")
    n_seed = 0
    if os.path.isdir(SEED_DIR):
        for fn in sorted(os.listdir(SEED_DIR)):
            if not fn.endswith(".md"):
                continue
            data = open(os.path.join(SEED_DIR, fn), encoding="utf-8").read().encode("utf-8")
            title = data.decode("utf-8").splitlines()[0].lstrip("# ").strip()
            try:
                ingest.ingest_bytes(uid, fn, data, "md", title=title)
                n_seed += 1
            except Exception as e:
                print(f"    跳过 {fn}: {str(e)[:50]}")
    print(f"    入库 {n_seed} 篇")

    # ③ 全量口碑语料（按车系成文档）
    print("\n[3] 懂车帝口碑语料(按车系)…")
    by_series = {}
    if os.path.exists(CORPUS):
        for line in open(CORPUS, encoding="utf-8"):
            r = json.loads(line)
            by_series.setdefault((r["series_id"], r["series_name"]), []).append(r)
    series_items = list(by_series.items())
    if limit:
        series_items = series_items[:limit]
    n_kou = 0
    for (sid, name), revs in series_items:
        md = f"# {name} 车主口碑\n\n" + "\n\n".join(
            f"## 车主点评 {i+1}（{rv['metadata'].get('location') or '—'}｜{rv['metadata'].get('bought_time') or '—'}）"
            f"\n\n{rv['text']}" for i, rv in enumerate(revs))
        try:
            ingest.ingest_bytes(uid, f"koubei_{name}_{sid}.md", md.encode("utf-8"), "md",
                                title=f"{name}车主口碑")
            n_kou += 1
            if n_kou % 20 == 0:
                print(f"    …已入库 {n_kou} 车系")
        except Exception as e:
            print(f"    跳过 {name}: {str(e)[:50]}")
    print(f"    入库 {n_kou} 车系口碑文档")

    # 汇总
    with pg.conn() as c:
        docs = c.execute("SELECT count(*) FROM kb_document WHERE user_id=%s AND deleted_at IS NULL", (uid,)).fetchone()[0]
        chunks = c.execute("SELECT count(*) FROM kb_chunk WHERE user_id=%s", (uid,)).fetchone()[0]
        children = c.execute("SELECT count(*) FROM kb_chunk WHERE user_id=%s AND is_retrievable", (uid,)).fetchone()[0]
    print(f"\n✅ 知识库构建完成：文档={docs}，chunk={chunks}（子块={children}，有向量可检索）")


if __name__ == "__main__":
    main()
