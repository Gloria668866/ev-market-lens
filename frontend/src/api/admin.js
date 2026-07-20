// 管理员后台 API：用户列表/概览/改角色禁用/重置密码/删除。mock ↔ live 一个开关切换。
import { ENDPOINTS, IS_MOCK } from './config.js'
import { authHeaders, getStoredUser, loadMockUsers, saveMockUsers } from './auth.js'

async function jsonOrThrow(r) {
  let data = null
  try { data = await r.json() } catch {}
  if (!r.ok) {
    const d = data && data.detail
    throw new Error((typeof d === 'string' && d) || (Array.isArray(d) && d[0]?.msg) || `请求失败（${r.status}）`)
  }
  return data
}

// —— mock helpers —— //
const _list = () => Object.values(loadMockUsers())
const _byId = (users, id) => Object.keys(users).find((k) => users[k].id === id)
const _role = (rec) => rec.role || (rec.username === 'admin' ? 'admin' : 'user')
const _adminCount = () => _list().filter((r) => _role(r) === 'admin').length
const _pub = (rec) => ({ id: rec.id, username: rec.username, nickname: rec.nickname, role: _role(rec),
  disabled: !!rec.disabled, created_at: rec.created_at || null, last_login_at: rec.last_login_at || null,
  conversations: 0, questions: 0, insights: 0 })

export async function listUsers() {
  if (IS_MOCK) return _list().map(_pub)
  const r = await fetch(ENDPOINTS.adminUsers, { headers: { ...authHeaders() } })
  return (await jsonOrThrow(r)).users || []
}

export async function overview() {
  if (IS_MOCK) {
    const us = _list()
    return { users: us.length, admins: us.filter((r) => _role(r) === 'admin').length,
      disabled: us.filter((r) => r.disabled).length, conversations: 0, questions: 0, insights: 0, shares: 0 }
  }
  const r = await fetch(ENDPOINTS.adminOverview, { headers: { ...authHeaders() } })
  return jsonOrThrow(r)
}

export async function patchUser(id, patch) {
  if (IS_MOCK) {
    const users = loadMockUsers(); const k = _byId(users, id)
    if (!k) throw new Error('用户不存在')
    const rec = users[k]; const me = getStoredUser()?.id
    if (patch.role !== undefined) {
      if (_role(rec) === 'admin' && patch.role !== 'admin' && _adminCount() <= 1) throw new Error('不能降级最后一个管理员')
      rec.role = patch.role
    }
    if (patch.disabled !== undefined) {
      if (rec.id === me && patch.disabled) throw new Error('不能禁用自己')
      if (patch.disabled && _role(rec) === 'admin' && _adminCount() <= 1) throw new Error('不能禁用最后一个管理员')
      rec.disabled = patch.disabled
    }
    saveMockUsers(users); return _pub(rec)
  }
  const r = await fetch(ENDPOINTS.adminUser(id), { method: 'PATCH', headers: { 'Content-Type': 'application/json', ...authHeaders() }, body: JSON.stringify(patch) })
  return (await jsonOrThrow(r)).user
}

export async function resetPassword(id, newPassword) {
  if (IS_MOCK) {
    const users = loadMockUsers(); const k = _byId(users, id)
    if (!k) throw new Error('用户不存在')
    if ((newPassword || '').length < 6) throw new Error('新密码至少 6 位')
    users[k].password = newPassword; saveMockUsers(users); return { ok: true }
  }
  const r = await fetch(ENDPOINTS.adminResetPwd(id), { method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeaders() }, body: JSON.stringify({ new_password: newPassword }) })
  return jsonOrThrow(r)
}

export async function deleteUser(id) {
  if (IS_MOCK) {
    const users = loadMockUsers(); const k = _byId(users, id)
    if (!k) throw new Error('用户不存在')
    if (users[k].id === getStoredUser()?.id) throw new Error('不能删除自己')
    if (_role(users[k]) === 'admin' && _adminCount() <= 1) throw new Error('不能删除最后一个管理员')
    delete users[k]; saveMockUsers(users); return { id, deleted: true }
  }
  const r = await fetch(ENDPOINTS.adminUser(id), { method: 'DELETE', headers: { ...authHeaders() } })
  return jsonOrThrow(r)
}
