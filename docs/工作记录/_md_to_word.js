/**
 * _md_to_word.js —— 把「工作记录」markdown 转成 Word(.docx)，并把 ```mermaid 图渲染成图片嵌进去。
 *
 * 为什么要这个脚本：团队工作记录用 markdown 写（版本友好），但里面的 mermaid 流程图在 Word/预览里
 * 看不到。本脚本用 mermaid-cli(mmdc) 把每个 mermaid 块渲成 PNG，再用 docx 库拼成带图的 Word，
 * 方便直接看图。约定：以后每篇后端跑通文档写完 .md 后都跑一次本脚本生成同名 .docx。
 *
 * 用法（NODE_PATH 指向全局 docx 库）：
 *   NODE_PATH=C:/Users/Lenovo/AppData/Roaming/npm/node_modules \
 *     node docs/工作记录/_md_to_word.js "docs/工作记录/后端/2026-05-22-T4+T7-跑通后端.md"
 * 产物：同目录同名 .docx。
 *
 * 支持的 markdown 子集（够工作记录用）：# ## ### #### 标题、段落、**加粗**、`行内代码`、
 * - 无序列表 / 1. 有序列表、> 引用、| 表格 |、``` 代码块、```mermaid 图。
 */
const fs = require("fs");
const path = require("path");
const { execSync } = require("child_process");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel,
  Table, TableRow, TableCell, WidthType, ImageRun, AlignmentType, ShadingType,
} = require("docx");

const REPO = path.resolve(__dirname, "..", "..");
const MMDC_CFG = path.join(REPO, "docs", "prd", "diagrams", "mmdc.json");
const PUPPET_CFG = path.join(REPO, "docs", "prd", "diagrams", "puppeteer.json");
const MAX_IMG_W = 600; // 页面可用宽约 600px（A4 - 页边距，96dpi）

const mdPath = process.argv[2];
if (!mdPath) { console.error("用法: node _md_to_word.js <markdown 路径>"); process.exit(1); }
const absMd = path.resolve(mdPath);
const outDocx = absMd.replace(/\.md$/i, ".docx");
const tmpDir = path.join(path.dirname(absMd), ".diagrams_tmp");
fs.mkdirSync(tmpDir, { recursive: true });

// ---- PNG 尺寸（从 IHDR 读，避免引第三方依赖）----
function pngSize(file) {
  const b = fs.readFileSync(file);
  return { w: b.readUInt32BE(16), h: b.readUInt32BE(20) };
}

// ---- mermaid → PNG ----
let diagramSeq = 0;
function renderMermaid(code) {
  const id = ++diagramSeq;
  const mmd = path.join(tmpDir, `d${id}.mmd`);
  const png = path.join(tmpDir, `d${id}.png`);
  fs.writeFileSync(mmd, code, "utf8");
  execSync(`mmdc -i "${mmd}" -o "${png}" -c "${MMDC_CFG}" -p "${PUPPET_CFG}" -b white -s 2`,
    { stdio: "pipe" });
  return png;
}

// ---- 行内：**加粗** / `代码` → TextRun[] ----
function parseInline(text) {
  const runs = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let last = 0, m;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) runs.push(new TextRun({ text: text.slice(last, m.index) }));
    const tok = m[0];
    if (tok.startsWith("**")) runs.push(new TextRun({ text: tok.slice(2, -2), bold: true }));
    else runs.push(new TextRun({ text: tok.slice(1, -1), font: "Consolas" }));
    last = re.lastIndex;
  }
  if (last < text.length) runs.push(new TextRun({ text: text.slice(last) }));
  return runs.length ? runs : [new TextRun({ text: "" })];
}

function imageParagraph(png) {
  const { w, h } = pngSize(png);
  const scale = Math.min(1, MAX_IMG_W / w);
  return new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 120, after: 120 },
    children: [new ImageRun({
      type: "png", data: fs.readFileSync(png),
      transformation: { width: Math.round(w * scale), height: Math.round(h * scale) },
    })],
  });
}

function codeParagraph(lines) {
  const kids = [];
  lines.forEach((ln, i) => {
    if (i) kids.push(new TextRun({ break: 1 }));
    kids.push(new TextRun({ text: ln, font: "Consolas", size: 18 }));
  });
  return new Paragraph({
    shading: { type: ShadingType.SOLID, color: "F2F2F2" },
    spacing: { before: 80, after: 80 },
    children: kids,
  });
}

function tableBlock(rows) {
  const cells = rows.map((r) => r.replace(/^\s*\|/, "").replace(/\|\s*$/, "").split("|").map((c) => c.trim()));
  const header = cells[0];
  const body = cells.slice(2); // 跳过分隔行
  const mk = (arr, bold) => new TableRow({
    children: arr.map((c) => new TableCell({
      width: { size: Math.floor(100 / arr.length), type: WidthType.PERCENTAGE },
      shading: bold ? { type: ShadingType.SOLID, color: "E7E6E6" } : undefined,
      children: [new Paragraph({ children: parseInline(c).map((run) => { if (bold) run.bold = true; return run; }) })],
    })),
  });
  return new Table({
    width: { size: 100, type: WidthType.PERCENTAGE },
    rows: [mk(header, true), ...body.map((r) => mk(r, false))],
  });
}

// ---- 主解析 ----
const lines = fs.readFileSync(absMd, "utf8").replace(/\r\n/g, "\n").split("\n");
const children = [];
const HEAD = { 1: HeadingLevel.HEADING_1, 2: HeadingLevel.HEADING_2, 3: HeadingLevel.HEADING_3, 4: HeadingLevel.HEADING_4 };
let i = 0;
while (i < lines.length) {
  const line = lines[i];

  // 代码块 / mermaid
  const fence = line.match(/^```(\w*)/);
  if (fence) {
    const lang = fence[1];
    const buf = [];
    i++;
    while (i < lines.length && !lines[i].startsWith("```")) { buf.push(lines[i]); i++; }
    i++; // 跳过结束 ```
    if (lang === "mermaid") {
      try { children.push(imageParagraph(renderMermaid(buf.join("\n")))); }
      catch (e) { console.error("mermaid 渲染失败，降级为代码块:", e.message); children.push(codeParagraph(buf)); }
    } else {
      children.push(codeParagraph(buf));
    }
    continue;
  }

  // 表格
  if (/^\s*\|.*\|\s*$/.test(line) && i + 1 < lines.length && /^\s*\|[\s:|-]+\|\s*$/.test(lines[i + 1])) {
    const buf = [];
    while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) { buf.push(lines[i]); i++; }
    children.push(tableBlock(buf));
    children.push(new Paragraph({ text: "" }));
    continue;
  }

  // 标题
  const h = line.match(/^(#{1,4})\s+(.*)$/);
  if (h) { children.push(new Paragraph({ heading: HEAD[h[1].length], children: parseInline(h[2]) })); i++; continue; }

  // 引用
  if (line.startsWith(">")) {
    children.push(new Paragraph({ indent: { left: 360 }, children: parseInline(line.replace(/^>\s?/, "")).map((r) => { r.italics = true; return r; }) }));
    i++; continue;
  }

  // 列表
  const ul = line.match(/^(\s*)[-*]\s+(.*)$/);
  const ol = line.match(/^(\s*)\d+\.\s+(.*)$/);
  if (ul) { children.push(new Paragraph({ bullet: { level: Math.floor(ul[1].length / 2) }, children: parseInline(ul[2]) })); i++; continue; }
  if (ol) { children.push(new Paragraph({ numbering: { reference: "num", level: 0 }, children: parseInline(ol[2]) })); i++; continue; }

  // 空行 / 普通段落
  if (line.trim() === "") { i++; continue; }
  children.push(new Paragraph({ children: parseInline(line) }));
  i++;
}

const doc = new Document({
  numbering: { config: [{ reference: "num", levels: [{ level: 0, format: "decimal", text: "%1.", alignment: AlignmentType.START }] }] },
  styles: { default: { document: { run: { font: "Microsoft YaHei", size: 21 } } } },
  sections: [{ children }],
});

Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync(outDocx, buf);
  fs.rmSync(tmpDir, { recursive: true, force: true });
  console.log("✅ 已生成 Word:", outDocx, `(${diagramSeq} 张图已嵌入)`);
});
