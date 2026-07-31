import { reactive, computed } from 'vue'
import { API, IS_MOCK, getToken, setToken, clearToken, getUser, setUser } from '@/api/config.js'

const state = reactive({
  user: getUser(),
  token: getToken(),
  error: '',
  pending: false,
})

export const isAuthed = computed(() => !!state.token && !!state.user)

// —— mock 账号（localStorage，可离线 demo；用户名 admin 即管理员）—— //
const MOCK_KEY = 'cheshijing_mock_users'
const loadMU = () => { try { return JSON.parse(localStorage.getItem(MOCK_KEY) || '{}') } catch { return {} } }
const saveMU = (u) => { try { localStorage.setItem(MOCK_KEY, JSON.stringify(u)) } catch {} }
const pub = (r) => ({ id: r.id, username: r.username, nickname: r.nickname, role: r.role || (r.username === 'admin' ? 'admin' : 'user') })

function applySession(access_token, user) { setToken(access_token); setUser(user); state.token = access_token; state.user = user }

async function login(username, password) {
  state.pending = true; state.error = ''
  try {
    if (IS_MOCK) {
      const rec = loadMU()[username]
      if (!rec || rec.password !== password) throw new Error('账号或密码不正确')
      applySession(`mock.${rec.id}`, pub(rec)); return
    }
    const r = await fetch(API.login, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username, password }) })
    const d = await r.json()
    if (!r.ok) throw new Error(d.detail || '登录失败')
    applySession(d.access_token, d.user)
  } catch (e) { state.error = e.message } finally { state.pending = false }
}

async function register(username, password, nickname) {
  state.pending = true; state.error = ''
  try {
    if (IS_MOCK) {
      const users = loadMU()
      if (users[username]) throw new Error('该账号已存在，请直接登录')
      const rec = { id: 'u_' + Date.now().toString(36), username, nickname: nickname || username, password, role: username === 'admin' ? 'admin' : 'user' }
      users[username] = rec; saveMU(users)
      applySession(`mock.${rec.id}`, pub(rec)); return
    }
    const r = await fetch(API.register, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username, password, nickname }) })
    const d = await r.json()
    if (!r.ok) throw new Error(d.detail || '注册失败')
    await login(username, password)
  } catch (e) { state.error = e.message } finally { state.pending = false }
}

function logout() { clearToken(); state.token = null; state.user = null }

export function useAuth() { return { state, isAuthed, login, register, logout } }
