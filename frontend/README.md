# 车市镜 · 前端门面

新能源车市情报对话式 BI Agent 的前端。Vue 3 + Vite + ECharts + 原生 SSE。

## 快速开始

```bash
cd frontend
npm install
npm run dev               # http://localhost:5173，默认连接 localhost:8001
```

先从仓库根目录运行 `scripts/start-dev.ps1` 启动完整演示。只调前端且不启动
后端时，可复制 `.env.example` 为 `.env`，再把 `VITE_DATA_SOURCE` 改为 `mock`。

## 连真后端

项目启动脚本默认把后端运行在 `:8001`。不创建 `.env` 时，Vite 开发模式也会
直接使用这个地址；如需覆盖，创建 `.env`：

```ini
VITE_API_BASE=http://localhost:8001
VITE_DATA_SOURCE=live
```

重启 `npm run dev` 即可。**无需改任何组件代码。**

> ⚠️ 后端需在 FastAPI 加 `CORSMiddleware` 放行 `http://localhost:5173`（当前 `app/main.py` 已用 `allow_origins=["*"]` 放行，OK）。

## 目录

```
src/
  api/        config(.env) · client(mock↔live 路由) · sse(POST-SSE) · events(协议归一化) · mock
  composables/useChat.js   对话状态机：SSE 事件 → 助手消息模型
  utils/chart.js           chart 负载 → ECharts option（兼容完整 option 与选图建议）
  components/ ...           Sidebar / TopBar / EmptyState / MessageList / 双脑结果卡 / Composer ...
```

项目架构、接口协议与运行边界见仓库根目录
[`docs/technical-design.md`](../docs/technical-design.md)；生产部署步骤见
[`deploy/DEPLOY.md`](../deploy/DEPLOY.md)。
