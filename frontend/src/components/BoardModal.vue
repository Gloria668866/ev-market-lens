<script setup>
// 收藏看板：把任意结果卡「收藏」下来的洞察快照集中展示。
// 重提（回到对话框再问一次）/ 删除。空态引导用户去收藏。
import { computed } from 'vue'
import { useBoard } from '@/composables/useBoard.js'

const emit = defineEmits(['close', 'ask'])
const { items, loading, remove } = useBoard()

const INTENT = { sql: ['数据分析', 'sql'], rag: ['知识问答', 'rag'], hybrid: ['综合分析', 'mix'], clarify: ['需澄清', 'mix'] }

function excerpt(it) {
  const t = it.payload?.insight || ''
  return t.length > 140 ? t.slice(0, 140) + '…' : t
}
function fmtDate(t) {
  const d = typeof t === 'number' ? new Date(t) : new Date(Date.parse(t))
  if (isNaN(d.getTime())) return ''
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}
const count = computed(() => items.length)
</script>

<template>
  <div class="mask" @click.self="emit('close')">
    <div class="modal">
      <header>
        <div>
          <h3><span class="star">★</span> 收藏看板</h3>
          <p class="sub">把有价值的洞察存档，随时回看或重新提问 · 共 {{ count }} 条</p>
        </div>
        <button class="x" @click="emit('close')">✕</button>
      </header>

      <div class="body">
        <p v-if="loading" class="hint">加载中…</p>
        <div v-else-if="!items.length" class="empty">
          <div class="empty-ic">★</div>
          <strong>看板还是空的</strong>
          <span>在任意分析结果卡上点「收藏」，洞察就会出现在这里。</span>
        </div>

        <div v-else class="grid">
          <article v-for="it in items" :key="it.id" class="ins">
            <div class="ins-h">
              <span class="badge" :class="(INTENT[it.intent] || INTENT.sql)[1]">{{ (INTENT[it.intent] || INTENT.sql)[0] }}</span>
              <span class="date mono">{{ fmtDate(it.createdAt) }}</span>
              <button class="del" title="移出看板" @click="remove(it.id)">✕</button>
            </div>
            <div class="q">{{ it.title || it.question }}</div>
            <p v-if="excerpt(it)" class="ex">{{ excerpt(it) }}</p>
            <div v-if="it.payload?.rows?.length" class="meta mono">{{ it.payload.rows.length }} 行 · {{ (it.payload.columns || []).length }} 列</div>
            <div v-if="it.payload?.citations?.length" class="meta mono">{{ it.payload.citations.length }} 条引用</div>
            <button class="reask" @click="emit('ask', it.question)">重新提问 →</button>
          </article>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.mask { position: fixed; inset: 0; background: rgba(17,17,17,.32); backdrop-filter: blur(4px); display: flex; align-items: center; justify-content: center; z-index: 50; animation: fadeIn .18s ease; padding: 20px; }
.modal { width: min(760px, 96vw); max-height: 84vh; background: var(--bg); border: 1px solid var(--line); border-radius: var(--r-lg); box-shadow: var(--sh-lg); display: flex; flex-direction: column; overflow: hidden; animation: fadeUp .22s ease; }
header { display: flex; align-items: flex-start; padding: 22px 24px 16px; border-bottom: 1px solid var(--line); }
h3 { margin: 0; font-family: var(--font-display); font-size: 19px; font-weight: 700; color: var(--ink); }
h3 .star { color: var(--accent); }
.sub { margin: 5px 0 0; font-size: 12.5px; color: var(--ink-3); }
.x { margin-left: auto; width: 30px; height: 30px; border-radius: 8px; color: var(--ink-3); font-size: 15px; }
.x:hover { background: var(--bg-subtle); color: var(--ink); }

.body { padding: 18px 24px 24px; overflow-y: auto; }
.hint { font-size: 13px; color: var(--ink-3); text-align: center; padding: 30px 0; }
.empty { display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 48px 0; text-align: center; }
.empty-ic { width: 56px; height: 56px; border-radius: 16px; background: var(--accent-wash); color: var(--accent); display: flex; align-items: center; justify-content: center; font-size: 26px; }
.empty strong { font-size: 15px; color: var(--ink); margin-top: 6px; }
.empty span { font-size: 13px; color: var(--ink-3); max-width: 320px; line-height: 1.6; }

.grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px; }
.ins { border: 1px solid var(--line); border-radius: var(--r-md); padding: 14px 16px; background: var(--bg); display: flex; flex-direction: column; gap: 8px; transition: border-color .12s, box-shadow .12s; }
.ins:hover { border-color: var(--line-strong); box-shadow: var(--sh-sm); }
.ins-h { display: flex; align-items: center; gap: 8px; }
.badge { font-size: 11px; font-weight: 700; padding: 2px 9px; border-radius: 999px; }
.badge.sql { background: var(--info-wash); color: var(--info); }
.badge.rag { background: var(--up-wash); color: var(--up); }
.badge.mix { background: var(--accent-wash); color: var(--accent); }
.date { margin-left: 4px; font-size: 10.5px; color: var(--ink-3); }
.del { margin-left: auto; width: 22px; height: 22px; border-radius: 6px; color: var(--ink-3); font-size: 12px; }
.del:hover { background: var(--accent-wash); color: var(--accent); }
.q { font-size: 14px; font-weight: 700; color: var(--ink); line-height: 1.45; }
.ex { margin: 0; font-size: 12.5px; color: var(--ink-2); line-height: 1.7; }
.meta { font-size: 10.5px; color: var(--ink-3); }
.reask { align-self: flex-start; margin-top: 2px; font-size: 12.5px; font-weight: 600; color: var(--accent); }
.reask:hover { text-decoration: underline; }

@media (max-width: 640px) { .grid { grid-template-columns: 1fr; } }
</style>
