/* 生成《PRD-1 数据获取与处理》Word 文档 */
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, LevelFormat, HeadingLevel, BorderStyle,
  WidthType, ShadingType, VerticalAlign, PageNumber, PageBreak, ImageRun,
  TableOfContents, TabStopType, TabStopPosition,
} = require("docx");

const DIR = __dirname;
const DIAG = path.join(DIR, "diagrams");
const CONTENT_W = 9360; // US Letter, 1" margins

// ---------- helpers ----------
const FONT = "Microsoft YaHei"; // 中文字体
const BLUE = "1F4E79", LIGHT = "D6E4F0", GREY = "F2F2F2", HEADc = "BDD7EE";

function h1(t) {
  return new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun(t)] });
}
function h2(t) {
  return new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun(t)] });
}
function h3(t) {
  return new Paragraph({ heading: HeadingLevel.HEADING_3, children: [new TextRun(t)] });
}
function p(t, opts = {}) {
  const runs = Array.isArray(t) ? t : [new TextRun(t)];
  return new Paragraph({ spacing: { after: 120, line: 300 }, children: runs, ...opts });
}
function b(t) { // bullet
  return new Paragraph({ numbering: { reference: "bul", level: 0 }, spacing: { after: 60, line: 290 },
    children: Array.isArray(t) ? t : [new TextRun(t)] });
}
function b2(t) {
  return new Paragraph({ numbering: { reference: "bul", level: 1 }, spacing: { after: 40, line: 290 },
    children: Array.isArray(t) ? t : [new TextRun(t)] });
}
function num(t) {
  return new Paragraph({ numbering: { reference: "ord", level: 0 }, spacing: { after: 60, line: 290 },
    children: Array.isArray(t) ? t : [new TextRun(t)] });
}
function bold(t) { return new TextRun({ text: t, bold: true }); }
function txt(t) { return new TextRun(t); }

const border = { style: BorderStyle.SINGLE, size: 1, color: "AAB7C4" };
const borders = { top: border, bottom: border, left: border, right: border,
  insideHorizontal: border, insideVertical: border };

function cell(content, w, { head = false, fill = null, bold: bd = false, align } = {}) {
  const paras = (Array.isArray(content) ? content : [content]).map((c) =>
    typeof c === "string"
      ? new Paragraph({ alignment: align, spacing: { after: 20, line: 270 },
          children: [new TextRun({ text: c, bold: head || bd, color: head ? "FFFFFF" : "000000" })] })
      : c);
  return new TableCell({
    width: { size: w, type: WidthType.DXA },
    shading: { fill: head ? BLUE : (fill || "FFFFFF"), type: ShadingType.CLEAR },
    margins: { top: 60, bottom: 60, left: 110, right: 110 },
    verticalAlign: VerticalAlign.CENTER,
    children: paras,
  });
}

function table(widths, rows) {
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: widths,
    borders,
    rows: rows.map((r, ri) =>
      new TableRow({
        tableHeader: ri === 0,
        children: r.map((c, ci) =>
          cell(c, widths[ci], { head: ri === 0, fill: ri % 2 === 0 ? GREY : null }))
      })),
  });
}

function fig(file, caption, maxW = CONTENT_W) {
  const png = path.join(DIAG, file);
  const children = [];
  if (fs.existsSync(png)) {
    // read intrinsic size from PNG header
    const buf = fs.readFileSync(png);
    const w = buf.readUInt32BE(16), hh = buf.readUInt32BE(20);
    let dispW = Math.min(620, w); // px cap
    let dispH = Math.round(hh * (dispW / w));
    children.push(new ImageRun({ type: "png", data: buf,
      transformation: { width: dispW, height: dispH },
      altText: { title: caption, description: caption, name: caption } }));
  } else {
    children.push(new TextRun({ text: `［图：${file}（渲染缺失）］`, italics: true, color: "B00020" }));
  }
  return [
    new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 120, after: 40 }, children }),
    new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 160 },
      children: [new TextRun({ text: caption, italics: true, size: 20, color: "555555" })] }),
  ];
}

// ---------- document ----------
const children = [];

// 封面
children.push(
  new Paragraph({ spacing: { before: 1600, after: 0 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "车市镜 · 新能源汽车市场情报 Agent", bold: true, size: 30, color: BLUE })] }),
  new Paragraph({ spacing: { before: 200, after: 0 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "产品需求文档 PRD-1", bold: true, size: 56, color: "000000" })] }),
  new Paragraph({ spacing: { before: 120, after: 0 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "数据获取与处理", bold: true, size: 44, color: BLUE })] }),
  new Paragraph({ spacing: { before: 600 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "—— 爬虫采集 · 清洗治理 · 双轨入库 · 质量监控 ——", size: 24, color: "555555" })] }),
  new Paragraph({ spacing: { before: 1400 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "版本 v1.0    日期 2026-05-22    状态：评审稿", size: 22, color: "555555" })] }),
  new Paragraph({ children: [new PageBreak()] }),
);

// 文档信息 + 修订记录
children.push(h1("文档信息"));
children.push(table([2340, 2340, 2340, 2340], [
  ["项目", "车市镜（EV-MarketLens）", "文档编号", "PRD-1"],
  ["模块", "数据获取与处理", "版本", "v1.0"],
  ["作者", "项目组", "日期", "2026-05-22"],
  ["状态", "评审稿", "关联文档", "PRD-2 Agent 构建"],
]));
children.push(p(""));
children.push(h2("修订记录"));
children.push(table([1400, 1600, 2000, 4360], [
  ["版本", "日期", "修订人", "说明"],
  ["v1.0", "2026-05-22", "项目组", "初稿：数据源选型、采集/清洗/存储/质量监控全链路设计"],
]));
children.push(new Paragraph({ children: [new PageBreak()] }));

// 目录
children.push(h1("目录"));
children.push(new TableOfContents("目录", { hyperlink: true, headingStyleRange: "1-3" }));
children.push(new Paragraph({ children: [new PageBreak()] }));

// 第1章
children.push(h1("1. 背景与目标"));
children.push(h2("1.1 项目背景"));
children.push(p([
  txt("「车市镜」是一款面向新能源汽车行业的"), bold("对话式市场情报 Agent"),
  txt("。它把传统 BI 看板升级为「用大白话提问 → 系统自动查数 / 查文档 → 生成图表、结论与归因」的智能分析助手。产品采用"),
  bold("「双脑」架构"), txt("：结构化数据走 "), bold("Text2SQL"),
  txt(" 做量化分析，非结构化文档走 "), bold("RAG 检索增强"),
  txt(" 做知识问答，再由 Agent 统一编排意图路由。"),
]));
children.push(p([
  bold("数据是整个产品的地基。"),
  txt("Agent 再聪明，若底层数据缺失、脏乱、口径不一，输出的结论便不可信。本文档专门定义「数据从哪来、怎么爬、怎么洗、怎么存、怎么保质量」，为上层 Text2SQL 与 RAG 提供干净、规整、可信的数据供给。"),
]));
children.push(h2("1.2 文档范围"));
children.push(b([bold("本文档覆盖："), txt("数据源选型与合规、采集层（爬虫）架构、数据清洗与治理、结构化与非结构化双轨存储设计、数据质量监控。")]));
children.push(b([bold("本文档不覆盖："), txt("Text2SQL 引擎、RAG 问答、Agent 编排、前端与部署——这些见《PRD-2 Agent 构建 / 整体项目》。")]));
children.push(h2("1.3 目标与非目标"));
children.push(h3("设计目标"));
children.push(b("可得性：采集公开可得数据，覆盖品牌/车系、官方指导价/经销商报价、销量榜、用户口碑、行业研究/政策报告。"));
children.push(b("可信度：建立清洗、去重、实体对齐与口径标准化规则，关键指标可追溯血缘。"));
children.push(b("双轨供给：同一套采集结果同时落地为「分析库（结构化）」与「知识库（向量化）」，分别服务 Text2SQL 与 RAG。"));
children.push(b("可增量：支持按日/按周增量更新，避免全量重爬。"));
children.push(b("低门槛起步：本地零配置（SQLite + 本地向量库）即可跑通 demo，生产再平滑升级到 PostgreSQL + 独立向量库。"));
children.push(h3("非目标"));
children.push(b("不采集需登录/付费墙后的数据（拿不到）；不采集车企内部经营数据（涉密、不可得）。"));
children.push(b("不做实时（秒级）数据流；情报分析场景按日/周粒度足够。"));
children.push(h2("1.4 术语表"));
children.push(table([2400, 6960], [
  ["术语", "含义"],
  ["数据域", "一类业务数据的集合，如「报价」「销量榜」「口碑」。"],
  ["维度/事实表", "数仓建模概念：维度表存实体属性（车型、品牌），事实表存可度量事件（一次报价、一条销量记录）。"],
  ["实体对齐", "把不同来源对同一实体的不同写法（如「比亚迪汉EV」「BYD 汉 EV」）归一到同一主键。"],
  ["口径标准化", "统一指标定义与单位，如价格统一为「万元、含税」、时间统一到「自然月」。"],
  ["切片 / Chunk", "把长文档切成适合向量检索的小段。"],
  ["Embedding", "把文本转成向量，用于语义相似检索。"],
  ["ODS/DWD/DWS", "数仓分层：贴源层 / 明细层 / 汇总层。"],
]));
children.push(new Paragraph({ children: [new PageBreak()] }));

// 第2章
children.push(h1("2. 数据需求分析"));
children.push(p("数据设计必须倒推自「上层 Agent 需要什么」。两个消费方对数据的要求截然不同："));
children.push(table([1600, 3880, 3880], [
  ["消费方", "需要的数据形态", "对数据的要求"],
  ["Text2SQL\n（结构化脑）", "规整的维度表 + 事实表（数值、日期、外键）", "字段类型干净、口径统一、可 JOIN、有时间粒度；脏数据会直接导致 SQL 结果错误"],
  ["RAG\n（非结构化脑）", "高质量长文本（行研报告、政策、车评长文）切片后向量化", "正文抽取干净、去除导航/广告噪声、保留来源与标题用于引用溯源"],
]));
children.push(h2("2.1 数据域划分"));
children.push(table([1700, 3000, 2360, 2300], [
  ["数据域", "字段示例（以实测为准）", "去向", "更新频率"],
  ["品牌/车系（维度）", "品牌、车系、级别、动力、指导价区间", "分析库 dim_brand/dim_series", "周/月"],
  ["销量榜（事实）", "车系、排名、上期排名、销量、能源类型、月份", "分析库 fact_sales_rank", "月"],
  ["报价（事实）", "车系、指导价区间、经销商价、降价幅度、快照日", "分析库 fact_price", "日/周"],
  ["口碑（事实+文本）", "车系、评分、评论数、情感、评论正文", "分析库 fact_review + 知识库", "日/周"],
  ["行研/政策（文档）", "标题、正文、来源、发布日期", "知识库（向量化）", "不定期"],
]));
children.push(h2("2.2 规模与频率估算"));
children.push(b([bold("车系维度："), txt("新能源在榜车系单月约 200，全市场更多，属慢变维度，周/月刷新。")]));
children.push(b([bold("销量榜（实测）："), txt("单月新能源约 199 车系，历史可回溯 16+ 月，4 种能源类型 → 销量事实约「近万行」量级。")]));
children.push(b([bold("报价/口碑："), txt("与销量同量级（车系 × 快照），口碑长评另入知识库。")]));
children.push(b([bold("行研/政策："), txt("低频高价值，单篇长文，是 RAG 知识库的核心语料。")]));
children.push(p([bold("结论："), txt("结构化数据近万行量级（可扩到十万级），单机 PostgreSQL + pgvector + MinIO 轻松支撑，无需大数据组件——符合作品级与早期产品定位。详细数据量实测见 data/probe/。")]));
children.push(new Paragraph({ children: [new PageBreak()] }));

// 第3章 数据源选型与合规
children.push(h1("3. 数据源选型与合规"));
children.push(h2("3.1 候选数据源对比"));
children.push(table([1700, 2600, 2100, 2960], [
  ["数据源", "可提供数据", "数据质量/结构化度", "采集难度/反爬"],
  ["汽车之家", "车型库、报价、口碑评分、车评", "高，字段规整", "中，有一定反爬，需限速+UA轮换"],
  ["懂车帝", "销量榜、车型、口碑、资讯", "高，移动端接口规整", "中高，部分接口需签名"],
  ["易车", "报价、车型、经销商", "中高", "中"],
  ["乘联会 / 中汽协", "权威销量统计、行业报告", "高（多为公告/报告 PDF）", "低，多为公开发布"],
  ["政府/政策网站", "新能源补贴、双积分等政策原文", "文本为主", "低，公开"],
]));
children.push(p([bold("选型策略（探针后定稿）："), txt("结构化指标确定为「懂车帝销量榜 API」"), bold("单源"), txt("——一个免登录免签名接口即覆盖品牌/车系/销量/排名/报价/口碑数，且自带稳定 series_id（天然对齐、零对齐风险）。缺字段（级别/动力/续航/口碑评分）走懂车帝自家详情/口碑接口补，仍是同源。")]));
children.push(p([bold("为什么不上多源："), txt("汽车之家/易车作为后期可选增强，仅在「单源确实没有且必须要」时才接，且需做实体对齐（crosswalk 映射 + 模糊匹配 + 人工抽查，易错）。原则：能单源就别多源。行业报告/政策（乘联会等）另作 RAG 知识库语料（与结构化无关，无对齐问题）。")]));
children.push(h2("3.2 采集策略（防封与稳定）"));
children.push(p([txt("本项目为"), bold("个人非商用作品（演示/研究）"), txt("，采集对象为公开可访问页面与接口。以下措施目的是"), bold("保证采集稳定、不被风控封禁"), txt("，并保证数据可追溯：")]));
children.push(num("请求伪装：用 Scrapling 的浏览器级指纹（impersonate/StealthyFetcher），带合理 Referer/Header。"));
children.push(num("限速与重试：随机延时 + 指数退避重试，避免短时高频触发风控（这是为「爬得到」，不是合规门槛）。"));
children.push(num("代理与降级：必要时挂代理 IP 轮换；静态接口拿不到时降级到浏览器渲染。"));
children.push(num("血缘留痕：每行数据保留来源 URL 与采集时间，便于追溯、复爬与下线。"));
children.push(num("优先用 JSON 接口（如懂车帝销量榜）：返回干净、稳定、免登录，比解析 HTML 更省事抗改版。"));
children.push(h2("3.3 风险与规避"));
children.push(table([2600, 3380, 3380], [
  ["风险", "说明", "规避措施"],
  ["IP 封禁", "高频访问被风控", "代理 IP 池轮换、随机延时、指数退避重试、断点续爬"],
  ["页面结构变更", "改版导致解析失效", "解析规则配置化、解析失败告警、样例快照回归"],
  ["反爬升级（JS 渲染/签名）", "静态请求拿不到数据", "Scrapling StealthyFetcher 浏览器渲染兜底；优先找免签名 JSON 接口"],
  ["数据源单一", "懂车帝改版即断供", "多源备份（汽车之家车系树交叉校验）+ 缓存历史数据"],
]));
children.push(new Paragraph({ children: [new PageBreak()] }));

// 第4章 总流程
children.push(h1("4. 总体数据流程"));
children.push(p("数据从采集到供给上层 Agent，经过「采集 → 清洗 → 分流入库 → 质量监控」四个阶段。结构化与非结构化在清洗后分流，分别落地分析库与知识库。"));
fig("d1_overview.png", "图 4-1  数据获取与处理总流程").forEach((x) => children.push(x));
children.push(new Paragraph({ children: [new PageBreak()] }));

// 第5章 采集层
children.push(h1("5. 采集层设计（爬虫）"));
children.push(h2("5.1 架构"));
children.push(p("采集层分为「调度与任务管理 / 采集与反爬 / 解析与落地」三部分，原始数据先落「数据湖（raw 层）」，与下游清洗解耦，便于重放与回溯。"));
fig("d2_crawler.png", "图 5-1  分布式爬虫架构").forEach((x) => children.push(x));
children.push(h2("5.2 反爬策略"));
children.push(b("请求伪装：UA 轮换、合理 Referer/Header、Cookie 管理。"));
children.push(b("频率控制：单域名限速 + 随机抖动延时 + 错峰调度。"));
children.push(b("代理池：付费/自建代理 IP 轮换，失败熔断与健康检查。"));
children.push(b("失败重试：指数退避重试 + 死信队列，避免漏采。"));
children.push(b("渲染降级：静态请求拿不到时降级到 Playwright 无头浏览器。"));
children.push(h2("5.3 增量更新与定时调度（已实现）"));
children.push(p([txt("已在 data/crawl_sales.py 实现"), bold("真增量"), txt("：每跑一次只补新月、刷最近月，跑多少次都幂等。逻辑如下——")]));
children.push(b([bold("动态月份："), txt("从 START_MONTH 自动枚举到「当前月」，不写死；下个月再跑会自动带上新月份。")]));
children.push(b([bold("只补新月："), txt("历史月已采过（记录在 _manifest.json）就跳过——历史销量是定死的不会变，省时省流量。")]));
children.push(b([bold("刷新最近月："), txt("最近 2 个月（含当月）每次强制重采，因为当月数据还在更新、月初可能不全。")]));
children.push(b([bold("按月分文件 + 去重："), txt("data/raw/sales_rank/{月}_{能源}.jsonl 互不覆盖；每个文件整体重写，(月,能源,车系)天然唯一；入库再按唯一键 UPSERT，幂等。")]));
children.push(p([bold("定时调度（买服务器后）："), txt("挂 Celery Beat（推荐，随应用跑在 Docker 里，每月 1 号自动触发）或 Linux cron / Windows 计划任务，每月跑一次即可保持数据常新。配置示例见 deploy/scheduling/。")]));
children.push(p([bold("一句话："), txt("每月（或每周）自动跑一次增量采集 → 数据一直是新的，且重复跑不会脏。")]));
children.push(h2("5.4 采集层技术栈选型"));
children.push(table([1900, 2730, 2030, 2700], [
  ["环节", "候选方案", "选型", "理由"],
  ["抓取+反爬+解析", "Scrapy+Playwright+httpx 三件套 / Scrapling", "Scrapling", "一个库集成抓取、反爬绕过（StealthyFetcher）、自适应选择器，替代原三件套，开发量大减、抗改版强"],
  ["动态渲染", "Selenium / Scrapling PlayWrightFetcher", "Scrapling PlayWrightFetcher", "Scrapling 内置，无需单独接 Playwright"],
  ["调度", "APScheduler / Celery", "Celery + Redis", "任务队列 + 分布式，生产级"],
  ["代理", "自建 / 付费代理", "付费代理池", "稳定性优先，成本可控"],
  ["原始落地", "Hadoop/HDFS / MinIO / 云 OSS", "MinIO 对象存储", "GB 级数据无需 Hadoop；MinIO 自建 S3 兼容、轻量、可重放"],
]));
children.push(h2("5.5 实际采集实现（懂车帝销量榜，已跑通）"));
children.push(p([bold("这是真实落地的采集，不是示意。"), txt("代码：data/crawl_sales.py（用 Scrapling 专用环境运行）；原始数据落 data/raw/，"), bold("不入库"), txt("（等第 6 章清洗后才进数仓）。")]));
children.push(h3("接口与参数"));
children.push(table([2000, 7360], [
  ["项", "值"],
  ["接口", "GET https://www.dongchedi.com/motor/pc/car/rank_data"],
  ["关键参数", "rank_data_type=11（销量榜）、new_energy_type=1纯电/2插混/3增程、month（空=最新，YYYYMM=历史月）、count=60+offset（翻页）"],
  ["请求头", "Referer: https://www.dongchedi.com/sales —— 免登录、免签名"],
  ["返回", "JSON：{status:0, data:{list:[…], paging:{has_more}}}，用 page.body 取原始字节再 json.loads"],
]));
children.push(h3("采集维度组合（怎么把数据铺满）"));
children.push(b([bold("月份遍历："), txt("2024-01 ~ 2026-04 的月份列表，逐月请求；空响应自动跳过（拿到全部可得历史月）。")]));
children.push(b([bold("能源类型遍历："), txt("纯电(1)/插混(2)/增程(3) 三类各拉一遍，覆盖整个新能源盘子。")]));
children.push(b([bold("翻页："), txt("count=60 + offset 递增，直到 paging.has_more=false，取尽单月单类型的全部车系。")]));
children.push(h3("防封与稳定（纯实用，非合规门槛）"));
children.push(b("浏览器级指纹：Fetcher impersonate='chrome'。"));
children.push(b("随机延时 0.3~0.7s + 失败指数退避重试 3 次（1.5s/3s/4.5s），避免短时高频被风控。"));
children.push(h3("原始落地与血缘"));
children.push(b("每条记录追加血缘字段：_month、_new_energy_type、_energy_label、_source、_source_url、_crawl_time。"));
children.push(b("落 data/raw/sales_rank_raw.jsonl（一行一条 JSON；生产环境 → MinIO 对象存储）。"));
children.push(b([bold("不入库原则："), txt("原始层保持接口原样，便于重放/回溯；清洗（§6）后才进 PostgreSQL。")]));
children.push(p([bold("实测产出（2026-05-22 实跑）："), txt("销量记录 7,734 行，覆盖 409 个车系、28 个月（2024-01 ~ 2026-04）；按能源类型 纯电 4,923 / 插混 2,528 / 增程 283。详见 data/raw/_crawl_summary.json。")]));
children.push(new Paragraph({ children: [new PageBreak()] }));

// 第6章 清洗
children.push(h1("6. 数据清洗与治理"));
children.push(p("原始数据从数据湖流入清洗流水线，依次完成校验、清洗、去重、实体对齐、口径标准化，再分流到结构化数仓与非结构化知识库。"));
fig("d3_etl.png", "图 6-1  数据清洗与分流（ETL）流水线").forEach((x) => children.push(x));
children.push(p([bold("说明："), txt("本章清洗逻辑直接对应 data/crawl_sales.py 采下的真实原始数据（data/raw/sales_rank_raw.jsonl，7,734 行）。输入=原始 JSON 行，输出=DWD 明细（dim_brand / dim_series / fact_sales_rank / fact_price / fact_review）+ DWS 预聚合。五步：字段级清洗 → 去重 → 实体对齐 → 口径标准化 → 拆表映射。")]));

children.push(h2("6.1 字段级清洗规则（原始字段 → 处理 → 去向）"));
children.push(p("以一条真实原始记录为例（Model Y / 特斯拉 / 202401 / 纯电）："));
children.push(table([2100, 4060, 3200], [
  ["原始字段（实测）", "清洗处理", "去向"],
  ["_month「202401」", "解析为 date_id=202401、year=2024、month=1、quarter=1、ym=「2024-01」", "dim_date"],
  ["series_id「4363」", "整数主键，直接用", "dim_series.series_id"],
  ["series_name「Model Y」", "去首尾空白、全半角统一", "dim_series.series_name"],
  ["brand_name/sub_brand_name「特斯拉/特斯拉中国」", "去空白；按 brand_id 归并", "dim_brand"],
  ["count「29912」", "→ volume(int)；校验 >0（实测异常 0 条）", "fact_sales_rank.volume"],
  ["rank/last_rank「1 / 1」", "整数；last_rank 缺失/0 → 置 NULL 并标「新上榜」（实测 337 行）", "fact_sales_rank"],
  ["min_price/max_price「26.35/31.35」", "数值(万元)；缺失→NULL", "fact_price + dim_series 当前快照"],
  ["price/dealer_price「26.35-31.35万」", "正则解析区间数值；「暂无报价」→NULL", "fact_price"],
  ["car_review_count「2768」", "→ review_count(int)", "fact_review.review_count"],
  ["score「0」", "实测恒为 0 → 一律置 NULL（不当真实评分）", "fact_review.score"],
  ["_new_energy_type「1」", "推断 powertrain：1纯电/2插混/3增程 → 补字段", "dim_series.powertrain"],
  ["_source/_source_url/_crawl_time", "原样带入（血缘）", "各事实表"],
]));

children.push(h2("6.2 去重"));
children.push(b([bold("事实去重："), txt("fact_sales_rank 以 (series_id, date_id, new_energy_type, rank_type) 为唯一键；同键重复取 _crawl_time 最新的一条。")]));
children.push(b([bold("维度去重："), txt("409 个车系在 28 月 × 3 类型里共出现 7,734 次 → 按 series_id 去重成约 409 行 dim_series；属性取最新一条。dim_brand 同理按 brand_id 去重。")]));
children.push(b("文本 MinHash 模糊去重留给后续「口碑评论文本」用，本结构化榜单用不上。"));

children.push(h2("6.3 实体对齐（关键，含一条重要简化）"));
children.push(b([bold("单源天然对齐："), txt("懂车帝单源内 series_id / brand_id 本身就是稳定主键，同源数据无需模糊匹配——这是选「带稳定 ID 的接口」而非「爬名字」的红利。")]));
children.push(b([bold("跨源才需要对齐："), txt("将来接汽车之家车系树时，用 series_name 标准化 + RapidFuzz 模糊匹配 + 别名词典，把汽车之家车系名映射到懂车帝 series_id。例：「Model Y / modelY / 特斯拉Model Y」→ 统一 series_id=4363。")]));
children.push(b([bold("对齐的副产品——补字段："), txt("powertrain 由 _new_energy_type 直接推断填入 dim_series，无需额外接口（把原本 nullable 的列在清洗阶段就补上一部分）。")]));

children.push(h2("6.4 口径标准化"));
children.push(b("销量口径：volume = 该车系当月销量（榜单月度口径），统一到「辆」。"));
children.push(b("价格口径：guide_price_min/max = 厂商指导价；dealer_price 文本解析为经销商报价区间；统一「万元」。"));
children.push(b("能源枚举：1/2/3 → 纯电/插混/增程 标准词，写入 fact_sales_rank.new_energy_type 与 dim_series.powertrain。"));
children.push(b("时间口径：销量/报价/口碑统一到「月」（date_id=YYYYMM）。"));
children.push(b("「新上榜」语义：last_rank 缺失 → 该车系当月首次进榜，环比排名变化记 NULL（而非 0），避免误算。"));

children.push(h2("6.5 raw → DWD / DWS 映射"));
children.push(b([bold("拆表："), txt("原始 1 行 → 拆出 dim_brand(1) + dim_series(1) + fact_sales_rank(1) + fact_price(1) + fact_review(1)，按 §6.1 规则填充。")]));
children.push(b([bold("DWS 预聚合派生指标："), txt("月度环比销量增幅 =（本月 volume − 上月 volume）/ 上月 volume；排名变化 = last_rank − rank（NULL 时不算）。")]));
children.push(b([bold("产出量级："), txt("7,734 原始行 → fact_sales_rank ≈ 7,734 行（去重后）、dim_series ≈ 409 行、dim_brand 数十行。")]));

children.push(h2("6.6 清洗层技术栈选型"));
children.push(table([2000, 3680, 3680], [
  ["环节", "选型", "理由"],
  ["数据处理", "Pandas（起步）/ Polars（大数据量）", "Pandas 生态成熟易上手；数据量上来后 Polars 性能更优"],
  ["数据质量校验", "Great Expectations / Pandera", "声明式断言（非空、范围、唯一），自动生成质量报告"],
  ["去重", "datasketch（MinHash）", "海量文本近似去重高效"],
  ["实体对齐", "RapidFuzz + 别名词典 + Embedding", "字符串模糊匹配 + 语义匹配双保险"],
  ["文档解析", "MinerU（CPU 模式）", "PDF→Markdown，复杂版面/表格/多栏抽取强，是 RAG 入库前首选；CPU 即可，无需 GPU"],
]));
children.push(new Paragraph({ children: [new PageBreak()] }));

// 第7章 存储
children.push(h1("7. 数据存储设计"));
children.push(h2("7.1 schema 是怎么定出来的（方法与探针依据）"));
children.push(p([bold("原则：先探真实字段，再建模，不在见数据前敲死表结构。"), txt("流程分两步——")]));
children.push(num([bold("探针实测（T1，已完成）："), txt("用 Scrapling 对候选源各爬样本，列出「实际能拿到的字段」。实测主源为懂车帝销量榜 API（免登录免签名、返回干净 JSON），一个接口即覆盖 品牌 / 车系 / 销量 / 排名（本期+上期）/ 指导价区间 / 经销商价 / 口碑数。产物：data/probe/数据源字段清单.md。")]));
children.push(num([bold("Kimball 建模 → 定稿："), txt("以实测字段为准，按「业务问题→度量→粒度→维度+事实」映射成星型模型并写入 sql/schema.sql。")]));
children.push(p([bold("探针带来的两个关键修正（相比拍脑袋的 v0）："), txt("")]));
children.push(b([bold("不建 dim_region 空表："), txt("该榜单是全国口径，实测无分地区销量 → 删除地区维度，避免造空表。")]));
children.push(b([bold("score/segment/powertrain 标 nullable："), txt("销量接口里评分恒为 0、无级别/动力字段 → 这些列先置空，标注由「口碑接口 / 车系详情接口」在 T3 补全。")]));
children.push(p([bold("真实字段 → 表 映射（节选）："), txt("series_id/series_name→dim_series；brand_id/brand_name→dim_brand；count→fact_sales_rank.volume；rank/last_rank→排名与趋势；min_price/max_price/dealer_price→fact_price；car_review_count→fact_review。完整映射见字段清单与 schema.sql。")]));
children.push(h2("7.2 结构化：维度建模（定稿）"));
children.push(p("星型模型：维度 dim_brand（品牌）/ dim_series（车系）/ dim_date（月）+ 事实 fact_sales_rank（销量榜）/ fact_price（报价）/ fact_review（口碑）。该模型对 Text2SQL 友好——表意清晰、JOIN 路径短，LLM 更易生成正确 SQL。"));
fig("d4_star.png", "图 7-1  分析库星型模型（ER 图，基于实测字段定稿）").forEach((x) => children.push(x));
children.push(h3("数仓分层"));
children.push(b("ODS（贴源）：与源结构一致的原始落地，仅做格式规整。"));
children.push(b("DWD（明细）：清洗、对齐、标准化后的明细事实。"));
children.push(b("DWS（汇总）：按车型/地区/月预聚合，加速高频查询。"));
children.push(h3("数据库选型"));
children.push(table([2200, 3580, 3580], [
  ["阶段", "选型", "理由"],
  ["本地 / Demo", "SQLite", "零配置、单文件、便于演示与提交作品（现有 starter 即用）"],
  ["生产 / 上线", "PostgreSQL", "并发、类型、窗口函数强；可装 pgvector 同库存向量，运维简单"],
]));
children.push(h3("原始数据存储（为什么不用 Hadoop）"));
children.push(b("原始爬取数据（HTML/JSON/PDF）落 MinIO 对象存储（自建 S3 兼容）或云 OSS，按文件存，便于重放、追溯与下线。"));
children.push(b([bold("明确不用 Hadoop："), txt("本项目数据量级为 GB 级，Hadoop/HDFS/Spark 面向 TB~PB 级分布式计算，对 5 人团队是过度设计与沉重运维负担。单机 PostgreSQL + MinIO 即可，真到 TB 级再考虑 ClickHouse / 数据湖。")]));
children.push(h2("7.3 非结构化：知识库"));
children.push(b("切片：按语义/标题分块，重叠窗口（如 chunk 500–800 字、overlap 80–120），保留标题与来源元数据。"));
children.push(b("向量化：Embedding 模型把切片转向量，写入向量库；保留 doc_id/来源/页码用于引用溯源。"));
children.push(h3("向量库与 Embedding 选型"));
children.push(table([1900, 2600, 4860], [
  ["环节", "候选", "选型与理由"],
  ["向量库", "Chroma / FAISS / pgvector / Milvus", "起步可用 Chroma（本地零配置）；生产统一用 pgvector（与业务库同栈，少一个组件）"],
  ["Embedding", "BGE-large-zh / M3E", "本地 BGE-large-zh，中文检索好、零成本、可离线。注意：Embedding 模型独立于对话大模型（DeepSeek-V4），不可混用"],
]));
children.push(new Paragraph({ children: [new PageBreak()] }));

// 第8章 数据质量
children.push(h1("8. 数据质量与监控"));
children.push(p("数据质量直接决定 Agent 输出可信度，需建立可量化、可告警的监控体系。"));
children.push(h2("8.1 质量维度与指标"));
children.push(table([2200, 3580, 3580], [
  ["维度", "指标", "处理"],
  ["完整性", "关键字段非空率、采集成功率", "低于阈值告警，触发补采"],
  ["准确性", "数值合理区间、跨源一致性", "离群过滤、多源交叉校验"],
  ["唯一性", "重复率", "去重规则兜底"],
  ["及时性", "数据新鲜度（最近更新时间）", "调度延迟告警"],
  ["一致性", "口径/单位统一", "标准化断言校验"],
]));
children.push(h2("8.2 监控与血缘"));
children.push(b("校验：Great Expectations 在入库前断言，生成质量报告。"));
children.push(b("告警：采集失败率、解析失败、新鲜度异常通过日志+通知（邮件/IM Webhook）告警。"));
children.push(b("血缘：每行数据保留 source_url、采集时间、清洗版本，关键指标可回溯到原始页面。"));
children.push(new Paragraph({ children: [new PageBreak()] }));

// 第9章 技术栈总览
children.push(h1("9. 技术栈总览"));
children.push(table([2400, 6960], [
  ["层次", "技术选型"],
  ["采集", "Python · Scrapling（抓取 + 反爬绕过 + 自适应解析）· Celery + Redis 调度 · 付费代理池"],
  ["清洗治理", "Pandas / Polars · Great Expectations · RapidFuzz · datasketch"],
  ["文档解析", "MinerU（CPU 模式，PDF→Markdown）"],
  ["原始存储", "MinIO 对象存储（明确不用 Hadoop）"],
  ["结构化存储", "SQLite（demo）→ PostgreSQL · 星型维度建模 · SQLAlchemy"],
  ["向量存储", "pgvector（同 PostgreSQL）· BGE-large-zh Embedding（独立于对话模型）"],
  ["质量监控", "Great Expectations · 日志告警 · 数据血缘"],
  ["部署形态", "单台云 VPS 自托管全栈（Docker Compose）"],
]));
children.push(p([bold("一句话技术栈："), txt("Python 全栈采集治理——Scrapling 爬取、MinerU 解析文档；本地 SQLite/Chroma 零配置起步，生产 PostgreSQL + pgvector + MinIO 部署在单台云 VPS。")]));
children.push(new Paragraph({ children: [new PageBreak()] }));

// 第10章 可行性分析
children.push(h1("10. 可行性分析"));
children.push(h2("10.1 技术可行性"));
children.push(p("所选技术栈均为成熟开源方案，社区活跃、文档齐全，无前沿不确定性。现有 starter 已验证 SQLAlchemy + SQLite 链路可跑通，向量库（Chroma）与爬虫（Scrapy/Playwright）均有大量生产案例。"));
children.push(p([bold("结论：技术可行，无卡点。")]));
children.push(h2("10.2 合规可行性"));
children.push(p("采集范围严格限定在公开、非登录、robots 允许的数据，限速去 PII、来源留痕（见第 3 章）。在「个人作品/研究演示、不商用」定位下，合规风险可控。"));
children.push(p([bold("结论：合规可行，前提是严守第 3.2 节红线。")]));
children.push(h2("10.3 成本与资源"));
children.push(table([2600, 3380, 3380], [
  ["项", "估算", "说明"],
  ["开发人力", "约 3–4 周（数据层）", "采集 1.5 周 + 清洗存储 1.5 周 + 监控 0.5 周"],
  ["代理 IP", "约 ¥100–300/月", "按量付费，demo 阶段可极低"],
  ["Embedding/LLM", "按调用量，可先本地", "本地 BGE 零成本；云端按 token 计费"],
  ["服务器", "单台云 VPS 2C4G 起", "数据 GB 级，单机自托管全栈足够；MinerU 用 CPU，无需 GPU"],
]));
children.push(p([bold("结论：成本极低，个人可负担。")]));
children.push(h2("10.4 工期可行性（对齐秋招窗口）"));
children.push(p("距秋招约 3 个月，数据层在前 3–4 周完成可为后续 Agent 开发留足时间。建议先打通「单数据域（如报价+销量）最小闭环」再横向扩域，避免一开始铺太大。"));
children.push(p([bold("结论：工期可行，建议小步快跑、先窄后宽。")]));
children.push(new Paragraph({ children: [new PageBreak()] }));

// 第11章 里程碑
children.push(h1("11. 里程碑与排期"));
children.push(table([1300, 2400, 4200, 1460], [
  ["阶段", "目标", "交付物", "周期"],
  ["D-M1", "采集最小闭环", "汽车之家报价+销量爬虫，原始数据落地", "第 1–1.5 周"],
  ["D-M2", "清洗与建模", "清洗流水线 + 星型模型入库（SQLite）", "第 1.5–3 周"],
  ["D-M3", "知识库", "报告/政策文档切片向量化入 Chroma", "第 3–3.5 周"],
  ["D-M4", "质量监控", "GE 校验 + 告警 + 血缘字段", "第 3.5–4 周"],
]));
children.push(p([bold("出口标准："), txt("Text2SQL 能查到干净可 JOIN 的结构化数据，RAG 能检索到带来源的高质量文本切片——即移交《PRD-2 Agent 构建》。")]));
children.push(new Paragraph({ children: [new PageBreak()] }));

// 第12章 风险
children.push(h1("12. 风险与应对"));
children.push(table([3000, 3180, 3180], [
  ["风险", "影响", "应对"],
  ["反爬升级导致采集中断", "数据断更", "多源备份、Playwright 降级、缓存历史数据"],
  ["数据源改版", "解析失效", "解析配置化 + 失败告警 + 快速修复"],
  ["实体对齐错误", "跨源聚合错误", "别名词典人工校准 + 抽样核对"],
  ["合规边界", "项目风险", "严守 robots/限速/去 PII，保留下线能力"],
  ["范围蔓延", "工期失控", "先单域最小闭环，按里程碑收敛"],
]));
children.push(p(""));
children.push(p([bold("—— 本文档完。下一步见《PRD-2 Agent 构建 / 整体项目》。 ——")], { alignment: AlignmentType.CENTER }));

// ---------- assemble ----------
const doc = new Document({
  creator: "车市镜项目组",
  title: "PRD-1 数据获取与处理",
  styles: {
    default: { document: { run: { font: FONT, size: 22 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 32, bold: true, font: FONT, color: BLUE },
        paragraph: { spacing: { before: 280, after: 160 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 26, bold: true, font: FONT, color: "2E5496" },
        paragraph: { spacing: { before: 200, after: 100 }, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 23, bold: true, font: FONT, color: "44546A" },
        paragraph: { spacing: { before: 140, after: 80 }, outlineLevel: 2 } },
    ],
  },
  numbering: {
    config: [
      { reference: "bul", levels: [
        { level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 540, hanging: 280 } } } },
        { level: 1, format: LevelFormat.BULLET, text: "–", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 1080, hanging: 280 } } } },
      ] },
      { reference: "ord", levels: [
        { level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 540, hanging: 280 } } } },
      ] },
    ],
  },
  sections: [{
    properties: { page: {
      size: { width: 12240, height: 15840 },
      margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } } },
    headers: { default: new Header({ children: [new Paragraph({
      border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: BLUE, space: 4 } },
      tabStops: [{ type: TabStopType.RIGHT, position: TabStopPosition.MAX }],
      children: [new TextRun({ text: "车市镜 · PRD-1 数据获取与处理", size: 16, color: "888888" }),
        new TextRun({ text: "\tv1.0", size: 16, color: "888888" })] })] }) },
    footers: { default: new Footer({ children: [new Paragraph({
      alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: "第 ", size: 18, color: "888888" }),
        new TextRun({ children: [PageNumber.CURRENT], size: 18, color: "888888" }),
        new TextRun({ text: " 页", size: 18, color: "888888" })] })] }) },
    children,
  }],
});

Packer.toBuffer(doc).then((buf) => {
  let out = path.join(DIR, "PRD-1-数据获取与处理.docx");
  try { fs.writeFileSync(out, buf); }
  catch (e) {
    if (e.code === "EBUSY" || e.code === "EPERM") {
      out = path.join(DIR, "PRD-1-数据获取与处理-已更新.docx");
      fs.writeFileSync(out, buf);
      console.log("（原文件被 Word 占用，已写到新文件）");
    } else throw e;
  }
  console.log("WROTE", out, buf.length, "bytes");
});
