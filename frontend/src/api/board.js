// 收藏看板 API：保存 / 列出 / 删除「洞察快照」。
// mock（localStorage，按用户分桶，可离线 demo）↔ live（真后端 /api/insights）一个开关切换，
// 与 history.js 同套路。快照 payload 复用消息结果结构 {columns,rows,chart,insight,citations,sql}。
import { ENDPOINTS, IS_MOCK } from './config.js'
import { authHeaders, getStoredUser } from './auth.js'

const key = (uid) => `cheshijing.board.${uid || 'anon'}`

async function jsonOrThrow(r) {
  let data = null
  try { data = await r.json() } catch {}
  if (!r.ok) {
    const d = data && data.detail
    throw new Error((typeof d === 'string' && d) || `请求失败（${r.status}）`)
  }
  return data
}

// 后端 insight 行 → 前端归一
function norm(d) {
  return {
    id: d.id,
    title: d.title || d.question || '未命名洞察',
    question: d.question || '',
    intent: d.intent || 'sql',
    payload: typeof d.payload === 'string' ? safeParse(d.payload) : (d.payload || {}),
    createdAt: d.created_at || d.createdAt || Date.now(),
  }
}
function safeParse(s) { try { return JSON.parse(s) } catch { return {} } }

// —— mock（localStorage）—— //
function mockRead() {
  try { return JSON.parse(localStorage.getItem(key(getStoredUser()?.id)) || '[]') } catch { return [] }
}
function mockWrite(list) {
  try { localStorage.setItem(key(getStoredUser()?.id), JSON.stringify(list)) } catch {}
}

export async function listInsights() {
  if (IS_MOCK) return mockRead().map(norm)
  const r = await fetch(ENDPOINTS.insights, { headers: { ...authHeaders() } })
  const data = await jsonOrThrow(r)
  return (data.insights || []).map(norm)
}

export async function saveInsight({ title, question, intent, payload }) {
  if (IS_MOCK) {
    const item = { id: 'b_' + Date.now().toString(36), title, question, intent, payload, created_at: Date.now() }
    const list = mockRead(); list.unshift(item); mockWrite(list)
    return norm(item)
  }
  const r = await fetch(ENDPOINTS.insights, {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ title, question, intent, payload: JSON.stringify(payload || {}) }),
  })
  return norm(await jsonOrThrow(r))
}

export async function deleteInsight(id) {
  if (IS_MOCK) { mockWrite(mockRead().filter((x) => x.id !== id)); return true }
  const r = await fetch(ENDPOINTS.insight(id), { method: 'DELETE', headers: { ...authHeaders() } })
  return jsonOrThrow(r)
}
