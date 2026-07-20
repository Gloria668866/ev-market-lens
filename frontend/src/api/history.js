// 历史会话 API（live）：列会话 + 取某会话全部消息（含图表/引用）以还原对话。
// 后端契约（app/main.py，需 Bearer、按 user_id 隔离）：
//   GET /api/history            -> {conversations:[{id,title,created_at}]}
//   GET /api/history/{conv_id}  -> {conversation_id, title, messages:[
//          {role,content,intent,chart,columns,rows,citations}]}
// mock 模式不走这里（useChat 用 localStorage 富副本还原），故 mock 分支返回空。
import { ENDPOINTS, IS_MOCK } from './config.js'
import { authHeaders } from './auth.js'

async function jsonOrThrow(r) {
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json()
}

/** 会话列表（时间倒序）。mock 返回 null 表示「不走服务端」。 */
export async function listConversations() {
  if (IS_MOCK) return null
  const r = await fetch(ENDPOINTS.history, { headers: { ...authHeaders() } })
  const data = await jsonOrThrow(r)
  return (data.conversations || []).map((c) => ({
    serverConvId: c.id, title: c.title || '未命名会话', createdAt: c.created_at,
  }))
}

/** 取某会话的全部消息（用于还原含图表/引用的对话）。 */
export async function getConversation(convId) {
  if (IS_MOCK) return null
  const r = await fetch(ENDPOINTS.historyDetail(convId), { headers: { ...authHeaders() } })
  const data = await jsonOrThrow(r)
  return { title: data.title, messages: data.messages || [] }
}

/** 删除某会话（连同消息）。mock 模式不走服务端，返回 true 由本地处理。 */
export async function deleteConversation(convId) {
  if (IS_MOCK) return true
  const r = await fetch(ENDPOINTS.historyDetail(convId), { method: 'DELETE', headers: { ...authHeaders() } })
  return jsonOrThrow(r)
}
