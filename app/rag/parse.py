"""可插拔文档解析器：PDF/HTML/纯文本 → 结构化块（保留标题层级、表格、页码）。

设计（PRD-2 §5.2）：解析的产物是「带结构的块序列」，给后面「结构感知切块」和「引用溯源」打底：
  block = {"type": "heading"|"text"|"table", "text": str, "level": int,
           "heading_path": [str,...], "page_no": int}
  - heading 块：更新标题栈；level=标题深度（1=最大标题）。
  - text/table 块：携带当前 heading_path（祖先标题路径），table 文本渲染成 Markdown 表。

为什么可插拔 + MinerU 留接口：MinerU(CPU) 多 GB、Windows 上难装；先用 PyMuPDF/pdfplumber 轻量实现
（秒装、稳定、足够「带表格 PDF」），把解析器抽象成 `parse_document()` 一个入口，
日后 `PARSER_BACKEND=mineru` 想换随时换，下游分块/向量化零改动。
"""
import os
import re
from collections import Counter
from html.parser import HTMLParser

PARSER_BACKEND = os.getenv("PARSER_BACKEND", "lite")   # lite=PyMuPDF/pdfplumber；mineru=留待接入


# ---------------------------------------------------------------- 表格渲染
def _table_to_markdown(rows) -> str:
    rows = [[("" if c is None else str(c).replace("\n", " ").strip()) for c in r] for r in rows if r]
    if not rows:
        return ""
    head = rows[0]
    md = ["| " + " | ".join(head) + " |", "| " + " | ".join(["---"] * len(head)) + " |"]
    for r in rows[1:]:
        if len(r) < len(head):
            r = r + [""] * (len(head) - len(r))
        md.append("| " + " | ".join(r[:len(head)]) + " |")
    return "\n".join(md)


# ---------------------------------------------------------------- PDF（pdfplumber）
def _parse_pdf(data: bytes):
    import io
    import pdfplumber

    blocks = []
    heading_stack = []           # [(level, text)]，维护当前祖先标题路径
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        # 先扫一遍定「正文字号」：行字号众数 = 正文，明显更大的 = 标题
        line_sizes = []
        pages_lines = []
        for page in pdf.pages:
            lines = _page_lines(page)
            pages_lines.append((page, lines))
            line_sizes += [round(l["size"]) for l in lines if l["text"].strip()]
        body_size = Counter(line_sizes).most_common(1)[0][0] if line_sizes else 10
        # 标题字号分级（从大到小 → level 1,2,3...）
        big = sorted({s for s in line_sizes if s >= body_size * 1.25}, reverse=True)
        size_level = {s: i + 1 for i, s in enumerate(big[:4])}

        for pno, (page, lines) in enumerate(pages_lines, 1):
            tables = page.find_tables()
            table_boxes = [t.bbox for t in tables]
            # 表格块（按 top 排序插入）
            items = []
            for t in tables:
                items.append(("table", t.bbox[1], _table_to_markdown(t.extract())))
            # 正文行（排除落在表格框内的）
            for l in lines:
                if any(_inside(l, b) for b in table_boxes):
                    continue
                txt = l["text"].strip()
                if not txt:
                    continue
                lvl = size_level.get(round(l["size"]))
                items.append(("heading" if lvl else "text", l["top"], txt, lvl))
            items.sort(key=lambda x: x[1])         # 按页内纵坐标恢复阅读顺序

            for it in items:
                if it[0] == "table":
                    blocks.append({"type": "table", "text": it[2], "level": len(heading_stack),
                                   "heading_path": [h[1] for h in heading_stack], "page_no": pno})
                elif it[0] == "heading":
                    lvl = it[3]
                    while heading_stack and heading_stack[-1][0] >= lvl:
                        heading_stack.pop()
                    heading_stack.append((lvl, it[2]))
                    blocks.append({"type": "heading", "text": it[2], "level": lvl,
                                   "heading_path": [h[1] for h in heading_stack], "page_no": pno})
                else:
                    blocks.append({"type": "text", "text": it[2], "level": len(heading_stack),
                                   "heading_path": [h[1] for h in heading_stack], "page_no": pno})
    return blocks


def _page_lines(page):
    """把 page 的词按行(top 相近)聚合，返回 [{text,size,top}]。"""
    words = page.extract_words(extra_attrs=["size"]) if page.extract_words else []
    rows = {}
    for w in words:
        key = round(w["top"])
        rows.setdefault(key, []).append(w)
    out = []
    for top in sorted(rows):
        ws = sorted(rows[top], key=lambda w: w["x0"])
        out.append({"text": " ".join(w["text"] for w in ws),
                    "size": max(w.get("size", 10) for w in ws),
                    "top": top, "x0": min(w["x0"] for w in ws)})
    return out


def _inside(line, bbox):
    x0, top0, x1, bottom1 = bbox
    return top0 - 2 <= line["top"] <= bottom1 + 2


# ---------------------------------------------------------------- HTML（stdlib）
class _HTMLBlocks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.blocks, self.stack, self._buf, self._tag = [], [], [], None

    def handle_starttag(self, tag, attrs):
        if tag in ("h1", "h2", "h3", "h4", "p", "li", "td", "th"):
            self._flush(); self._tag = tag

    def handle_endtag(self, tag):
        if tag in ("h1", "h2", "h3", "h4", "p", "li", "td", "th"):
            self._flush()

    def handle_data(self, data):
        if self._tag:
            self._buf.append(data)

    def _flush(self):
        if not self._tag:
            return
        text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
        self._buf = []
        if text:
            if self._tag in ("h1", "h2", "h3", "h4"):
                lvl = int(self._tag[1])
                while self.stack and self.stack[-1][0] >= lvl:
                    self.stack.pop()
                self.stack.append((lvl, text))
                self.blocks.append({"type": "heading", "text": text, "level": lvl,
                                    "heading_path": [h[1] for h in self.stack], "page_no": 1})
            else:
                self.blocks.append({"type": "text", "text": text, "level": len(self.stack),
                                    "heading_path": [h[1] for h in self.stack], "page_no": 1})
        self._tag = None


def _parse_html(data: bytes):
    p = _HTMLBlocks()
    p.feed(data.decode("utf-8", "replace"))
    p._flush()
    return p.blocks


# ---------------------------------------------------------------- 纯文本/Markdown
def _parse_text(data: bytes):
    """纯文本/Markdown：# 开头当标题，空行分段。"""
    blocks, stack = [], []
    for raw in data.decode("utf-8", "replace").split("\n\n"):
        seg = raw.strip()
        if not seg:
            continue
        m = re.match(r"^(#{1,4})\s+(.*)", seg)
        if m:
            lvl = len(m.group(1)); text = m.group(2).strip()
            while stack and stack[-1][0] >= lvl:
                stack.pop()
            stack.append((lvl, text))
            blocks.append({"type": "heading", "text": text, "level": lvl,
                           "heading_path": [h[1] for h in stack], "page_no": 1})
        else:
            blocks.append({"type": "text", "text": seg, "level": len(stack),
                           "heading_path": [h[1] for h in stack], "page_no": 1})
    return blocks


# ---------------------------------------------------------------- 统一入口
def parse_document(data: bytes, file_type: str):
    """原始字节 → 结构化块序列。file_type: pdf/html/text/md。"""
    if PARSER_BACKEND == "mineru":
        # 留接口：装好 MinerU 后在此调用 magic_pdf，产物同样转成上面的 block 结构即可，下游零改动。
        raise NotImplementedError("MinerU 后端待接入；当前用 PARSER_BACKEND=lite")
    ft = (file_type or "").lower()
    if ft == "pdf":
        return _parse_pdf(data)
    if ft in ("html", "htm"):
        return _parse_html(data)
    return _parse_text(data)        # text / md / 其它按纯文本
