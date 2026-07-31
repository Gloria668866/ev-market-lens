<script setup>
import { ref, nextTick } from 'vue'
import LogoMark from './LogoMark.vue'

const emit = defineEmits(['ask'])
const text = ref('')
const ta = ref(null)

function submit() { const q = text.value.trim(); if (!q) return; emit('ask', q); text.value = ''; nextTick(resize) }
function resize() { const el = ta.value; if (!el) return; el.style.height = 'auto'; el.style.height = Math.min(el.scrollHeight, 160) + 'px' }
function onKey(e) {
  if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); submit(); return }
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); submit() }
}

const COLS = [
  { key: 'sql', cap: '数据脑 · TEXT2SQL', icon: '/images/icon-text2sql.png',
    items: ['2025 年纯电销量 Top10', '比亚迪各车系今年销量', '增程车型月度趋势如何'] },
  { key: 'rag', cap: '知识脑 · RAG', icon: '/images/icon-rag.png',
    items: ['这份研报怎么看后续渗透率？', '2025 补贴政策有哪些变化', '总结上传报告的核心观点'] },
  { key: 'mix', cap: '综合 · 双脑编排', icon: '/images/icon-langgraph.png',
    items: ['小米 SU7 卖得好吗？为什么', '销量数据印证研报预测了吗', '谁在抢比亚迪的份额'] },
]

const KPIS = [
  { k: '覆盖车系', v: '433', d: '102 品牌', cls: 'up' },
  { k: '市场数据', v: '8,402', d: '条销量记录', cls: 'up' },
  { k: '回归集通过率', v: '100%', d: 'Text2SQL · 60 题', cls: 'flat' },
  { k: '意图准确率', v: '100%', d: '110 题固定回归集', cls: 'flat' },
]
</script>

<template>
  <div class="center">

    <!-- Hero 区 -->
    <div class="overline">新能源车市情报 · 双脑 AGENT</div>
    <h1 class="hero-h">把提问，<br/>变成<em>市场洞察</em>。</h1>
    <p class="hero-p">用大白话问。Agent 自动判断意图——查库出图表加归因，或读研报给带引用的答案。</p>

    <!-- 双脑插图 -->
    <div class="brain-banner">
      <img src="/images/dual-brain.png" alt="双脑架构" class="brain-img" />
      <div class="brain-labels">
        <span class="bl left">数据脑 · SQL + 图表</span>
        <span class="bl right">知识脑 · RAG + 引用</span>
      </div>
    </div>

    <!-- 命令输入框 -->
    <div class="cmd">
      <LogoMark :size="20" tone="brand" />
      <textarea ref="ta" v-model="text" rows="1" placeholder="问点什么……例如：2025 年纯电销量 Top10" @input="resize" @keydown="onKey" />
      <button class="go" :disabled="!text.trim()" @click="submit">
        分析
        <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
          <path d="M3 8h9M9 4l4 4-4 4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </button>
    </div>
    <div class="cmd-hint">
      <span><kbd>Enter</kbd> 发送</span>
      <span><kbd>⌘K</kbd> 新对话</span>
    </div>

    <!-- 示例问题（带图标） -->
    <div class="ex-wrap">
      <div v-for="col in COLS" :key="col.key" class="ex-col" :class="col.key">
        <div class="ex-cap">
          <img :src="col.icon" :alt="col.cap" class="ex-icon" />
          {{ col.cap }}
        </div>
        <button v-for="q in col.items" :key="q" class="ex" @click="emit('ask', q)">
          {{ q }}<span class="arr">→</span>
        </button>
      </div>
    </div>

    <!-- 数据概览 KPI -->
    <div class="market">
      <div class="market-h"><span class="lbl">▤ 引擎概览</span></div>
      <div class="kpis">
        <div v-for="kpi in KPIS" :key="kpi.k" class="kpi">
          <div class="k">{{ kpi.k }}</div>
          <div class="v">{{ kpi.v }}</div>
          <div class="d" :class="kpi.cls">{{ kpi.d }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.center { max-width: var(--maxw-center); margin: 0 auto; padding: 56px 28px 56px; animation: fadeUp .4s ease both; }

.overline { display: inline-flex; align-items: center; gap: 9px; font-family: var(--font-mono); font-size: 11.5px; font-weight: 600; letter-spacing: .18em; color: var(--accent); text-transform: uppercase; }
.overline::before { content: ""; width: 26px; height: 1px; background: var(--accent); }
.hero-h { font-family: var(--font-display); font-size: clamp(32px, 5.5vw, 50px); line-height: 1.05; font-weight: 800; letter-spacing: -.02em; margin: 16px 0 0; color: var(--ink); }
.hero-h em { font-style: normal; color: var(--accent); }
.hero-p { font-size: 15.5px; color: var(--ink-2); margin: 14px 0 0; max-width: 540px; line-height: 1.65; }

/* 双脑插图横幅 */
.brain-banner { position: relative; margin: 32px 0 0; border-radius: var(--r-lg); overflow: hidden; border: 1px solid var(--line); background: var(--bg); }
.brain-img { display: block; width: 100%; max-height: 220px; object-fit: contain; padding: 20px; box-sizing: border-box; }
.brain-labels { position: absolute; bottom: 0; left: 0; right: 0; display: flex; justify-content: space-between; padding: 10px 24px; background: linear-gradient(transparent, rgba(255,255,255,.9)); }
.bl { font-family: var(--font-mono); font-size: 11px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; padding: 3px 10px; border-radius: 20px; }
.bl.left { background: var(--info-wash); color: var(--info-strong); }
.bl.right { background: var(--up-wash); color: var(--up); }

/* 命令输入框 */
.cmd { margin: 28px 0 0; display: flex; align-items: center; gap: 12px; background: var(--bg); border: 1px solid var(--line-strong); border-radius: var(--r-lg); box-shadow: var(--sh-md); padding: 10px 10px 10px 16px; transition: border-color .15s, box-shadow .15s; }
.cmd:focus-within { border-color: var(--accent); box-shadow: var(--sh-md), 0 0 0 4px var(--accent-wash); }
.cmd textarea { flex: 1; border: none; outline: none; resize: none; background: transparent; font-size: 15.5px; line-height: 1.5; padding: 7px 0; max-height: 160px; color: var(--ink); }
.cmd textarea::placeholder { color: var(--ink-4); }
.go { flex: none; display: inline-flex; align-items: center; gap: 7px; padding: 11px 18px; font-size: 14px; font-weight: 700; color: #fff; background: var(--accent); border-radius: var(--r-md); transition: background .12s; }
.go:hover:not(:disabled) { background: var(--accent-press); }
.go:disabled { background: var(--bg-sunken-2); color: var(--ink-4); cursor: not-allowed; }
.cmd-hint { display: flex; gap: 16px; margin: 10px 4px 0; font-family: var(--font-mono); font-size: 11px; color: var(--ink-3); }
.cmd-hint kbd { font-family: var(--font-mono); background: var(--bg); border: 1px solid var(--line); border-bottom-width: 2px; border-radius: 5px; padding: 0 5px; margin-right: 5px; color: var(--ink-2); }

/* 示例问题 */
.ex-wrap { margin: 32px 0 0; display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
.ex-cap { display: flex; align-items: center; gap: 8px; font-family: var(--font-mono); font-size: 10.5px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; color: var(--ink-3); margin-bottom: 10px; }
.ex-icon { width: 22px; height: 22px; border-radius: 6px; object-fit: contain; border: 1px solid var(--line); background: var(--bg-sunken); padding: 2px; flex: none; }
.ex { position: relative; display: block; width: 100%; text-align: left; background: var(--bg); border: 1px solid var(--line); border-radius: var(--r-md); padding: 12px 32px 12px 14px; font-size: 13px; color: var(--ink); margin-bottom: 9px; cursor: pointer; transition: border-color .12s, box-shadow .12s, transform .12s; }
.ex:hover { border-color: var(--line-strong); box-shadow: var(--sh-sm); transform: translateY(-1px); }
.ex .arr { position: absolute; right: 13px; top: 50%; transform: translateY(-50%); color: var(--ink-4); transition: color .12s, transform .12s; }
.ex:hover .arr { color: var(--accent); transform: translate(2px, -50%); }

/* KPI 概览 */
.market { margin: 40px 0 0; border-top: 1px solid var(--line); padding-top: 24px; }
.market-h { margin-bottom: 14px; }
.market-h .lbl { font-family: var(--font-mono); font-size: 11px; font-weight: 600; letter-spacing: .1em; color: var(--ink-2); text-transform: uppercase; }
.kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; }
.kpi { background: var(--bg); border: 1px solid var(--line); border-radius: var(--r-md); padding: 15px 16px; }
.kpi .k { font-size: 12px; color: var(--ink-3); }
.kpi .v { font-family: var(--font-mono); font-size: 22px; font-weight: 600; letter-spacing: -.02em; margin-top: 8px; color: var(--ink); }
.kpi .d { display: inline-block; font-family: var(--font-mono); font-size: 11px; font-weight: 600; margin-top: 7px; padding: 2px 8px; border-radius: 6px; }
.kpi .d.up { color: var(--up); background: var(--up-wash); }
.kpi .d.flat { color: var(--ink-3); background: var(--bg-sunken); }

@media (max-width: 820px) {
  .center { padding: 36px 18px 40px; }
  .ex-wrap { grid-template-columns: 1fr; gap: 10px; }
  .kpis { grid-template-columns: repeat(2, 1fr); }
  .brain-img { max-height: 160px; }
}
</style>
