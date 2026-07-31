<script setup>
// 移动端图表卡：ECharts 渲染 + 图型切换（柱/折/饼），用同一份 rows 本地重绘。
import { ref, computed, watch, onMounted, onBeforeUnmount, shallowRef } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { normalizeChartSpec, buildOptionByType, TYPE_LABEL } from '@/utils/chart.js'

echarts.use([BarChart, LineChart, PieChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const props = defineProps({ msg: { type: Object, required: true } })

const hasData = computed(() => props.msg.rows?.length > 0 && props.msg.columns?.length > 0)
const spec = computed(() => hasData.value ? normalizeChartSpec(props.msg.chartPayload, props.msg.columns, props.msg.rows) : null)
const types = computed(() => (spec.value?.switchable || []).filter((k) => k !== 'hbar').map((k) => ({ key: k, label: TYPE_LABEL[k] || k })))
const type = ref(null)
watch(spec, (s) => { if (s && (type.value == null || !s.switchable.includes(type.value))) type.value = s.defaultType === 'hbar' ? 'bar' : s.defaultType }, { immediate: true })
const option = computed(() => spec.value && type.value ? buildOptionByType(type.value, props.msg.columns, props.msg.rows, spec.value) : null)

const el = ref(null); const chart = shallowRef(null); let ro = null
function render() { if (!el.value || !option.value) return; if (!chart.value) chart.value = echarts.init(el.value, null, { renderer: 'canvas' }); chart.value.setOption(option.value, true) }
onMounted(() => { render(); ro = new ResizeObserver(() => chart.value?.resize()); ro.observe(el.value) })
onBeforeUnmount(() => { ro?.disconnect(); chart.value?.dispose() })
watch(option, render, { deep: true })
</script>

<template>
  <div v-if="option" class="card">
    <div class="head">
      <span class="lbl mono"><span class="dot"></span>数据图表</span>
      <div v-if="types.length > 1" class="seg">
        <button v-for="t in types" :key="t.key" :class="{ on: type === t.key }" @click="type = t.key">{{ t.label }}</button>
      </div>
    </div>
    <div ref="el" class="chart"></div>
  </div>
</template>

<style scoped>
.card { border: 1px solid var(--line); border-radius: var(--r-md); background: var(--bg); padding: 10px 10px 6px; margin-top: 8px; box-shadow: var(--sh-sm); }
.head { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.lbl { display: inline-flex; align-items: center; gap: 6px; font-size: 9.5px; font-weight: 600; letter-spacing: .08em; color: var(--ink-3); text-transform: uppercase; }
.lbl .dot { width: 5px; height: 5px; border-radius: 50%; background: var(--info); }
.seg { margin-left: auto; display: inline-flex; background: var(--bg-sunken); border: 1px solid var(--line); border-radius: 8px; padding: 2px; }
.seg button { font-size: 11px; font-weight: 600; color: var(--ink-3); padding: 3px 9px; border-radius: 6px; }
.seg button.on { background: var(--bg); color: var(--ink); box-shadow: var(--sh-sm); }
.chart { width: 100%; height: 240px; }
</style>
