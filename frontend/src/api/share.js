// 一键分享：把一条结果生成只读公开快照，得到 /s/{token} 链接。
// mock（localStorage，按 token 存，可同浏览器演示）↔ live（后端 /api/share + 公开读取）。
import { ENDPOINTS, IS_MOCK } from './config.js'
import { authHeaders } from './auth.js'

const key = (token) => `cheshijing.share.${token}`

export function shareUrl(token) {
  return `${window.location.origin}/s/${token}`
}

async function jsonOrThrow(r) {
  let data = null
  try { data = await r.json() } catch {}
  if (!r.ok) {
    const d = data && data.detail
    throw new Error((typeof d === 'string' && d) || `请求失败（${r.status}）`)
  }
  return data
}

/** 创建分享，返回 { token, url }。payload = {title,question,intent,columns,rows,chart,insight,citations,sql} */
export async function createShare(payload) {
  if (IS_MOCK) {
    const token = 'd' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6)
    try { localStorage.setItem(key(token), JSON.stringify({ ...payload, created_at: Date.now() })) } catch {}
    return { token, url: shareUrl(token) }
  }
  const r = await fetch(ENDPOINTS.share, {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({
      title: payload.title || payload.question || '',
      question: payload.question || '', intent: payload.intent || 'sql',
      payload: JSON.stringify(payload),
    }),
  })
  const data = await jsonOrThrow(r)
  return { token: data.token, url: shareUrl(data.token) }
}

/** 公开读取（免鉴权）。返回快照对象或 null。 */
export async function getPublicShare(token) {
  if (IS_MOCK) {
    try { const raw = localStorage.getItem(key(token)); return raw ? JSON.parse(raw) : null } catch { return null }
  }
  const r = await fetch(ENDPOINTS.publicShare(token))
  if (!r.ok) return null
  const data = await r.json().catch(() => null)
  if (!data) return null
  // 后端把快照存在 payload(JSON 字符串) 里
  const p = typeof data.payload === 'string' ? safeParse(data.payload) : (data.payload || data)
  return { ...p, title: data.title || p.title, question: data.question || p.question, intent: data.intent || p.intent, created_at: data.created_at }
}
function safeParse(s) { try { return JSON.parse(s) } catch { return {} } }
