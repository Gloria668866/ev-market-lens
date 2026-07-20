// 鉴权 API：mock（前端自洽，demo 用）↔ live（真后端）一个开关切换，与 ask 同套路。
// live 契约（已对齐后端 app/auth.py 实测实现，PRD-2 §17.3/§17.4）：
//   POST /api/auth/register {username,password,nickname?} -> {user:{...}}   ← 注意：不返回 token，需再 login
//   POST /api/auth/login    {username,password}           -> {access_token, token_type, user:{...}}
//   GET  /api/auth/me        (Bearer)                      -> {user:{...}}
//   错误体：FastAPI 风格 {detail:"..."}（注意不是 message）
//   其余受保护接口（/api/ask、/api/kb/*、/api/history）均按 Authorization: Bearer <token> 鉴权，
//   并按 user_id 做行级数据隔离。
import { ENDPOINTS, IS_MOCK } from './config.js'

const TOKEN_KEY = 'cheshijing.token'
const USER_KEY = 'cheshijing.user'
const MOCK_USERS_KEY = 'cheshijing.mock.users'

// —— token 读写（同步，供 sse/fetch 取用）—— //
export function getToken() {
  try { return localStorage.getItem(TOKEN_KEY) || null } catch { return null }
}
export function setSession(token, user) {
  try {
    localStorage.setItem(TOKEN_KEY, token)
    localStorage.setItem(USER_KEY, JSON.stringify(user))
  } catch {}
}
export function clearSession() {
  try { localStorage.removeItem(TOKEN_KEY); localStorage.removeItem(USER_KEY) } catch {}
}
export function getStoredUser() {
  try { return JSON.parse(localStorage.getItem(USER_KEY) || 'null') } catch { return null }
}
/** 局部更新已存用户（如改昵称后同步会话里的展示）。 */
export function updateStoredUser(patch) {
  try {
    const u = { ...(getStoredUser() || {}), ...patch }
    localStorage.setItem(USER_KEY, JSON.stringify(u))
    return u
  } catch { return getStoredUser() }
}
/** 给受保护请求加鉴权头；SSE 因走 fetch 同样可带（方案B）。 */
export function authHeaders() {
  const t = getToken()
  return t ? { Authorization: `Bearer ${t}` } : {}
}

// —— mock 实现（localStorage 存账号，纯前端，可离线 demo）—— //
// 离线也能体验管理员：用户名 'admin' 注册/登录即获 admin 角色。
export function loadMockUsers() {
  try { return JSON.parse(localStorage.getItem(MOCK_USERS_KEY) || '{}') } catch { return {} }
}
export function saveMockUsers(u) { try { localStorage.setItem(MOCK_USERS_KEY, JSON.stringify(u)) } catch {} }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const _pub = (rec) => ({ id: rec.id, username: rec.username, nickname: rec.nickname,
  role: rec.role || (rec.username === 'admin' ? 'admin' : 'user'), disabled: !!rec.disabled })

async function mockRegister({ username, password, nickname }) {
  await sleep(400)
  const users = loadMockUsers()
  if (users[username]) throw new Error('该账号已存在，请直接登录')
  const rec = { id: 'u_' + Date.now().toString(36), username, nickname: nickname || username,
    password, role: username === 'admin' ? 'admin' : 'user', disabled: false }
  users[username] = rec
  saveMockUsers(users)
  const user = _pub(rec)
  return { access_token: `mock.${user.id}.${Math.random().toString(36).slice(2)}`, user }
}
async function mockLogin({ username, password }) {
  await sleep(400)
  const users = loadMockUsers()
  const rec = users[username]
  if (!rec || rec.password !== password) throw new Error('账号或密码不正确')
  if (rec.disabled) throw new Error('账号已被禁用，请联系管理员')
  const user = _pub(rec)
  return { access_token: `mock.${user.id}.${Math.random().toString(36).slice(2)}`, user }
}

// —— live 实现 —— //
async function post(url, body) {
  const r = await fetch(url, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  })
  let data = null
  try { data = await r.json() } catch {}
  if (!r.ok) {
    // FastAPI 错误体是 {detail}；detail 可能是字符串或数组（校验错）
    const d = data && data.detail
    const msg = (typeof d === 'string' && d) || (Array.isArray(d) && d[0]?.msg) || `请求失败（${r.status}）`
    throw new Error(msg)
  }
  return data
}

async function liveLogin(payload) {
  const data = await post(ENDPOINTS.login, payload)   // {access_token, token_type, user}
  return { access_token: data.access_token, user: data.user }
}

async function liveRegister(payload) {
  // 后端 /register 只建账号、不发 token；注册成功后立即 login 拿 token
  await post(ENDPOINTS.register, payload)
  return liveLogin({ username: payload.username, password: payload.password })
}

export function register(payload) {
  return IS_MOCK ? mockRegister(payload) : liveRegister(payload)
}
export function login(payload) {
  return IS_MOCK ? mockLogin(payload) : liveLogin(payload)
}
