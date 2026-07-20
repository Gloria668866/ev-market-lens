// 统一入口：按 .env 的数据源开关，把请求路由到 mock 或真后端。
// 组件/composable 只调这里，切换 mock↔live 不动任何 UI 代码。
import { ENDPOINTS, IS_MOCK } from './config.js'
// P2 FIX: 使用 postSSEWithRetry 而非 postSSE，网络抖动时自动重连（最多 2 次）
import { postSSEWithRetry } from './sse.js'
import { mockSSE } from './mock.js'
import { authHeaders } from './auth.js'

/**
 * 流式提问。自动断线重连（live 模式，最多 2 次，1s/2s 退避）。
 * @param {string} question
 * @param {{onEvent, onError, onClose}} handlers  收规范事件
 * @returns {{ abort: () => void }}
 */
export function ask(question, handlers, conversationId) {
  const controller = new AbortController()
  const body = { question, ...(conversationId != null ? { conversation_id: conversationId } : {}) }
  if (IS_MOCK) {
    mockSSE(body, handlers, controller.signal)
  } else {
    postSSEWithRetry(ENDPOINTS.ask, body, handlers, controller.signal, 2)
  }
  return { abort: () => controller.abort() }
}

/** 一次性提问（调试/降级用，对应 /api/ask_sync）。mock 模式下不可用。 */
export async function askSync(question) {
  const resp = await fetch(ENDPOINTS.askSync, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ question }),
  })
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  return resp.json()
}
