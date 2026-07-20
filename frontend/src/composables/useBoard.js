// 收藏看板状态（模块级单例）：保存/列出/删除洞察快照，按当前用户切换。
// 任意结果卡点「收藏」→ save(snapshot)；看板 BoardModal 读 items。
import { reactive, ref, watch } from 'vue'
import { listInsights, saveInsight, deleteInsight } from '@/api/board.js'
import { useAuth } from '@/composables/useAuth.js'

const items = reactive([])
const loading = ref(false)
let bound = false

function bind() {
  if (bound) return
  bound = true
  const { state: auth } = useAuth()
  watch(() => auth.user?.id, async (id) => {
    items.splice(0, items.length)
    if (!id) return
    loading.value = true
    try { const list = await listInsights(); items.splice(0, items.length, ...list) } catch {}
    loading.value = false
  }, { immediate: true })
}

export function useBoard() {
  bind()

  async function save({ title, question, intent, payload }) {
    const item = await saveInsight({ title, question, intent, payload })
    items.unshift(item)
    return item
  }
  async function remove(id) {
    try { await deleteInsight(id) } catch { return false }
    const i = items.findIndex((x) => x.id === id)
    if (i !== -1) items.splice(i, 1)
    return true
  }

  return { items, loading, save, remove }
}
