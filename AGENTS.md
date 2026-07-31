# AGENTS.md —— 给任何 AI / 编程助手的入口

> 你正在接手「车市镜」项目（新能源汽车市场情报对话式 Agent）。
> **开工前请先完整阅读 [`PROJECT-MEMORY/`](PROJECT-MEMORY/README.md) 文件夹**——那里是工具无关、纯 markdown 的项目记忆，包含产品方向、技术栈、数据源与已定死的表结构、交付物与进度、踩坑记录。

## 30 秒速览
- **产品**：车市镜 / EV-MarketLens —— 新能源汽车市场情报 **对话式 Agent**（双脑：Text2SQL + RAG，LangGraph 编排）。
- **目标**：作品级产品，服务 2026 秋招拿高薪 / 未来创业；核心卖点 = 大模型应用/Agent 工程。
- **技术栈**：Scrapling 爬虫 · MinerU 解析 · DeepSeek-V4 对话 · BGE-large-zh 向量 · PostgreSQL+pgvector · MinIO · FastAPI(SSE) · 单台云 VPS。
- **数据**：懂车帝销量榜 API（公开免登录），schema 已定死见 `sql/schema.sql` 与 `PROJECT-MEMORY/03-数据源与表结构.md`。
- **进度**：方向/技术栈/三份 PRD 已定，T1（数据探针+定 schema）已完成。下一步见 `PROJECT-MEMORY/04-交付物与进度.md`。

## 重要约定
- 爬虫：个人非商用作品，公开数据全爬，不卡 robots；防封措施仅为稳定。
- scrapling 必须用专用 venv：`C:\Users\Lenovo\.claude\skills\scrapling\.venv\Scripts\python.exe`；取响应内容用 `page.body`。
- Embedding 用 BGE，**不要**用对话模型做向量化；坚决不上 Hadoop。
- 有重要决策变更 → 同步更新 `PROJECT-MEMORY/` 对应文件。


<claude-mem-context>
# Memory Context

# [bi-agent] recent context, 2026-06-11 10:05pm GMT+8

Legend: 🎯session 🔴bugfix 🟣feature 🔄refactor ✅change 🔵discovery ⚖️decision 🚨security_alert 🔐security_note
Format: ID TIME TYPE TITLE
Fetch details: get_observations([IDs]) | Search: mem-search skill

Stats: 50 obs (15,144t read) | 222,654t work | 93% savings

### May 27, 2026
745 10:09a 🔵 Search for "omclaude" download returns OpenClaude, clarifying OMC as intended target
747 " 🔵 Oh-my-claudecode (OMC) v4.14.0 installation methods and ecosystem documented
748 " 🔵 Reasonix identified as DeepSeek-native AI coding agent
749 " 🔵 System Node.js version v24.15.0 meets Reasonix requirement
750 10:10a 🔵 Anthropic Claude desktop app found but Claude Code CLI not detected
752 " 🔵 Claude Code CLI is already installed via npm as @anthropic-ai/claude-code v2.1.152
751 10:11a ✅ Installing Reasonix globally via npm
754 " 🔴 npm install -g reasonix completed with empty output, indicating installation failure
753 10:13a 🔵 Claude Code CLI binary confirmed present inside npm package — npm executable registration is corrupted
755 10:14a 🔴 Attempted to repair Claude Code CLI by running postinstall script directly
756 10:15a 🔵 Claude Code plugin system is functional with existing plugin infrastructure
757 10:16a 🔵 Claude Code already has 6 marketplaces and 9 installed plugins including superpowers v5.1.0
758 10:17a 🔵 Untitled
759 " 🔵 Oh-my-claudecode git clone failed due to network RPC error on Windows
760 10:19a 🟣 Oh-my-claudecode repository successfully cloned into Claude Code marketplaces
761 10:20a 🟣 Oh-my-claudecode v4.14.4 cloned — newer than web search suggested — with 39 skills
762 " 🔵 Oh-my-claudecode cloned at commit 2733c1683ad375aae9eb26e979cc079f17673568
763 10:22a 🟣 Oh-my-claudecode manually installed into plugin cache at expected paths
764 " 🟣 OMC marketplace registered in known_marketplaces.json via PowerShell workaround
765 " 🟣 Oh-my-claudecode fully installed and enabled via manual registration in installed_plugins.json and settings.json
766 " 🟣 OMC installation verified across all four registration points
767 10:41a ✅ Cleaned global reasonix npm package and npm cache
768 10:42a ✅ Reinstalled reasonix npm package globally
769 " 🔵 Reasonix CLI tool version 0.52.0 verified
771 10:43a 🔵 Reasonix fresh install — no existing config found
770 10:44a ✅ Claude HUD setup initiated
772 " 🔵 D:\bi-agent project uses Qwen/Tongyi Qianwen via DashScope
773 " 🔵 Claude-hud plugin detected in cache and registry but not configured
774 " 🔵 bi-agent project actually uses DeepSeek API, not Qwen
775 " ✅ Configured Reasonix with DeepSeek API for first use
776 " 🔵 Reasonix doctor confirms full health with DeepSeek API balance
777 10:47a 🔵 User queries about deployment steps after domain approval
778 " 🔵 车市镜 deployment infrastructure explored for production deployment
779 10:48a 🔵 Makefile provides one-command production operations for carmirror deployment
780 " 🔵 车市镜 deployment architecture fully documented after domain approval
784 10:49a ✅ Primary agent shifts focus to troubleshooting claude-hud configuration
S118 用户选择 option A 继续推进部署，使用 /plan 生成了香港 2C8G 服务器部署计划 (May 27, 10:50 AM)
781 10:52a 🔵 bi-agent production deployment architecture documented in docker-compose
782 " 🔵 bi-agent deployment infrastructure files explored
783 " ⚖️ Deployment plan generated for 2C8G Hong Kong server
S119 用户遇到 Claude Code 报错：API 400 错误，content[].thinking must be passed back。诊断原因并给止血方案 (May 27, 10:56 AM)
785 10:57a 🔴 Claude-HUD "句柄无效" error resolved by suppressing stderr output
S120 Diagnose Claude Code 400 error with extended thinking, suspected claude-mem or hook interference (May 27, 10:59 AM)
786 11:01a 🔵 User reported claudecode monitoring plugin not displaying
787 " 🔵 Investigated installed Claude Code plugins on the system
788 " 🔵 Examined Claude Code settings and monitoring plugin configuration
789 " 🔵 Audited installed plugin versions and metadata
790 11:02a 🔵 User requests local run then deployment to Hong Kong server
S121 Diagnose and fix Claude Code 400 error on tool calls caused by DeepSeek API proxy + extended thinking incompatibility (May 27, 11:03 AM)
791 11:03a 🔵 Claude Code configured to proxy through DeepSeek API
792 " 🔵 No hooks JSON files found in any plugin directories
793 11:04a ✅ effortLevel reduced from xhigh to low to diagnose 400 error
S122 Switch Claude Code from DeepSeek proxy to native Anthropic Pro to resolve extended thinking 400 error (May 27, 11:06 AM)
794 11:06a ✅ Switched from DeepSeek proxy to native Anthropic API for Claude Code
S123 Reboot Claude Code on Anthropic Pro — user restored effortLevel to xhigh and logged into Pro (May 27, 11:07 AM)
S124 User asked why Claude Code previously showed "Opus 4.7" model but now shows "4.6" — both on Claude Pro subscription (May 27, 11:09 AM)
795 11:13a 🔵 User reports model downgrade from Opus 4.7 to 4.6 on Pro plan
S125 User shared a screenshot of a Claude Code window showing Opus 4.7 and asked if it's real or fake — assistant confirmed it's genuine Anthropic Opus 4.7 (May 27, 11:14 AM)
S126 User triggered `/pulse` command — assistant investigated current statusLine configuration and found claude-hud is active, not pulse (May 27, 11:16 AM)
### Jun 1, 2026
S127 User requested step-by-step deployment guide for a project to Hong Kong 2C8G server with domain connection, plus restart procedures for server reboot. Project intended for technical interview demonstrations. (Jun 1, 1:10 PM)
**Investigated**: Examined deployment requirements across 13 phases: local repo finalization (A), server preparation with Docker/swap (B), code checkout and secrets management (C), model/data transfer (D), Docker build and HTTPS setup (E), data ingestion (F), account creation and validation (G), backup automation (H). Analyzed auto-restart behavior: Docker daemon, container restart policies, Caddy certificate persistence, data volume persistence, scheduled tasks (beat container + cron).

**Learned**: Deployment architecture spans 8 containerized services with `restart: always` policy ensuring automatic startup after server reboot. Certificate renewal is automatic for 90 days. Memory constraints on 2C8G require override config (uvicorn workers=1, celery concurrency=1, PostgreSQL tuning). Four restart scenarios documented: temporary shutdown (auto-recover), incomplete startup (manual compose up), long shutdown (cert auto-renews), full restart (restart or down/up). Pre-flight schema change required: `message` table needs `result_meta TEXT` column for ORM alignment.

**Completed**: Comprehensive deployment documentation created with all 13 phases, command templates, and conditional restart guides. Chapter marked as "部署到香港 2C8G 服务器" with recovery procedures documented. Pre-deployment checklist established: two local repo file changes needed before server execution. Interview demo health check script provided (6-step validation).

**Next Steps**: Waiting for user to provide 3 configuration values: domain name, server public IP, SSH entry method (user@IP + auth type). Once received: Phase A execution (modify schema file and docker-compose override template, commit and push). Then proceed through phases B-H with substituted values in provided command templates.


Access 223k tokens of past work via get_observations([IDs]) or mem-search skill.
</claude-mem-context>