// 原生 SSE 解析（不依赖第三方 SSE 库）
// ------------------------------------------------------------------
// 为什么不用 window.EventSource？—— 原生 EventSource 只支持 GET，
// 而 /api/ask 是 POST（带 JSON body）。所以用 fetch + ReadableStream 自己解析
// text/event-stream，这是 POST-SSE 的标准做法，仍属「原生」（无 sse.js 等依赖）。

import { normalizeEvent } from './events.js'
import { authHeaders } from './auth.js'

/**
 * 发起 POST-SSE 请求，逐事件回调。
 * @param {string} url
 * @param {object} body         请求体（{ question }）
 * @param {object} handlers     { onEvent(normalizedEvent), onError(err), onClose() }
 * @param {AbortSignal} signal  用于中断
 */
export async function postSSE(url, body, handlers, signal) {
  const { onEvent, onError, onClose } = handlers
  let resp
  try {
    resp = await fetch(url, {
      method: 'POST',
      // 方案B：SSE 走 fetch，可直接带 Authorization 头（原生 EventSource 做不到）
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream', ...authHeaders() },
      body: JSON.stringify(body),
      signal,
    })
  } catch (e) {
    if (e.name === 'AbortError') return
    onError?.({ code: 'NETWORK', message: `无法连接后端：${e.message}` })
    return
  }

  if (!resp.ok || !resp.body) {
    onError?.({ code: `HTTP_${resp.status}`, message: `后端返回 ${resp.status}` })
    return
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      // 事件以空行（\n\n）分隔；兼容 \r\n
      let sep
      while ((sep = buffer.search(/\r?\n\r?\n/)) !== -1) {
        const chunk = buffer.slice(0, sep)
        buffer = buffer.slice(sep + (buffer[sep] === '\r' ? 4 : 2))
        dispatchChunk(chunk, onEvent)
      }
    }
    if (buffer.trim()) dispatchChunk(buffer, onEvent)
  } catch (e) {
    if (e.name !== 'AbortError') onError?.({ code: 'STREAM', message: e.message })
  } finally {
    onClose?.()
  }
}

// 解析单个 SSE 块：可能有多行 event:/data:，data 可跨行
function dispatchChunk(chunk, onEvent) {
  let event = 'message'
  const dataLines = []
  for (const line of chunk.split(/\r?\n/)) {
    if (!line || line.startsWith(':')) continue // 空行 / 注释（心跳）
    const idx = line.indexOf(':')
    const field = idx === -1 ? line : line.slice(0, idx)
    let val = idx === -1 ? '' : line.slice(idx + 1)
    if (val.startsWith(' ')) val = val.slice(1)
    if (field === 'event') event = val
    else if (field === 'data') dataLines.push(val)
  }
  const raw = dataLines.join('\n')
  const norm = normalizeEvent(event, raw)
  if (norm) onEvent?.(norm)
}

/**
 * POST-SSE with automatic reconnection on network errors.
 * Retries up to maxRetries times with linear backoff.
 * @returns {{ abort: () => void }}
 */
export function postSSEWithRetry(url, body, handlers, signal, maxRetries = 2) {
  let attempts = 0
  let aborted = false
  const controller = new AbortController()

  function tryConnect() {
    if (aborted) return
    const mergedSignal = signal
      ? combineSignals(signal, controller.signal)
      : controller.signal
    postSSE(url, body, {
      onEvent: handlers.onEvent,
      onError: (err) => {
        if (err.code === "NETWORK" && attempts < maxRetries && !aborted) {
          attempts++
          setTimeout(tryConnect, 1000 * attempts)
          return
        }
        handlers.onError?.(err)
      },
      onClose: () => {
        if (!aborted) handlers.onClose?.()
      },
    }, mergedSignal)
  }

  tryConnect()
  return { abort: () => { aborted = true; controller.abort() } }
}

function combineSignals(a, b) {
  if (!a) return b
  if (!b) return a
  const c = new AbortController()
  const onAbort = () => c.abort()
  a.addEventListener("abort", onAbort, { once: true })
  b.addEventListener("abort", onAbort, { once: true })
  return c.signal
}
