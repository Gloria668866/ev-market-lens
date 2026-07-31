// API 配置 — 本地连 localhost:8000，部署后改为服务器地址
const HOST = import.meta.env.VITE_API_HOST || 'http://localhost:8000'

// 'mock'(默认) = 前端自洽，可离线演示；'live' = 连真后端。与主站同套路。
export const DATA_SOURCE = import.meta.env.VITE_DATA_SOURCE === 'live' ? 'live' : 'mock'
export const IS_MOCK = DATA_SOURCE === 'mock'

export const API = {
  health: `${HOST}/health`,
  register: `${HOST}/api/auth/register`,
  login: `${HOST}/api/auth/login`,
  me: `${HOST}/api/auth/me`,
  ask: `${HOST}/api/ask`,
  askSync: `${HOST}/api/ask_sync`,
  history: `${HOST}/api/history`,
  historyDetail: (id) => `${HOST}/api/history/${id}`,
  kbList: `${HOST}/api/kb/list`,
  kbUpload: `${HOST}/api/kb/upload`,
  kbDelete: (id) => `${HOST}/api/kb/${id}`,
  prices: `${HOST}/api/prices`,
}

// Token 存储
const TOKEN_KEY = 'cheshijing_token'
const USER_KEY = 'cheshijing_user'

export function getToken() { return localStorage.getItem(TOKEN_KEY) }
export function setToken(t) { localStorage.setItem(TOKEN_KEY, t) }
export function clearToken() { localStorage.removeItem(TOKEN_KEY); localStorage.removeItem(USER_KEY) }

export function getUser() { try { return JSON.parse(localStorage.getItem(USER_KEY)) } catch { return null } }
export function setUser(u) { localStorage.setItem(USER_KEY, JSON.stringify(u)) }

export function authHeaders() {
  const t = getToken()
  return t ? { Authorization: `Bearer ${t}` } : {}
}
