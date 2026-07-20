// 全局鉴权状态（模块级单例）：登录态、当前用户，持久化到 localStorage。
// App 守卫、TopBar、Sidebar、useChat 都从这里读同一份状态。
import { reactive, computed } from 'vue'
import * as authApi from '@/api/auth.js'

const state = reactive({
  user: authApi.getStoredUser(),   // {id,nickname,username} | null
  token: authApi.getToken(),       // string | null
  pending: false,
  error: '',
})

const isAuthed = computed(() => !!state.token && !!state.user)
const isAdmin = computed(() => (state.user?.role || 'user') === 'admin')

/** 更新当前用户（改昵称后同步展示），持久化到 localStorage。 */
function setUser(patch) {
  state.user = { ...(state.user || {}), ...patch }
  authApi.updateStoredUser(patch)
}

async function login(payload) {
  state.pending = true; state.error = ''
  try {
    const { access_token, user } = await authApi.login(payload)
    authApi.setSession(access_token, user)
    state.token = access_token; state.user = user
    return true
  } catch (e) {
    state.error = e.message || '登录失败'
    return false
  } finally { state.pending = false }
}

async function register(payload) {
  state.pending = true; state.error = ''
  try {
    const { access_token, user } = await authApi.register(payload)
    authApi.setSession(access_token, user)
    state.token = access_token; state.user = user
    return true
  } catch (e) {
    state.error = e.message || '注册失败'
    return false
  } finally { state.pending = false }
}

function logout() {
  authApi.clearSession()
  state.token = null; state.user = null; state.error = ''
}

export function useAuth() {
  return { state, isAuthed, isAdmin, login, register, logout, setUser }
}
