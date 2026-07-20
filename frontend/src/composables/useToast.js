// 轻量全局 Toast：操作反馈（复制/收藏/分享/导出/错误）。App 里挂一个 <Toasts/> 渲染。
import { reactive } from 'vue'

let _id = 0
const toasts = reactive([])

export function pushToast(message, type = 'info', timeout = 2200) {
  const id = ++_id
  toasts.push({ id, message, type })
  setTimeout(() => dismiss(id), timeout)
  return id
}
export function dismiss(id) {
  const i = toasts.findIndex((t) => t.id === id)
  if (i !== -1) toasts.splice(i, 1)
}

export function useToast() {
  return {
    toasts,
    dismiss,
    toast: (m) => pushToast(m, 'info'),
    ok: (m) => pushToast(m, 'ok'),
    err: (m) => pushToast(m, 'err'),
  }
}
