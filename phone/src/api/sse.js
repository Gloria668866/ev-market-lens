// SSE 流式请求
import { API, authHeaders } from './config.js'

export async function postSSE(url, body, handlers, signal) {
  const { onEvent, onError, onClose } = handlers
  let resp
  try {
    resp = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream', ...authHeaders() },
      body: JSON.stringify(body), signal,
    })
  } catch (e) {
    if (e.name === 'AbortError') return
    onError?.({ message: `网络错误: ${e.message}` })
    return
  }
  if (!resp.ok || !resp.body) { onError?.({ message: `服务器错误 ${resp.status}` }); return }

  const reader = resp.body.getReader(); const decoder = new TextDecoder(); let buffer = ''
  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let sep
      while ((sep = buffer.search(/\r?\n\r?\n/)) !== -1) {
        const chunk = buffer.slice(0, sep)
        buffer = buffer.slice(sep + (buffer[sep] === '\r' ? 4 : 2))
        parseChunk(chunk, onEvent)
      }
    }
    if (buffer.trim()) parseChunk(buffer, onEvent)
  } catch (e) { if (e.name !== 'AbortError') onError?.({ message: e.message }) }
  finally { onClose?.() }
}

function parseChunk(chunk, onEvent) {
  let event = 'message'; const dataLines = []
  for (const line of chunk.split(/\r?\n/)) {
    if (!line || line.startsWith(':')) continue
    const idx = line.indexOf(':'); const field = idx === -1 ? line : line.slice(0, idx)
    let val = idx === -1 ? '' : line.slice(idx + 1); if (val.startsWith(' ')) val = val.slice(1)
    if (field === 'event') event = val
    else if (field === 'data') dataLines.push(val)
  }
  if (!dataLines.length) return
  const raw = dataLines.join('\n')
  try {
    const data = JSON.parse(raw)
    onEvent?.({ type: event, ...data })
  } catch { onEvent?.({ type: event, raw }) }
}
