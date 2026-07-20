/* 生成《车市镜 · 开发任务拆解书（工单制）》Word */
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, LevelFormat, HeadingLevel, BorderStyle,
  WidthType, ShadingType, VerticalAlign, PageNumber, PageBreak,
  TableOfContents, TabStopType, TabStopPosition,
} = require("docx");

const DIR = __dirname;
const CONTENT_W = 9360;
const FONT = "Microsoft YaHei", MONO = "Consolas";
const BLUE = "1F4E79", GREY = "F2F2F2", CODEBG = "F4F6F8";

const h1 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun(t)] });
const h2 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun(t)] });
const p = (t, o = {}) => new Paragraph({ spacing: { after: 120, line: 300 },
  children: Array.isArray(t) ? t : [new TextRun(t)], ...o });
const b = (t) => new Paragraph({ numbering: { reference: "bul", level: 0 }, spacing: { after: 50, line: 290 },
  children: Array.isArray(t) ? t : [new TextRun(t)] });
const bold = (t) => new TextRun({ text: t, bold: true });
const txt = (t) => new TextRun(t);

const border = { style: BorderStyle.SINGLE, size: 1, color: "AAB7C4" };
const borders = { top: border, bottom: border, left: border, right: border,
  insideHorizontal: border, insideVertical: border };
function cell(content, w, { head = false, fill = null } = {}) {
  const paras = (Array.isArray(content) ? content : [content]).map((c) =>
    typeof c === "string" ? new Paragraph({ spacing: { after: 10, line: 260 },
      children: [new TextRun({ text: c, bold: head, color: head ? "FFFFFF" : "000000" })] }) : c);
  return new TableCell({ width: { size: w, type: WidthType.DXA },
    shading: { fill: head ? BLUE : (fill || "FFFFFF"), type: ShadingType.CLEAR },
    margins: { top: 50, bottom: 50, left: 100, right: 100 },
    verticalAlign: VerticalAlign.CENTER, children: paras });
}
function table(widths, rows) {
  return new Table({ width: { size: CONTENT_W, type: WidthType.DXA }, columnWidths: widths, borders,
    rows: rows.map((r, ri) => new TableRow({ tableHeader: ri === 0,
      children: r.map((c, ci) => cell(c, widths[ci], { head: ri === 0, fill: ri % 2 === 0 ? GREY : null })) })) });
}
// 代码框：每行一个浅底单元格表格，等宽字体
function codeBox(lines) {
  const rows = lines.map((ln) => new TableRow({ children: [new TableCell({
    width: { size: CONTENT_W, type: WidthType.DXA },
    shading: { fill: CODEBG, type: ShadingType.CLEAR },
    margins: { top: 12, bottom: 12, left: 140, right: 100 },
    children: [new Paragraph({ spacing: { after: 0, line: 250 },
      children: [new TextRun({ text: ln === "" ? " " : ln, font: MONO, size: 18, color: "1A1A2E" })] })],
  })] }));
  return new Table({ width: { size: CONTENT_W, type: WidthType.DXA }, columnWidths: [CONTENT_W],
    borders: { top: { style: BorderStyle.SINGLE, size: 2, color: "C9D2DC" },
      bottom: { style: BorderStyle.SINGLE, size: 2, color: "C9D2DC" },
      left: { style: BorderStyle.SINGLE, size: 6, color: BLUE },
      right: { style: BorderStyle.SINGLE, size: 2, color: "C9D2DC" },
      insideHorizontal: { style: BorderStyle.NONE }, insideVertical: { style: BorderStyle.NONE } },
    rows });
}

// ---- 14 个工单数据 ----
const TASKS = [
  { id: "T1", name: "数据源调研与字段探针", dep: "—", stage: "数据",
    prompt: `角色：数据工程师。
背景：我们在做「车市镜」新能源汽车市场情报 Agent，数据靠爬公开市场数据。建表前必须先摸清各数据源真实能拿到哪些字段，不能拍脑袋定 schema。
任务：
1. 调研并选定 2-3 个公开数据源（候选：汽车之家、懂车帝、易车），目标数据域：车型库、官方指导价/经销商报价、销量榜、用户口碑评论。
2. 用 Scrapling（调用项目 scrapling skill）对每个源各爬 50-100 条样本，落到 data/probe/ 下的 JSON。
3. 产出《数据源字段清单.md》：每个源 × 每个数据域，列出【实际可得字段名、类型、示例值、缺失情况、更新频率、是否需登录/反爬强度】。
4. 标注：哪些理想字段拿不到（如经销商成交价）、哪些粒度受限（销量只到月/省）。
技术栈：Scrapling（StealthyFetcher 优先）、随机延时、单域 ≤1QPS。
交付物：data/probe/*.json + docs/数据源字段清单.md。
验收标准：三个数据域均有真实样本；字段清单能直接用于 T2 定 schema；无 PII、留 source_url+采集时间。
约束：严守合规红线；robots 禁止的不爬。` },
  { id: "T2", name: "schema 定稿 + PostgreSQL 建库建模", dep: "T1", stage: "数据",
    prompt: `角色：数据建模工程师。
背景：T1 已产出《数据源字段清单》。现在基于"真实可得字段"校准星型模型并建库。
任务：
1. 读 docs/数据源字段清单.md，用 Kimball 维度建模（业务问题→度量→粒度→维度+事实）定稿表结构。
   维度：dim_brand / dim_model / dim_region / dim_date；事实：fact_price / fact_sales_rank / fact_review。
   字段以 T1 实际可得为准，拿不到的字段删除或标注 nullable。
2. 写 sql/schema.sql（PostgreSQL 方言）+ SQLAlchemy ORM 模型（app/models.py）。
3. 分层 ODS/DWD/DWS：ODS 贴源、DWD 明细、DWS 预聚合（按车型×地区×月）。
4. 更新 seed.py：用 T1 样本生成可演示种子数据（本地仍可 SQLite，生产 PostgreSQL，DATABASE_URL 切换）。
技术栈：PostgreSQL + pgvector 扩展（为 T5 预留向量列）、SQLAlchemy。
交付物：sql/schema.sql、app/models.py、迁移脚本、更新后的 seed.py。
验收标准：本地 SQLite 与 PostgreSQL 均能建表+灌种子；表/字段与字段清单一致；DWS 预聚合查询跑通。` },
  { id: "T3", name: "Scrapling 正式采集模块", dep: "T2", stage: "数据",
    prompt: `角色：爬虫工程师。
背景：schema 已定稿（T2）。建生产级采集模块，持续供数。
任务：
1. 用 Scrapling 实现报价/销量榜/口碑三类采集器，字段映射到 T2 的 ODS 表。
2. 反爬：UA轮换、随机延时、代理池接口（可先空实现）、指数退避重试、失败入死信队列。
3. 增量：URL/内容指纹去重（BloomFilter）；报价按日、车型库按周、口碑按时间游标增量。
4. 调度：Celery + Redis；原始响应（HTML/JSON）落 MinIO 对象存储（本地用 MinIO docker 或文件夹兜底）。
技术栈：Scrapling（调用 skill）、Celery、Redis、MinIO（minio-py/boto3）。
交付物：app/crawler/ 模块、Celery 任务、采集配置（数据源解析规则配置化）。
验收标准：三类采集器跑通并写入 ODS；重复运行不产生重复数据；原始数据可在 MinIO 追溯；解析规则改配置即可，不改代码。
约束：合规红线；单域 ≤1QPS；解析失败要告警不能静默。` },
  { id: "T4", name: "清洗治理流水线", dep: "T3", stage: "数据",
    prompt: `角色：数据工程师。
背景：ODS 已有原始数据（T3）。清洗成可分析的 DWD/DWS。
任务：
1. 清洗：缺失/异常处理、数值合理区间过滤、单位归一（价格→万元、销量→辆、日期→ISO）、文本去 HTML/广告噪声。
2. 去重：主键精确去重 + SimHash/MinHash 文本模糊去重（datasketch）。
3. 实体对齐（关键）：建品牌/车型别名词典 + RapidFuzz 模糊匹配 + Embedding 语义兜底，把"比亚迪汉EV/BYD 汉 EV/汉EV"归一到同一 model_id。
4. 口径标准化：区分指导价/成交价、统一时间粒度、情感统一为正/中/负三分类。
5. 写入 DWD 明细 + DWS 预聚合。
技术栈：Pandas（量大可 Polars）、RapidFuzz、datasketch。
交付物：app/etl/ 流水线 + 别名词典 + 单元测试。
验收标准：跨源数据能按统一 model_id JOIN/聚合；重复率<阈值；抽样核对实体对齐正确率；DWS 指标口径一致。` },
  { id: "T5", name: "MinerU 文档知识库管线", dep: "T2", stage: "数据",
    prompt: `角色：RAG 数据工程师。
背景：RAG 知识库需要把行研报告/政策 PDF 转成高质量可检索切片。
任务：
1. 接入 MinerU（CPU 模式）解析 PDF/网页 → 干净 Markdown + 版面信息，保留标题/来源/页码。
2. 语义切片：chunk 500-800字、overlap 80-120，保留元数据（doc_id/来源/页码）用于引用溯源。
3. Embedding：本地 BGE-large-zh 把切片向量化，写入 pgvector（T2 预留的向量列/表）。
4. 提供"上传文档→入库"的服务函数（供 T11 接口调用）。
技术栈：MinerU（CPU）、BGE-large-zh、pgvector、LangChain/LlamaIndex（切片）。
交付物：app/kb/ 模块（解析/切片/向量化/入库）+ 单测。
验收标准：一篇带表格的 PDF 能解析干净、切片入库、可按相似度检回且带正确来源元数据。
约束：不要用 DeepSeek 对话模型做 embedding；embedding 模型独立可配。` },
  { id: "T6", name: "数据质量与监控", dep: "T4", stage: "数据",
    prompt: `角色：数据质量工程师。
背景：数据质量直接决定 Agent 输出可信度。
任务：
1. 用 Great Expectations 在入库前断言：关键字段非空率、数值合理区间、唯一性、口径/单位一致、数据新鲜度。
2. 每行数据保留血缘字段：source_url、采集时间、清洗版本。
3. 采集失败率/解析失败/新鲜度异常 → 日志 + IM Webhook 告警。
4. 生成数据质量报告（定期）。
技术栈：Great Expectations、日志、Webhook 告警。
交付物：app/dq/ 校验套件 + 告警 + 质量报告模板。
验收标准：故意灌脏数据能被拦截并告警；关键指标可回溯到原始页面；质量报告可读。` },
  { id: "T7", name: "Text2SQL 引擎", dep: "T4", stage: "Agent",
    prompt: `角色：LLM 应用工程师。
背景：DWD/DWS 已就绪（T4）。实现自然语言→SQL→安全执行的核心引擎。
任务：
1. Schema Linking：用 Embedding 算问题与表/列相似度，筛出相关表子集再喂 LLM（小库可全量），降噪提准。
2. 生成 SQL：DeepSeek-V4 + few-shot 示例库（领域包，放 app/fewshot/）。
3. SQL 安全护栏：用 sqlglot 解析 AST，只放行单条 SELECT，拦截写操作/多语句/危险函数，限制返回行数；DB 用只读账号双保险。
4. 自校验重试：执行报错或空结果时把错误回填给 LLM 修正，循环至成功或达 MAX_SQL_RETRY。
技术栈：sqlglot、SQLAlchemy（只读）、DeepSeek-V4、BGE Embedding。
交付物：app/text2sql.py、app/schema_linking.py、app/sql_guard.py、few-shot 示例集。
验收标准：复用 T13 的 Text2SQL 评测集，执行准确率达标；护栏能挡住所有写操作与注入用例；重试能修正常见错误。` },
  { id: "T8", name: "图表规格 + 洞察归因", dep: "T7", stage: "Agent",
    prompt: `角色：LLM 应用工程师。
背景：Text2SQL（T7）产出结果集。把结果转成图表与自然语言洞察。
任务：
1. 图表生成：LLM 根据结果结构（维度数/类型）选图型（折线/柱状/饼/排行），产出 ECharts JSON 规格。
2. 洞察：生成「结论（一句话趋势）+ 归因（为什么，可结合知识库）+ 建议（下一步）」。
3. 防幻觉：洞察只基于真实结果，数字禁止 LLM 杜撰。
技术栈：DeepSeek-V4、ECharts 规格（JSON）。
交付物：app/charts.py、app/insights.py。
验收标准：常见查询能出正确图型的合法 ECharts 规格；洞察数字与结果集一致（抽样核对）。` },
  { id: "T9", name: "RAG 问答引擎", dep: "T5", stage: "Agent",
    prompt: `角色：RAG 工程师。
背景：知识库已入库（T5，pgvector + 来源元数据）。实现检索问答。
任务：
1. 检索：问题向量化 → pgvector Top-K → bge-reranker 重排。
2. 生成：拼接上下文 + Prompt，DeepSeek-V4 产出答案，强制标注来源（文档名/页码）。
3. 防幻觉：无相关片段时明确"未在知识库找到"，不硬编。
技术栈：pgvector、BGE-large-zh、bge-reranker、DeepSeek-V4、LangChain。
交付物：app/rag.py（检索/重排/生成/引用）。
验收标准：RAGAS 忠实度/上下文精度达标；答案带正确引用；无关问题不幻觉。` },
  { id: "T10", name: "LangGraph Agent 编排", dep: "T7, T9", stage: "Agent",
    prompt: `角色：Agent 工程师。
背景：Text2SQL（T7/T8）与 RAG（T9）两个脑就绪。用 LangGraph 编排成统一 Agent。
任务：
1. 状态机节点：意图识别 → 路由（数据分析/知识问答/混合/需澄清）→ Text2SQL 节点 / RAG 节点 / 图表洞察节点 → 结果汇总。
2. 混合任务：既要数又要解读时并行调两个脑再合并。
3. 澄清追问：信息不足时反问；支持多轮上下文。
技术栈：LangGraph + LangChain。
交付物：app/agent.py（图定义 + 节点 + 状态）。
验收标准：意图路由准确率达标（用 T13 标注集）；混合任务能整合双脑输出；可回溯每步（意图/SQL/检索片段）。` },
  { id: "T11", name: "FastAPI 接口层", dep: "T10", stage: "Agent",
    prompt: `角色：后端工程师。
背景：Agent（T10）就绪。对外暴露 API。
任务：
1. /api/ask（POST，SSE）：流式推送 意图→SQL→结果→图表→洞察 / 或 RAG 答案+引用。
2. /api/ask_sync（POST）：同步返回完整结果（调试）。
3. /api/kb/upload、/api/kb/list：知识库上传（触发 T5 管线）与列表。
4. /api/history：会话历史。
技术栈：FastAPI、StreamingResponse（SSE）、Pydantic。
交付物：app/main.py + 路由 + schema。
验收标准：SSE 分阶段流式正常；上传文档能进知识库并可问答；接口有自动文档（/docs）；错误有结构化返回。` },
  { id: "T12", name: "前端（非重点，够用即可）", dep: "T11", stage: "前端",
    prompt: `角色：前端工程师。
背景：API（T11）就绪。做对话式界面。
任务：对话消息流 + SSE 流式逐字渲染 + ECharts 图表卡片 + 引用来源卡片 + 知识库上传/管理页 + 历史会话。
技术栈：Vue 或 React + ECharts + EventSource（SSE）。
交付物：frontend/ 项目。
验收标准：能跑通"提问→看到流式过程→出图表/出带引用答案"；上传文档可用；界面整洁即可，不追求花哨。` },
  { id: "T13", name: "测试体系", dep: "T7–T11", stage: "测试",
    prompt: `角色：测试工程师。
背景：后端各模块陆续就绪。建可量化、可回归的测试体系。
任务：
1. 单测：pytest 覆盖 爬虫/清洗/Text2SQL/RAG/Agent/接口 关键路径。
2. Text2SQL 评测集：50-100 条「问题→标准 SQL/结果」，算执行准确率。
3. RAG 评测：RAGAS（faithfulness/answer relevancy/context precision&recall）+ 引用正确率。
4. 意图路由：标注集 + 混淆矩阵。
5. 数据质量：Great Expectations 套件（配合 T6）。
6. CI：DeepEval + pytest 接 GitHub Actions，PR 自动跑回归。
技术栈：pytest、RAGAS、DeepEval、Great Expectations、GitHub Actions。
交付物：tests/ + 评测集 + CI 配置 + 评测报告模板。
验收标准：核心模块有单测；三套评测（SQL/RAG/路由）能出分；CI 在 PR 上自动运行。` },
  { id: "T14", name: "部署上线（单台云 VPS）", dep: "T11", stage: "运维",
    prompt: `角色：运维/部署工程师。
背景：应用就绪，要部署到单台云 VPS 上线。
任务：
1. 服务器：给出 VPS 配置建议（2C4G 起，CPU 跑 MinerU）与采购清单。
2. 容器化：为各服务写 Dockerfile，docker-compose 拉起 FastAPI + Celery Worker + PostgreSQL(pgvector) + Redis + MinIO + Caddy。
3. HTTPS：Caddy 自动证书 + 域名。
4. CI/CD：GitHub Actions 构建镜像 + 部署。
5. 调度：Celery Beat 跑定时采集/清洗。
6. 运维：日志、告警、定时备份（PG + MinIO）、安全（只读 DB 账号、防火墙、密钥用 .env 不入库）。
技术栈：Docker、docker-compose、Caddy、GitHub Actions、Celery Beat。
交付物：Dockerfile(s)、docker-compose.yml、Caddyfile、CI 配置、部署文档 docs/部署手册.md。
验收标准：一条 docker-compose up 拉起全栈；域名 HTTPS 可访问；定时采集自动跑；备份可恢复；密钥不进仓库。` },
];

const children = [];
// 封面
children.push(
  new Paragraph({ spacing: { before: 1700 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "车市镜 · 新能源汽车市场情报 Agent", bold: true, size: 30, color: BLUE })] }),
  new Paragraph({ spacing: { before: 220 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "开发任务拆解书", bold: true, size: 56 })] }),
  new Paragraph({ spacing: { before: 120 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "工单制（全栈认领）· 14 个任务包 · 每个含可直接发的提示词", size: 24, color: "555555" })] }),
  new Paragraph({ spacing: { before: 1500 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "版本 v1.0    日期 2026-05-22", size: 22, color: "555555" })] }),
  new Paragraph({ children: [new PageBreak()] }),
);
// 锁定技术栈
children.push(h1("一、已锁定技术栈（本书基准）"));
children.push(table([2400, 6960], [
  ["层次", "选型"],
  ["爬虫采集", "Scrapling（抓取+反爬绕过+自适应解析）+ Celery/Redis 调度 + 付费代理池"],
  ["文档解析", "MinerU（CPU 模式，PDF→Markdown）"],
  ["清洗治理", "Pandas/Polars · RapidFuzz · datasketch · Great Expectations"],
  ["原始存储", "MinIO 对象存储（明确不用 Hadoop）"],
  ["结构化", "SQLite（demo）→ PostgreSQL · 星型维度建模 · SQLAlchemy"],
  ["向量", "pgvector（同 PG）· BGE-large-zh Embedding（独立于对话模型）"],
  ["对话 LLM", "DeepSeek-V4（OpenAI 兼容，可切换）"],
  ["Agent", "LangGraph + LangChain"],
  ["后端/前端", "FastAPI（SSE）/ Vue 或 React + ECharts"],
  ["测试", "pytest + RAGAS + DeepEval(CI) + Great Expectations"],
  ["部署", "单台云 VPS · Docker + docker-compose + Caddy(HTTPS)"],
]));
children.push(p([bold("协作方式："), txt("5 人小公司、全栈制不分专职。下列 14 个任务包按依赖排序，谁有空认哪个；每个任务包的「提示词」可直接复制发给执行者（或粘进 Claude Code）。")]));
children.push(new Paragraph({ children: [new PageBreak()] }));
// 依赖总览
children.push(h1("二、工单依赖总览"));
children.push(table([900, 3400, 1600, 1100, 2360], [
  ["#", "工单", "依赖", "阶段", "关键产物"],
  ["T1", "数据源调研与字段探针", "—", "数据", "字段清单（阻塞 T2）"],
  ["T2", "schema 定稿 + 建库建模", "T1", "数据", "schema.sql / models.py"],
  ["T3", "Scrapling 正式采集", "T2", "数据", "app/crawler"],
  ["T4", "清洗治理流水线", "T3", "数据", "app/etl + DWD/DWS"],
  ["T5", "MinerU 文档知识库管线", "T2", "数据", "app/kb + pgvector"],
  ["T6", "数据质量与监控", "T4", "数据", "app/dq"],
  ["T7", "Text2SQL 引擎", "T4", "Agent", "text2sql/护栏/重试"],
  ["T8", "图表 + 洞察归因", "T7", "Agent", "charts.py/insights.py"],
  ["T9", "RAG 问答引擎", "T5", "Agent", "app/rag"],
  ["T10", "LangGraph 编排", "T7,T9", "Agent", "app/agent"],
  ["T11", "FastAPI 接口", "T10", "Agent", "app/main + 路由"],
  ["T12", "前端", "T11", "前端", "frontend/"],
  ["T13", "测试体系", "T7–T11", "测试", "tests + 评测集 + CI"],
  ["T14", "部署上线", "T11", "运维", "compose/Caddy/CI"],
]));
children.push(p([bold("关键路径："), txt("T1 → T2 → T3 → T4 → T7 → T10 → T11 →（T14 上线 / T13 测试）。T1 是总阻塞点：未探明真实字段前不要急着建表。")]));
children.push(new Paragraph({ children: [new PageBreak()] }));
// 各工单详情
children.push(h1("三、工单明细（含可直接发的提示词）"));
const STAGE_COLOR = { 数据: "2E7D32", Agent: "1565C0", 前端: "6A1B9A", 测试: "AD6800", 运维: "B71C1C" };
TASKS.forEach((t, i) => {
  children.push(new Paragraph({ heading: HeadingLevel.HEADING_2,
    children: [new TextRun(`${t.id}　${t.name}`)] }));
  children.push(table([1560, 1560, 1560, 4680], [
    [{ }, { }, { }, { }].map ? undefined : undefined, // placeholder removed below
  ].length ? [["工单号", t.id, "阶段", t.stage], ["依赖", t.dep, "状态", "待认领"]] : []));
  // 说明：上面 table 占位会出错，改为直接构造
});
// 重新构造（上面的 forEach 仅用于标题顺序参考，实际内容在此重建）
children.length = children.findIndex((c) => false) === -1 ?
  children.length : children.length;

const doc = new Document({
  creator: "车市镜项目组", title: "开发任务拆解书",
  styles: {
    default: { document: { run: { font: FONT, size: 22 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 32, bold: true, font: FONT, color: BLUE },
        paragraph: { spacing: { before: 280, after: 160 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 26, bold: true, font: FONT, color: "2E5496" },
        paragraph: { spacing: { before: 220, after: 100 }, outlineLevel: 1 } },
    ],
  },
  numbering: { config: [
    { reference: "bul", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
      style: { paragraph: { indent: { left: 540, hanging: 280 } } } }] },
  ] },
  sections: [{
    properties: { page: { size: { width: 12240, height: 15840 },
      margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } } },
    headers: { default: new Header({ children: [new Paragraph({
      border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: BLUE, space: 4 } },
      tabStops: [{ type: TabStopType.RIGHT, position: TabStopPosition.MAX }],
      children: [new TextRun({ text: "车市镜 · 开发任务拆解书（工单制）", size: 16, color: "888888" }),
        new TextRun({ text: "\tv1.0", size: 16, color: "888888" })] })] }) },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: "第 ", size: 18, color: "888888" }),
        new TextRun({ children: [PageNumber.CURRENT], size: 18, color: "888888" }),
        new TextRun({ text: " 页", size: 18, color: "888888" })] })] }) },
    children: buildChildren(),
  }],
});

function buildChildren() {
  const c = [];
  // 封面
  c.push(
    new Paragraph({ spacing: { before: 1700 }, alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: "车市镜 · 新能源汽车市场情报 Agent", bold: true, size: 30, color: BLUE })] }),
    new Paragraph({ spacing: { before: 220 }, alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: "开发任务拆解书", bold: true, size: 56 })] }),
    new Paragraph({ spacing: { before: 120 }, alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: "工单制（全栈认领）· 14 个任务包 · 每个含可直接发的提示词", size: 24, color: "555555" })] }),
    new Paragraph({ spacing: { before: 1500 }, alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: "版本 v1.0    日期 2026-05-22", size: 22, color: "555555" })] }),
    new Paragraph({ children: [new PageBreak()] }),
  );
  c.push(h1("目录"));
  c.push(new TableOfContents("目录", { hyperlink: true, headingStyleRange: "1-2" }));
  c.push(new Paragraph({ children: [new PageBreak()] }));
  // 一、技术栈
  c.push(h1("一、已锁定技术栈（本书基准）"));
  c.push(table([2400, 6960], [
    ["层次", "选型"],
    ["爬虫采集", "Scrapling（抓取+反爬绕过+自适应解析）+ Celery/Redis 调度 + 付费代理池"],
    ["文档解析", "MinerU（CPU 模式，PDF→Markdown）"],
    ["清洗治理", "Pandas/Polars · RapidFuzz · datasketch · Great Expectations"],
    ["原始存储", "MinIO 对象存储（明确不用 Hadoop）"],
    ["结构化", "SQLite（demo）→ PostgreSQL · 星型维度建模 · SQLAlchemy"],
    ["向量", "pgvector（同 PG）· BGE-large-zh Embedding（独立于对话模型）"],
    ["对话 LLM", "DeepSeek-V4（OpenAI 兼容，可切换）"],
    ["Agent", "LangGraph + LangChain"],
    ["后端/前端", "FastAPI（SSE）/ Vue 或 React + ECharts"],
    ["测试", "pytest + RAGAS + DeepEval(CI) + Great Expectations"],
    ["部署", "单台云 VPS · Docker + docker-compose + Caddy(HTTPS)"],
  ]));
  c.push(p([bold("协作方式："), txt("5 人小公司、全栈制不分专职。下列 14 个任务包按依赖排序，谁有空认哪个；每个任务包的「提示词」可直接复制发给执行者（或粘进 Claude Code）。")]));
  c.push(p([bold("公共约定（每个工单默认）："), txt("仓库 D:\\lgb\\t1\\bi-agent-starter；DeepSeek-V4 走 app/config.py；Embedding 用本地 BGE-large-zh（独立于对话模型）；只读 DB 账号；合规红线：仅爬公开非登录数据、单域 ≤1QPS、去 PII、留来源 URL+时间。")]));
  c.push(new Paragraph({ children: [new PageBreak()] }));
  // 二、依赖总览
  c.push(h1("二、工单依赖总览"));
  c.push(table([760, 3300, 1500, 1000, 2800], [
    ["#", "工单", "依赖", "阶段", "关键产物"],
    ["T1", "数据源调研与字段探针", "—", "数据", "字段清单（阻塞 T2）"],
    ["T2", "schema 定稿 + 建库建模", "T1", "数据", "schema.sql / models.py"],
    ["T3", "Scrapling 正式采集", "T2", "数据", "app/crawler"],
    ["T4", "清洗治理流水线", "T3", "数据", "app/etl + DWD/DWS"],
    ["T5", "MinerU 文档知识库管线", "T2", "数据", "app/kb + pgvector"],
    ["T6", "数据质量与监控", "T4", "数据", "app/dq"],
    ["T7", "Text2SQL 引擎", "T4", "Agent", "text2sql/护栏/重试"],
    ["T8", "图表 + 洞察归因", "T7", "Agent", "charts.py/insights.py"],
    ["T9", "RAG 问答引擎", "T5", "Agent", "app/rag"],
    ["T10", "LangGraph 编排", "T7,T9", "Agent", "app/agent"],
    ["T11", "FastAPI 接口", "T10", "Agent", "app/main + 路由"],
    ["T12", "前端", "T11", "前端", "frontend/"],
    ["T13", "测试体系", "T7–T11", "测试", "tests + 评测集 + CI"],
    ["T14", "部署上线", "T11", "运维", "compose/Caddy/CI"],
  ]));
  c.push(p([bold("关键路径："), txt("T1 → T2 → T3 → T4 → T7 → T10 → T11 →（T14 上线 / T13 测试）。T1 是总阻塞点：未探明真实字段前不要急着建表。")]));
  c.push(new Paragraph({ children: [new PageBreak()] }));
  // 三、明细
  c.push(h1("三、工单明细（含可直接发的提示词）"));
  TASKS.forEach((t) => {
    c.push(new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun(`${t.id}　${t.name}`)] }));
    c.push(table([1500, 1700, 1500, 4660], [
      ["工单号", t.id, "阶段", t.stage],
      ["依赖", t.dep, "状态", "待认领"],
    ]));
    c.push(new Paragraph({ spacing: { before: 80, after: 40 },
      children: [new TextRun({ text: "▼ 提示词（复制即用）", bold: true, size: 20, color: BLUE })] }));
    c.push(codeBox(t.prompt.split("\n")));
    c.push(new Paragraph({ spacing: { after: 120 }, children: [new TextRun("")] }));
  });
  c.push(p([bold("—— 全书完。配套《PRD-1 数据获取与处理》《PRD-2 Agent 构建/整体项目》同目录。 ——")], { alignment: AlignmentType.CENTER }));
  return c;
}

Packer.toBuffer(doc).then((buf) => {
  const out = path.join(DIR, "开发任务拆解书.docx");
  fs.writeFileSync(out, buf);
  console.log("WROTE", out, buf.length, "bytes");
});
