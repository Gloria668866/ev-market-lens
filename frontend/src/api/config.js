// 生产默认同源（"" → /api，由 Caddy 反代）；开发未配置时才回退到 localhost:8000。
// 不能用 `|| localhost`：Docker 有意注入空字符串时会被误判，导致线上浏览器请求访客自己的 localhost。
const DEFAULT_API_BASE = import.meta.env.DEV ? 'http://localhost:8000' : ''
export const API_BASE = (import.meta.env.VITE_API_BASE ?? DEFAULT_API_BASE).replace(/\/$/, '')

// 'mock' = 用本地 mock（后端未就绪）；'live' = 连真后端。
export const DATA_SOURCE = import.meta.env.VITE_DATA_SOURCE === 'mock' ? 'mock' : 'live'

export const IS_MOCK = DATA_SOURCE === 'mock'

export const ENDPOINTS = {
  ask: `${API_BASE}/api/ask`,          // POST + SSE
  askSync: `${API_BASE}/api/ask_sync`, // POST 一次性
  health: `${API_BASE}/health`,
  // 知识库（RAG，全部需 Bearer，按 user_id 隔离）
  kbList: `${API_BASE}/api/kb/list`,
  kbUpload: `${API_BASE}/api/kb/upload`,
  kbDoc: (id) => `${API_BASE}/api/kb/${id}`,    // GET 轮询状态 / DELETE 软删
  // 历史会话
  history: `${API_BASE}/api/history`,           // 会话列表
  historyDetail: (id) => `${API_BASE}/api/history/${id}`, // 会话消息（还原）
  register: `${API_BASE}/api/auth/register`,
  login: `${API_BASE}/api/auth/login`,
  me: `${API_BASE}/api/auth/me`,                          // GET 当前用户 / PATCH 改昵称
  changePassword: `${API_BASE}/api/auth/change-password`,
  myStats: `${API_BASE}/api/auth/stats`,
  // 管理员后台（需 admin 角色）
  adminOverview: `${API_BASE}/api/admin/overview`,
  adminUsers: `${API_BASE}/api/admin/users`,
  adminUser: (id) => `${API_BASE}/api/admin/users/${id}`,
  adminResetPwd: (id) => `${API_BASE}/api/admin/users/${id}/reset-password`,
  // 收藏看板（保存/列出/删除洞察快照，需 Bearer、按 user_id 隔离）
  insights: `${API_BASE}/api/insights`,
  insight: (id) => `${API_BASE}/api/insights/${id}`,
  // 分享（创建只读分享 + 公开读取，公开读取免鉴权）
  share: `${API_BASE}/api/share`,
  publicShare: (token) => `${API_BASE}/api/public/share/${token}`,
  // 车型报价（查 fact_price 实采数据）
  prices: `${API_BASE}/api/prices`,
  priceBrands: `${API_BASE}/api/prices/brands`,
  taskStream: (id) => `${API_BASE}/api/tasks/${id}/stream`,
}
