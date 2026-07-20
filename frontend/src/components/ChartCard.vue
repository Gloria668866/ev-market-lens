<script setup>
// ECharts 渲染器：按需引入核心 + 用到的图表/组件，体积可控。
import { ref, onMounted, onBeforeUnmount, watch, shallowRef } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart, ScatterChart } from 'echarts/charts'
import {
  GridComponent, TooltipComponent, LegendComponent, TitleComponent, DataZoomComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([
  BarChart, LineChart, PieChart, ScatterChart,
  GridComponent, TooltipComponent, LegendComponent, TitleComponent, DataZoomComponent,
  CanvasRenderer,
])

const props = defineProps({ option: { type: Object, required: true } })
const el = ref(null)
const chart = shallowRef(null)
let ro = null

function render() {
  if (!el.value) return
  if (!chart.value) chart.value = echarts.init(el.value, null, { renderer: 'canvas' })
  chart.value.setOption(props.option, true)
}

onMounted(() => {
  render()
  ro = new ResizeObserver(() => chart.value?.resize())
  ro.observe(el.value)
})
onBeforeUnmount(() => {
  ro?.disconnect()
  chart.value?.dispose()
})
watch(() => props.option, render, { deep: true })

// 供父组件「下载图表 PNG」：导出当前画布（2x 像素密度，白底）
function getDataURL() {
  return chart.value?.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: '#fff' }) || null
}
defineExpose({ getDataURL })
</script>

<template>
  <div ref="el" class="chart"></div>
</template>

<style scoped>
.chart { width: 100%; height: 320px; }
</style>
