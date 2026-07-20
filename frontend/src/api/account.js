// 账户自助 API：改昵称 / 改密码 / 我的用量。mock ↔ live 一个开关切换。
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

function _findRec(users, id) {
  for (const k of Object.keys(users)) if (users[k].id === id) return users[k]
  return null
}
function _boardCount() {
  try { return JSON.parse(localStorage.getItem(`cheshijing.board.${getStoredUser()?.id}`) || '[]').length } catch { return 0 }
}

export async function updateNickname(nickname) {
  if (IS_MOCK) {
    const users = loadMockUsers(); const rec = _findRec(users, getStoredUser()?.id)
    if (rec) { rec.nickname = nickname; saveMockUsers(users) }
    return { ...(getStoredUser() || {}), nickname }
  }
  const r = await fetch(ENDPOINTS.me, { method: 'PATCH', headers: { 'Content-Type': 'application/json', ...authHeaders() }, body: JSON.stringify({ nickname }) })
  return (await jsonOrThrow(r)).user
}

export async function changePassword(oldPassword, newPassword) {
  if (IS_MOCK) {
    const users = loadMockUsers(); const rec = _findRec(users, getStoredUser()?.id)
    if (!rec || rec.password !== oldPassword) throw new Error('原密码不正确')
    if ((newPassword || '').length < 6) throw new Error('新密码至少 6 位')
    rec.password = newPassword; saveMockUsers(users); return { ok: true }
  }
  const r = await fetch(ENDPOINTS.changePassword, { method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeaders() }, body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }) })
  return jsonOrThrow(r)
}

export async function myStats() {
  if (IS_MOCK) return { conversations: 0, questions: 0, insights: _boardCount() }
  const r = await fetch(ENDPOINTS.myStats, { headers: { ...authHeaders() } })
  return jsonOrThrow(r)
}
