<script setup>
// Agent 思考过程：横向「情报步进器」（意图识别 → 查数据/查文档 → 出结果）+ 意图徽章。
// 产品亮点——让用户看见 Agent 在替你判断与干活，是「这是 Agent 不是看板」的视觉证据。
defineProps({
  stages: { type: Array, default: () => [] },
  intent: { type: String, default: null },
  confidence: { type: Number, default: null },
})
const INTENT_LABEL = { sql: '数据分析', rag: '知识问答', hybrid: '综合分析', clarify: '需要澄清' }
const INTENT_CLS = { sql: 'sql', rag: 'rag', hybrid: 'mix', clarify: 'mix' }
</script>

<template>
  <div class="trace">
    <div class="trace-h">
      <span class="spark">◈</span>
      <span class="t">AGENT 思考过程</span>
      <span v-if="intent" class="intent-badge" :class="INTENT_CLS[intent] || 'sql'">
        {{ INTENT_LABEL[intent] || intent }}
        <em v-if="confidence != null">{{ Math.round(confidence * 100) }}%</em>
      </span>
    </div>
    <ol class="steps">
      <li v-for="(s, i) in stages" :key="s.key" :class="s.status">
        <span class="dot">
          <svg v-if="s.status === 'done'" viewBox="0 0 16 16" width="10" height="10"><path d="M3.5 8.5l3 3 6-7" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>
          <span v-else-if="s.status === 'active'" class="ring"></span>
          <span v-else class="hollow"></span>
        </span>
        <span class="label">{{ s.label }}</span>
        <span v-if="i < stages.length - 1" class="rail" :class="{ done: s.status === 'done' }"></span>
      </li>
    </ol>
  </div>
</template>

<style scoped>
.trace { background: var(--bg); border: 1px solid var(--line); border-radius: var(--r-md); overflow: hidden; }
.trace-h { display: flex; align-items: center; gap: 9px; padding: 11px 15px; border-bottom: 1px solid var(--line); background: var(--bg-subtle); }
.spark { color: var(--accent); font-size: 13px; }
.trace-h .t { font-family: var(--font-mono); font-size: 11px; font-weight: 600; letter-spacing: .1em; color: var(--ink-2); }
.intent-badge { margin-left: auto; display: inline-flex; align-items: center; gap: 7px; font-size: 11.5px; font-weight: 700; padding: 4px 11px; border-radius: 999px; }
.intent-badge em { font-style: normal; font-family: var(--font-mono); opacity: .7; font-weight: 600; font-variant-numeric: tabular-nums; }
.intent-badge.sql { background: var(--info-wash); color: var(--info); }
.intent-badge.rag { background: var(--up-wash); color: var(--up); }
.intent-badge.mix { background: var(--accent-wash); color: var(--accent); }

.steps { list-style: none; margin: 0; padding: 13px 15px; display: flex; align-items: center; gap: 0; }
.steps li { display: flex; align-items: center; gap: 9px; font-size: 12.5px; color: var(--ink-3); position: relative; }
.steps li.done { color: var(--ink-2); }
.steps li.active { color: var(--ink); font-weight: 600; }
.dot { width: 18px; height: 18px; display: inline-flex; align-items: center; justify-content: center; flex: none; }
.steps li.done .dot { color: #fff; }
.steps li.done .dot svg { background: var(--up); border-radius: 50%; padding: 3.4px; width: 18px; height: 18px; }
.hollow { width: 9px; height: 9px; border-radius: 50%; border: 1.5px solid var(--line-strong); background: var(--bg); }
.ring { width: 14px; height: 14px; border-radius: 50%; border: 2px solid var(--accent-wash-2); border-top-color: var(--accent); animation: spin .7s linear infinite; }
.rail { width: clamp(14px, 4vw, 48px); height: 1.5px; background: var(--line-strong); margin: 0 8px; flex: none; }
.rail.done { background: var(--up); }
.label { white-space: nowrap; }

@media (max-width: 560px) {
  .steps { flex-wrap: wrap; gap: 8px 0; }
  .rail { width: 16px; }
}
</style>
