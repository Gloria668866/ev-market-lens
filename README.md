# EV-MarketLens (车市镜)

> 对话式新能源汽车市场情报 Agent：自然语言提问 → 自动判断意图 → 查库出图 / 检索报告带引用作答。LangGraph 编排双脑协同。

---

## Demo 状态

当前为本地演示版本，暂无公开在线 Demo。

---

## 核心能力

| 能力 | 说明 |
|------|------|
| 数据脑 (Text2SQL) | 自然语言 → Schema Linking → SQL 生成 → sqlglot AST 安全护栏 → 只读执行 → 自校验重试 → 图表描述符 |
| 知识脑 (RAG) | 结构感知父子分块 → BGE-large-zh 向量化 → 混合召回(向量+全文 RRF) → bge-reranker → 父块归并 → 带引用生成 |
| Agent 编排 | LangGraph 状态图：5 层 NLU 路由 → sql / rag / hybrid / clarify / chat，支持重试环、并行 fan-out、澄清挂起 |
| 缺数自愈 | 查询无结果时创建采集任务；Redis/Celery 可用时进可靠队列，本地开发可退到非阻塞后台线程并持续回传进度 |
| 长期记忆 | 有界线程池后台提取 → 用户画像 + 会话摘要 → 关键词召回注入 |
| 产品工程 | JWT 多租户 · SSE 流式 · Vue3+ECharts 前端 · Docker 部署 |

---

## 架构

```mermaid
flowchart LR
    U[用户提问] --> API[FastAPI · SSE]
    API --> G{LangGraph 意图路由}
    G -->|sql| S[数据脑<br/>SchemaLink→GenSQL→护栏→执行→重试→图表→洞察]
    G -->|rag| R[知识脑<br/>混合召回→重排→父块归并→带引用生成]
    G -->|hybrid| S & R
    S --> C[compose 合并]
    R --> C
    C --> API
    S -.查.-> DB[(分析库<br/>dim/fact 星型模型)]
    R -.检索.-> VEC[(pgvector<br/>kb_chunk)]
```

---

## 一次请求调用链

```
用户提问 → intent_router (5层NLU)
  ├─ sql: schema_link → gen_sql → ensure_safe → exec_sql → verify_sql → chart → insight → compose
  ├─ rag: rag_retrieve → rag_answer → compose
  ├─ hybrid: [sql ∥ rag] 并行 → compose(defer=True)
  ├─ chat: chitchat → END
  └─ clarify: clarify → END
```

### Text2SQL 链路

1. **Schema Linking** — 语义描述匹配 + 实体信号增强
2. **SQL 生成** — LLM + domain prompt + few-shot
3. **安全护栏** — sqlglot AST 遍历，仅允许 SELECT
4. **执行** — 只读连接，失败回喂修正 (最多 2 次重试)
5. **语义自校验** — 确定性 SQL 结构校验先拦截 TopN、累计值、能源类型、排名变化等“能跑但答错”的查询，再由 LLM 做补充校验
6. **图表** — 规则引擎产出描述符，前端 ECharts 渲染

### RAG 链路

1. **文档入库** — 解析 → 结构感知父子分块 (子块~280token/父块~900token)
2. **混合召回** — 向量 + 全文，RRF(k=60) 融合
3. **Reranker** — bge-reranker；不可用时必须满足向量与关键词双路命中，证据不足直接拒答
4. **父块归并** — 去重/相邻合并/预算裁剪/冲突并列
5. **生成** — 带引用，has_answer 防幻觉

### 长期记忆

- **L2 Episode**: 会话摘要 (仅从用户消息提取，禁止保存数字结论)
- **L3 Profile**: 用户偏好画像 (白名单: 品牌/指标/车型/输出风格)
- **调度**: ThreadPoolExecutor(2) + msg_count 新消息判定 + 进程内去重
- **召回**: 关键词匹配 + 时间衰减；无关键词时不注入
- **安全**: 敏感过滤、不可信数据标记、fail-open

---

## 评测方法

| 评测 | 方法 | 说明 |
|------|------|------|
| Text2SQL | 执行结果集等价比对 | 位置元组比较，等价 SQL 算对 |
| 意图路由 | 混淆矩阵 + per-class P/R/F1 | 100 条标注样本 |
| RAG | 检索命中 + 负样本拒答 | 正样本验证目标文档召回，负样本验证证据不足时拒答 |
| 数据质量 | GE-style 断言 | pytest 门禁 (表行数、枚举值、NULL 率) |

> 评测使用 RAGAS/GE 的**指标定义**自实现，非直接调用官方库。CI 通过 pytest 红线门禁把关。

---

## 当前可复现指标

以下结果来自本地当前代码与当前模型，不沿用旧截图：

| 指标 | 值 | 方法 |
|------|---|------|
| 自动化测试 | 以本次运行结果为准 | `python -m pytest tests/ -m "not integration" -q` |
| Gold SQL 可执行率 | 60/60 | `--check-gold` |
| Text2SQL 回归集 EX | 60/60（首次 59/60，重试 +1.7pp） | 修正空 Gold 后的最新全量运行 |
| 意图规则测试 | 15/15 | 确定性 layer5 |
| 记忆安全测试 | 28/28 | mock LLM + SQLite |
| 小样本 RAG 严格通过 | 13/13 | 预期文档全召回且证据门控判定可答 |
| RAG 负样本拒答 | 3/3 | 未收录车型/主题不得用相似品牌内容作答 |

> Text2SQL 的 60/60 是修正空 Gold 后最新一次固定回归集全量通过，不等于线上未知问法 100% 泛化准确率。RAG 也只有 13 条正样本 + 3 条负样本；这些指标用于防回归，不包装成生产级统计结论。

---

## 快速启动

### Windows 快速启动

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
# 填好 .env，并把 BGE / reranker 权重放入 models/ 后：
npm --prefix frontend install
powershell -ExecutionPolicy Bypass -File .\scripts\start-dev.ps1
```

默认地址：前端 `http://127.0.0.1:5173`，后端 `http://127.0.0.1:8001`。停止本次脚本启动的进程：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\stop-dev.ps1
```

Linux/macOS 可按相同步骤创建虚拟环境，并分别执行
`uvicorn app.main:app --host 127.0.0.1 --port 8001` 与
`npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173`。

### 数据重建

本仓库**不附带数据库文件**，需自行采集：

```bash
python data/crawl_sales.py   # 采集懂车帝销量榜
python data/clean_load.py    # 清洗 → 星型模型 → SQLite
python seed.py               # 创建默认用户
```

### (可选) 完整双脑

```bash
docker compose -f deploy/docker-compose.dev.yml up -d
python data/build_local_kb.py
```

---

## 测试

```bash
python -m pytest tests/ -m "not integration" -q
python eval/text2sql_eval.py --check-gold
npm --prefix frontend run build
```

---

## 部署

见 [`deploy/DEPLOY.md`](deploy/DEPLOY.md)

---

## 已知限制

- 本地 RAG 使用 SQLite + numpy 暴力向量检索 + jieba 关键词召回，适合演示小语料；大语料生产部署使用 PostgreSQL+pgvector
- Embedding/Reranker 模型不在仓库 (~2.6GB)，需首次下载
- 评测样本: Text2SQL 60 条、意图 100 条、RAG 13 条正样本 + 3 条负样本
- 长期记忆: 关键词匹配，无向量检索
- 本地无 Redis 时的采集任务退路是单进程内存态，重启会丢失；生产必须使用 Redis + Celery
- 当前目标是作品集/面试演示级可靠性，不宣称高并发生产就绪

---

## 技术取舍

- 为什么 LangGraph → 显式状态+环+并行+可观测 (详见 `docs/工作记录/`)
- 为什么自实现 judge → 避免 langchain 全家桶
- 为什么双层 SQL 校验 → 确定性高价值规则 fail-closed；LLM 校验器自身故障时 fail-open，避免可用性被第二个模型调用拖垮
- 为什么父子分块 → 检索精度 vs 上下文完整

---

## License

MIT
