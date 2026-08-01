# AGENTS.md

> 车市镜 / EV-MarketLens 的协作入口。开始改动前，先完整阅读
> [`PROJECT-MEMORY/README.md`](PROJECT-MEMORY/README.md) 及其列出的四份文档，
> 再阅读 [`docs/technical-design.md`](docs/technical-design.md)。

## 当前事实

- 产品是新能源汽车市场情报对话式 Agent，双脑为 Text2SQL 与 RAG。
- LangGraph 当前有 13 个节点、五类意图：`sql / rag / hybrid / clarify / chat`。
- 销量主链路使用懂车帝公开 JSON API 和 Python 标准库 HTTP，不依赖浏览器。
- 当前解析后端是 `PARSER_BACKEND=lite`；MinerU 仅预留，尚未接入。
- 对话模型通过 OpenAI-compatible 环境变量配置，不锁定单一厂商或不存在的模型名。
- Embedding 使用 BGE-large-zh，不能使用对话模型代替；向量记录版本和维度血缘。
- 本地 RAG 为 SQLite + numpy；生产配置为 PostgreSQL + pgvector、MinIO、Redis + Celery。
- 无数据研究结果仅在 Review 允许时写入发起用户私有 RAG，不回写销量事实表，也不自动重跑 SQL。
- `ev-market-lens` 是唯一权威仓库；`study_code/车市镜` 只做精确镜像。
- 生产配置已经具备，但云服务器 fresh-volume E2E 尚未验收，不能写成“已生产验证”。

## 修改约定

- 行为变化必须同时核对代码、`README.md`、`docs/technical-design.md`、相关 Mermaid 图和 `PROJECT-MEMORY/`。
- 评测数字只能来自当前可追溯报告；固定回归集通过率不能外推为开放域准确率。
- 不提交 `.env`、API key、模型权重、本地数据库、原始大文件、构建产物或本机私有记忆。
- 不恢复已废弃的旧 PRD、旧工作记录、旧流程图或旧 RAG 构建脚本作为当前入口。
- 主仓库完成并验证后，才把同一 tracked tree 同步到 `study_code/车市镜`；镜像不独立开发。

## 标准验证

```bash
python -m pytest tests/ -m "not integration" -q
python -m pytest tests/ -m integration -q
python eval/text2sql_eval.py --check-gold
python eval/intent_eval.py
python eval/rag_eval.py
npm --prefix frontend run build
cp .env.prod.example .env.prod
docker compose --env-file .env.prod -f deploy/docker-compose.prod.yml config -q
```

Windows 本地优先使用仓库 `.venv\Scripts\python.exe`。若命令、报告或代码冲突，
以实际代码和可重新运行的证据为准，并同步修正文档。
