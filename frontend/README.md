# 车市镜 · 前端门面

新能源车市情报对话式 BI Agent 的前端。Vue 3 + Vite + ECharts + 原生 SSE。

## 快速开始

```bash
cd frontend
cp .env.example .env      # 首次：生成本地配置（默认 mock 数据源）
npm install
npm run dev               # http://localhost:5173
```

打开后在空状态点任意示例问题即可看到「思考过程 → 图表卡 + 结论」或「带引用的答案」。

## 连真后端

后端（`app/main.py`，默认 `:8000`）就绪后，把 `.env` 改成：

```ini
VITE_API_BASE=http://localhost:8000
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
