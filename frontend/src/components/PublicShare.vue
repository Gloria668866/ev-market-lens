<script setup>
// 公开分享页（/s/{token}，免登录只读）：每条分享都是一个带品牌的落地页 = 天然营销位。
import { ref, reactive, onMounted, computed } from 'vue'
import LogoMark from './LogoMark.vue'
import DataResultCard from './DataResultCard.vue'
import KnowledgeAnswer from './KnowledgeAnswer.vue'
import ThinkingTrace from './ThinkingTrace.vue'
import { getPublicShare } from '@/api/share.js'

const loading = ref(true)
const notFound = ref(false)
const msg = reactive({ intent: 'sql', columns: [], rows: [], chartPayload: null, insight: '', citations: [], sql: '', question: '' })

const token = computed(() => decodeURIComponent((location.pathname.match(/\/s\/([^/?#]+)/) || [])[1] || ''))
const isKnowledge = computed(() => msg.intent === 'rag')
const stages = computed(() => isKnowledge.value
  ? [{ key: 'i', label: '意图识别', status: 'done' }, { key: 'r', label: '检索知识库', status: 'done' }, { key: 'p', label: '生成答案', status: 'done' }]
  : [{ key: 'i', label: '意图识别', status: 'done' }, { key: 'r', label: '查询数据库', status: 'done' }, { key: 'p', label: '生成图表与结论', status: 'done' }])

onMounted(async () => {
  const data = await getPublicShare(token.value).catch(() => null)
  if (!data) { notFound.value = true; loading.value = false; return }
  msg.intent = data.intent || 'sql'
  msg.columns = data.columns || []; msg.rows = data.rows || []
  msg.chartPayload = data.chart || data.chartPayload || null
  msg.insight = data.insight || ''; msg.citations = data.citations || []
  msg.sql = data.sql || ''; msg.question = data.question || data.title || ''
  loading.value = false
})
</script>

<template>
  <div class="pub">
    <header class="pub-top">
      <a class="brand" href="/"><LogoMark :size="24" tone="brand" /><span>车<b>市</b>镜</span></a>
      <a class="cta" href="/">自己来问一个 →</a>
    </header>

    <main class="pub-main">
      <p v-if="loading" class="state">加载分享内容…</p>
      <div v-else-if="notFound" class="state nf">
        <div class="nf-ic">∅</div>
        <strong>分享不存在或已过期</strong>
        <span>链接可能已失效。</span>
        <a class="go" href="/">前往车市镜 →</a>
      </div>

      <template v-else>
        <div class="overline">新能源车市情报 · 双脑 AGENT · 分享</div>
        <h1 class="q">{{ msg.question || '分析结果' }}</h1>

        <div class="card">
          <ThinkingTrace :stages="stages" :intent="msg.intent" :confidence="null" />
          <div class="sp"></div>
          <KnowledgeAnswer v-if="isKnowledge" :msg="msg" :streaming="false" />
          <DataResultCard v-else :msg="msg" :streaming="false" />
        </div>

        <div class="foot">
          <p>由 <b>车市镜 / EV-MarketLens</b> 生成 —— 用大白话问，Agent 自动查库出图、读研报给引用。</p>
          <a class="go" href="/">免费体验 →</a>
        </div>
      </template>
    </main>
  </div>
</template>

<style scoped>
.pub { min-height: 100%; background: var(--bg-subtle); }
.pub-top { display: flex; align-items: center; height: 58px; padding: 0 24px; background: var(--bg); border-bottom: 1px solid var(--line); }
.brand { display: flex; align-items: center; gap: 9px; font-family: var(--font-display); font-size: 17px; font-weight: 800; color: var(--ink); }
.brand b { color: var(--accent); }
.cta { margin-left: auto; font-size: 13px; font-weight: 700; color: var(--accent); }
.pub-main { max-width: 800px; margin: 0 auto; padding: 40px 24px 64px; }
.state { text-align: center; color: var(--ink-3); padding: 60px 0; }
.nf { display: flex; flex-direction: column; align-items: center; gap: 8px; }
.nf-ic { width: 56px; height: 56px; border-radius: 16px; background: var(--bg-sunken); color: var(--ink-3); display: flex; align-items: center; justify-content: center; font-size: 26px; }
.nf strong { font-size: 16px; color: var(--ink); }
.nf span { font-size: 13px; color: var(--ink-3); }
.overline { font-family: var(--font-mono); font-size: 11px; font-weight: 600; letter-spacing: .16em; color: var(--accent); text-transform: uppercase; }
.q { font-family: var(--font-display); font-size: clamp(26px, 4.6vw, 38px); font-weight: 800; letter-spacing: -.02em; margin: 12px 0 22px; color: var(--ink); }
.card { background: var(--bg); border: 1px solid var(--line); border-radius: var(--r-lg); box-shadow: var(--sh-sm); padding: 18px; }
.card .sp { height: 14px; }
.foot { margin-top: 28px; padding-top: 22px; border-top: 1px solid var(--line); display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
.foot p { margin: 0; font-size: 13px; color: var(--ink-2); flex: 1; min-width: 240px; }
.foot b { color: var(--ink); }
.go { display: inline-block; font-size: 13.5px; font-weight: 700; color: #fff; background: var(--accent); padding: 9px 18px; border-radius: var(--r-md); }
.go:hover { background: var(--accent-press); text-decoration: none; }
</style>
