<script setup>
// 数据分析脑：图表卡（可切图型 + 导出 PNG/CSV）+「结论与归因」+「查看 SQL」折叠（展示 Text2SQL）。
// 图型切换在前端用同一份 columns/rows 直接重绘，不重新请求后端。
import { ref, computed, watch } from 'vue'
import ChartCard from './ChartCard.vue'
import { normalizeChartSpec, buildOptionByType, TYPE_LABEL } from '@/utils/chart.js'
import { toCSV, downloadFile, downloadDataURL, copyText, exportName } from '@/utils/export.js'

const props = defineProps({
  msg: { type: Object, required: true },
  streaming: { type: Boolean, default: false },
})

const chartRef = ref(null)
const copied = ref(false)

function exportCSV() {
  downloadFile(exportName('车市镜数据', 'csv'), toCSV(props.msg.columns, props.msg.rows), 'text/csv;charset=utf-8')
}
function exportPNG() {
  const url = chartRef.value?.getDataURL()
  if (url) downloadDataURL(exportName('车市镜图表', 'png'), url)
}
async function copyInsight() {
  if (await copyText(props.msg.insight || '')) { copied.value = true; setTimeout(() => { copied.value = false }, 1500) }
}

const hasData = computed(() => props.msg.rows?.length > 0 && props.msg.columns?.length > 0)
const spec = computed(() => hasData.value ? normalizeChartSpec(props.msg.chartPayload, props.msg.columns, props.msg.rows) : null)
const types = computed(() => (spec.value?.switchable || []).map((k) => ({ key: k, label: TYPE_LABEL[k] || k })))

const type = ref(null)
watch(spec, (s) => { if (s && (type.value == null || !s.switchable.includes(type.value))) type.value = s.defaultType }, { immediate: true })

const option = computed(() => spec.value && type.value ? buildOptionByType(type.value, props.msg.columns, props.msg.rows, spec.value) : null)
</script>

<template>
  <div class="result">
    <div v-if="option" class="chart-card">
      <div class="card-head">
        <span class="lbl"><span class="d"></span>数据图表</span>
        <div v-if="types.length > 1" class="switch" role="group" aria-label="切换图型">
          <button v-for="t in types" :key="t.key" :class="{ on: type === t.key }" @click="type = t.key">{{ t.label }}</button>
        </div>
        <div class="tools">
          <button class="tool" title="下载图表 PNG" @click="exportPNG">
            <svg viewBox="0 0 16 16" width="13" height="13" fill="none"><path d="M8 2v8m0 0L5 7m3 3l3-3M3 14h10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>图
          </button>
          <button class="tool" title="导出数据 CSV" @click="exportCSV">
            <svg viewBox="0 0 16 16" width="13" height="13" fill="none"><rect x="2.5" y="2.5" width="11" height="11" rx="1.5" stroke="currentColor" stroke-width="1.3"/><path d="M2.5 6.5h11M6.5 2.5v11" stroke="currentColor" stroke-width="1.3"/></svg>CSV
          </button>
        </div>
      </div>
      <ChartCard ref="chartRef" :option="option" />
    </div>

    <div v-if="msg.insight || streaming" class="insight">
      <div class="insight-head">
        <span>结论与归因</span>
        <button class="copy" :class="{ ok: copied }" :title="copied ? '已复制' : '复制结论'" @click="copyInsight">{{ copied ? '✓ 已复制' : '复制' }}</button>
      </div>
      <div class="insight-body"><span class="text">{{ msg.insight }}</span><span v-if="streaming" class="cursor"></span></div>
    </div>

    <details v-if="msg.sql && !streaming" class="disc">
      <summary>
        <span class="tw">▸</span> 查看 SQL <span class="tag">TEXT2SQL · 自校验通过</span>
      </summary>
      <pre>{{ msg.sql }}</pre>
    </details>
  </div>
</template>

<style scoped>
.result { display: flex; flex-direction: column; gap: 14px; }

.chart-card { border: 1px solid var(--line); border-radius: var(--r-lg); padding: 14px 16px 12px; background: var(--bg); box-shadow: var(--sh-sm); position: relative; overflow: hidden; }
.card-head { display: flex; align-items: center; gap: 12px; margin: 2px 0 8px; flex-wrap: wrap; }
.lbl { display: inline-flex; align-items: center; gap: 7px; font-family: var(--font-mono); font-size: 10.5px; font-weight: 600; letter-spacing: .1em; color: var(--ink-3); text-transform: uppercase; }
.lbl .d { width: 6px; height: 6px; border-radius: 50%; background: var(--info); }

.switch { margin-left: auto; display: inline-flex; background: var(--bg-sunken); border: 1px solid var(--line); border-radius: 9px; padding: 3px; }
.switch button { font-size: 12px; font-weight: 600; color: var(--ink-3); padding: 4px 11px; border-radius: 6px; transition: color .12s, background .12s; white-space: nowrap; }
.switch button:hover { color: var(--ink); }
.switch button.on { background: var(--bg); color: var(--ink); box-shadow: var(--sh-sm); }

.tools { display: inline-flex; gap: 4px; margin-left: auto; }
.switch ~ .tools { margin-left: 0; }
.tool { display: inline-flex; align-items: center; gap: 5px; font-size: 11.5px; font-weight: 600; color: var(--ink-3); border-radius: 8px; padding: 6px 9px; transition: color .12s, background .12s; }
.tool:hover { color: var(--ink); background: var(--bg-subtle); }

.insight { border: 1px solid var(--line); border-left: 3px solid var(--info); background: linear-gradient(180deg, var(--info-wash), var(--bg) 80%); border-radius: var(--r-md); padding: 14px 16px; }
.insight-head { display: flex; align-items: center; font-family: var(--font-mono); font-size: 10.5px; font-weight: 600; color: var(--info); letter-spacing: .1em; margin-bottom: 8px; text-transform: uppercase; }
.insight-head .copy { margin-left: auto; font-family: var(--font-body); font-size: 11px; font-weight: 600; color: var(--ink-3); border: 1px solid var(--line); border-radius: 7px; padding: 2px 10px; letter-spacing: 0; text-transform: none; transition: color .12s, border-color .12s; }
.insight-head .copy:hover { color: var(--info); border-color: var(--info); }
.insight-head .copy.ok { color: var(--up); border-color: var(--up); }
.insight-body { font-size: 14.5px; color: var(--ink); line-height: 1.8; white-space: pre-wrap; }
.cursor { display: inline-block; width: 7px; height: 15px; background: var(--info); margin-left: 2px; vertical-align: -2px; animation: blink 1s step-start infinite; }

.disc { border: 1px solid var(--line); border-radius: var(--r-md); overflow: hidden; }
.disc summary { list-style: none; cursor: pointer; display: flex; align-items: center; gap: 8px; padding: 10px 14px; font-family: var(--font-mono); font-size: 11.5px; font-weight: 600; color: var(--ink-2); background: var(--bg-subtle); }
.disc summary::-webkit-details-marker { display: none; }
.disc summary .tw { transition: transform .15s; color: var(--ink-3); }
.disc[open] summary .tw { transform: rotate(90deg); }
.disc summary .tag { margin-left: auto; font-size: 10px; color: var(--ink-3); background: var(--bg); border: 1px solid var(--line); padding: 1px 8px; border-radius: 6px; letter-spacing: .04em; }
.disc pre { margin: 0; padding: 14px 16px; font-family: var(--font-mono); font-size: 12px; line-height: 1.7; color: var(--ink-2); background: var(--bg); overflow-x: auto; white-space: pre-wrap; border-top: 1px solid var(--line); }

@media (max-width: 560px) { .switch button { padding: 5px 9px; } }
</style>
