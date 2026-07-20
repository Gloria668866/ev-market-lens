// 全局快捷键系统：Cmd+K 新建对话、Cmd+Enter 发送、Cmd+/ 快捷键帮助、Esc 关闭模态
import { onMounted, onBeforeUnmount } from 'vue'

export function useHotkeys(handlers) {
  function onKeydown(e) {
    const mod = e.metaKey || e.ctrlKey
    const key = e.key.toLowerCase()
    if (mod && key === 'k') { e.preventDefault(); handlers.newChat?.() }
    if (mod && key === 'enter') { e.preventDefault(); handlers.send?.() }
    if (mod && key === '/') { e.preventDefault(); handlers.help?.() }
    if (key === 'escape') { e.preventDefault(); handlers.esc?.() }
  }
  onMounted(() => window.addEventListener('keydown', onKeydown))
  onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
}
