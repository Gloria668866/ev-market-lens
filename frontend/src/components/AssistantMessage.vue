<script setup>
// 助手消息：思考链 → 按意图分流渲染（数据卡 / 知识答案）→ 统一操作栏（复制/收藏/分享/导出报告 + 追问）。
// 收藏/分享/导出对两个脑都通用，故放在消息级而非卡片级。
import { computed, ref } from 'vue'
import ThinkingTrace from './ThinkingTrace.vue'
import DataResultCard from './DataResultCard.vue'
import KnowledgeAnswer from './KnowledgeAnswer.vue'
import LogoMark from './LogoMark.vue'
import { useBoard } from '@/composables/useBoard.js'
import { useToast } from '@/composables/useToast.js'
import { createShare } from '@/api/share.js'
import { exportReport } from '@/utils/report.js'
import { copyText } from '@/utils/export.js'

const props = defineProps({ msg: { type: Object, required: true } })
const emit = defineEmits(['ask'])

const { save } = useBoard()
const { ok, err } = useToast()

const streaming = computed(() => props.msg.status === 'streaming')
const isNoData = computed(() => props.msg.intent !== 'chat' && (
  !!props.msg.collection
  || /未查询到|没有找到|暂无相关数据|0条结果|不在覆盖|不在数据库|未检索到/.test(props.msg.insight || '')
))
const isKnowledge = computed(() => props.msg.intent === 'rag' || props.msg.intent === 'chat' || props.msg.intent === 'clarify' || isNoData.value)
const hasResult = computed(() => props.msg.sql || props.msg.rows.length || props.msg.insight || props.msg.citations.length)

const saved = ref(false)
const sharing = ref(false)
const shareUrl = ref('')

const FALLBACK_QS = ['2025年纯电销量Top10', '理想和小米SU7谁卖得多', '2025年增程销量最高的5款车']
const followups = computed(() => {
  if (props.msg.intent === 'chat' || props.msg.intent === 'clarify')
    return [{ t: '📊 看销量榜单', q: '2025年纯电销量Top10' }, { t: '🔍 比较车型', q: '理想和小米SU7谁卖得多' }]
  if (isNoData.value) return [{ t: '🔍 看热门榜单', q: '2025年纯电销量Top10' }, { t: '🧭 换个品牌', q: '比亚迪2025年销量怎么样' }]
  if (isKnowledge.value) return [{ t: '🔎 看依据', q: '这个结论的依据是什么' }, { t: '🧭 换角度', q: '换个角度再解读一下' }]
  return [{ t: '🔍 追问原因', q: '能进一步分析原因吗？' }, { t: '📈 看趋势', q: '按月拆开看看趋势' }, { t: '📊 对比', q: '对比去年同期的数据' }]
})

function snapshot() {
  return {
    title: props.msg.question || props.msg.insight?.slice(0, 30) || '洞察',
    question: props.msg.question || '',
    intent: props.msg.intent || 'sql',
    columns: props.msg.columns || [], rows: props.msg.rows || [],
    chart: props.msg.chartPayload || null, insight: props.msg.insight || '',
    citations: props.msg.citations || [], sql: props.msg.sql || '',
  }
}

async function copyAll() {
  const m = props.msg; const parts = []
  if (m.insight) parts.push(m.insight)
  if (m.rows.length) { parts.push((m.columns || []).join('\t')); parts.push(...m.rows.map((r) => r.join('\t'))) }
  if (m.sql) parts.push('\nSQL:\n' + m.sql)
  if (await copyText(parts.join('\n'))) ok('已复制全文')
  else err('复制失败')
}

async function onSave() {
  if (saved.value) { ok('已在收藏看板'); return }
  try {
    const s = snapshot()
    await save({ title: s.title, question: s.question, intent: s.intent, payload: s })
    saved.value = true; ok('已加入收藏看板')
  } catch (e) { err('收藏失败：' + (e.message || '')) }
}

async function onShare() {
  try {
    const { url } = await createShare(snapshot())
    shareUrl.value = url; sharing.value = true
    if (await copyText(url)) ok('分享链接已复制')
  } catch (e) { err('生成分享失败：' + (e.message || '')) }
}

function onExport() { exportReport(props.msg); ok('报告已导出（Markdown）') }
async function copyShare() { if (await copyText(shareUrl.value)) ok('已复制') }
</script>

<template>
  <div class="assistant">
    <div class="avatar"><LogoMark :size="20" tone="light" :scan="msg.status === 'thinking' || msg.status === 'streaming'" /></div>
    <div class="bubble">
      <div v-if="msg.status === 'error'" class="err">
        <div class="err-title">没太理解这个问题</div>
        <p class="err-sub">{{ msg.error?.message || '换一种问法试试，或点下面的示例问题：' }}</p>
        <div class="chips">
          <button v-if="msg.question" class="retry" @click="emit('ask', msg.question)">↻ 重试该问题</button>
          <button v-for="q in FALLBACK_QS" :key="q" @click="emit('ask', q)">{{ q }}</button>
        </div>
      </div>

      <template v-else>
        <ThinkingTrace v-if="msg.stages.length" :stages="msg.stages" :intent="msg.intent" :confidence="msg.confidence" />
        <div v-if="!hasResult && msg.status !== 'done'" class="placeholder">
          <span class="s"></span><span class="s"></span><span class="s"></span><span class="s"></span>
        </div>
        <KnowledgeAnswer v-else-if="isKnowledge" :msg="msg" :streaming="streaming" />
        <DataResultCard v-else-if="hasResult" :msg="msg" :streaming="streaming" />

        <div v-if="hasResult && msg.status === 'done'" class="actions">
          <button class="act" @click="copyAll">⧉ 复制</button>
          <button class="act" :class="{ on: saved }" @click="onSave">{{ saved ? '★ 已收藏' : '☆ 收藏' }}</button>
          <button class="act" @click="onShare">⇲ 分享</button>
          <button class="act" @click="onExport">📄 导出报告</button>
          <span class="sp"></span>
          <button v-for="f in followups" :key="f.q" class="act k" @click="emit('ask', f.q)">{{ f.t }}</button>
        </div>

        <div v-if="sharing" class="share-bar">
          <span class="sk mono">公开只读链接</span>
          <input :value="shareUrl" readonly @focus="(e) => e.target.select()" />
          <button @click="copyShare">复制</button>
          <a :href="shareUrl" target="_blank" rel="noopener">打开</a>
          <button class="cl" @click="sharing = false">✕</button>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.assistant { display: flex; gap: 13px; animation: fadeUp .32s ease both; }
.avatar { flex: none; width: 34px; height: 34px; border-radius: 11px; margin-top: 2px; background: linear-gradient(140deg, var(--accent), var(--accent-press)); display: flex; align-items: center; justify-content: center; box-shadow: var(--sh-sm); }
.bubble { flex: 1; min-width: 0; background: var(--bg); border: 1px solid var(--line); border-radius: 5px 16px 16px 16px; padding: 17px 19px; box-shadow: var(--sh-sm); }

.placeholder { display: flex; gap: 6px; padding: 6px 2px; }
.placeholder .s { width: 8px; height: 8px; border-radius: 2px; background: var(--accent); animation: skeletonPulse 1.2s ease-in-out infinite; }
.placeholder .s:nth-child(2) { animation-delay: .15s; }
.placeholder .s:nth-child(3) { animation-delay: .3s; }
.placeholder .s:nth-child(4) { animation-delay: .45s; }

.actions { display: flex; flex-wrap: wrap; align-items: center; gap: 7px; margin-top: 14px; padding-top: 13px; border-top: 1px solid var(--line); }
.actions .sp { flex: 1; min-width: 8px; }
.act { display: inline-flex; align-items: center; gap: 6px; font-size: 12.5px; font-weight: 600; color: var(--ink-2); padding: 6px 12px; border: 1px solid var(--line); border-radius: 999px; background: var(--bg); transition: border-color .12s, color .12s, background .12s; }
.act:hover { border-color: var(--line-strong); color: var(--ink); }
.act.on { color: var(--accent); border-color: var(--accent); background: var(--accent-wash); }
.act.k:hover { border-color: var(--accent); color: var(--accent); background: var(--accent-wash); }

.share-bar { display: flex; align-items: center; gap: 8px; margin-top: 10px; padding: 9px 12px; background: var(--bg-subtle); border: 1px solid var(--line); border-radius: var(--r-md); }
.share-bar .sk { flex: none; font-size: 10px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; color: var(--ink-3); }
.share-bar input { flex: 1; min-width: 0; border: 1px solid var(--line); border-radius: 7px; background: var(--bg); padding: 5px 9px; font-family: var(--font-mono); font-size: 11.5px; color: var(--ink-2); outline: none; }
.share-bar button, .share-bar a { flex: none; font-size: 12px; font-weight: 700; color: var(--accent); padding: 5px 8px; border-radius: 7px; }
.share-bar a:hover, .share-bar button:hover { background: var(--accent-wash); }
.share-bar .cl { color: var(--ink-3); }

.err-title { font-family: var(--font-display); font-size: 17px; font-weight: 700; color: var(--ink); }
.err-sub { font-size: 13px; color: var(--ink-3); margin: 8px 0 13px; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; }
.chips button { font-size: 12.5px; color: var(--ink); background: var(--bg-subtle); border: 1px solid var(--line); border-radius: var(--r-sm); padding: 7px 14px; transition: background .12s, border-color .12s; }
.chips button:hover { background: var(--accent-wash); border-color: var(--accent); color: var(--accent); }
.chips .retry { background: var(--accent); color: #fff; border-color: var(--accent); font-weight: 700; }
.chips .retry:hover { background: var(--accent-press); color: #fff; }
</style>
