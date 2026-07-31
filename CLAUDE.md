# CLAUDE.md

Claude Code 与其他助手开工前，**先读 [`PROJECT-MEMORY/`](PROJECT-MEMORY/README.md)**（工具无关的项目记忆，权威上下文），入口与速览见 [`AGENTS.md`](AGENTS.md)。

本项目 = 车市镜：新能源汽车市场情报对话式 Agent（双脑 Text2SQL + RAG，LangGraph 编排）。技术栈、数据源、已定死的表结构（`sql/schema.sql`）、进度与踩坑全部记录在 `PROJECT-MEMORY/`。

> 注：`C:\Users\…\.claude\projects\…\memory\` 是 Claude Code 私有记忆副本，可能不被其他工具读取；**以仓库内的 `PROJECT-MEMORY/` 为准**，变更时两边尽量同步。
