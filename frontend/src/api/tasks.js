import { ENDPOINTS } from './config.js'
import { authHeaders } from './auth.js'

function parseTaskEvent(name, raw) {
  let data = {}
  try { data = JSON.parse(raw || '{}') } catch { data = { message: raw } }
  if (name === 'stage') return { type: 'collection_stage', ...data }
  if (name === 'done') return { type: 'collection_done', ...data }
  if (name === 'error') return { type: 'collection_error', ...data }
  return null
}

function dispatch(chunk, onEvent) {
  let event = 'message'
  const data = []
  for (const line of chunk.split(/\r?\n/)) {
    if (!line || line.startsWith(':')) continue
    const idx = line.indexOf(':')
    const field = idx < 0 ? line : line.slice(0, idx)
    const value = idx < 0 ? '' : line.slice(idx + 1).trimStart()
    if (field === 'event') event = value
    if (field === 'data') data.push(value)
  }
  const parsed = parseTaskEvent(event, data.join('\n'))
  if (parsed) onEvent?.(parsed)
}

export function watchTask(taskId, handlers = {}) {
  const controller = new AbortController()

  ;(async () => {
    try {
      const response = await fetch(ENDPOINTS.taskStream(taskId), {
        headers: { Accept: 'text/event-stream', ...authHeaders() },
        signal: controller.signal,
      })
      if (!response.ok || !response.body) throw new Error(`任务流返回 ${response.status}`)

      const reader = response.body.getReader()
      const decoder = new TextDecoder('utf-8')
      let buffer = ''
      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        let separator
        while ((separator = buffer.search(/\r?\n\r?\n/)) !== -1) {
          const chunk = buffer.slice(0, separator)
          buffer = buffer.slice(separator + (buffer[separator] === '\r' ? 4 : 2))
          dispatch(chunk, handlers.onEvent)
        }
      }
      if (buffer.trim()) dispatch(buffer, handlers.onEvent)
    } catch (error) {
      if (error.name !== 'AbortError') {
        handlers.onEvent?.({ type: 'collection_error', message: error.message })
      }
    }
  })()

  return { abort: () => controller.abort() }
}
