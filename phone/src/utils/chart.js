// 图表构造：用查询返回的 columns/rows 在前端构造 ECharts option，支持「同一份数据、切换图型重绘」。
// 图型：bar(柱状) / line(折线) / pie(饼图) / hbar(横向条形)，全部开 legend。
//
// 消费后端 chart「描述符」（app/charts.py 规则引擎）：
//   { default_type, applicable_types:[bar/hbar/line/pie/table], dimension:列名, measures:[列名…], title }
// 同时兼容旧形态 { chart_type, x, y } 与「完整 ECharts option」（取其 series 推断）。
// 主题：干净亮色 SaaS —— 浅底、发丝网格、等宽数字轴、车速红为首的系列色。
// 铁律：图表只渲染查询返回的真实数据，前端只决定「怎么画」，绝不编造数据点。

import * as echarts from 'echarts/core'

// 车速红领衔 + 墨/蓝/绿/琥珀/青/紫，多系列时区分度足够
const PALETTE = ['#dc2626', '#2563eb', '#16a34a', '#d97706', '#0891b2', '#7c3aed', '#db2777', '#475569']
const FONT = 'Geist, "PingFang SC", "Microsoft YaHei", sans-serif'
const MONO = '"Geist Mono", ui-monospace, Consolas, monospace'
const AXIS = '#8a8a93'
const SPLIT = { lineStyle: { color: 'rgba(17,17,17,.06)', type: 'dashed' } }
const AXISLINE = { lineStyle: { color: 'rgba(17,17,17,.14)' } }
const KNOWN = ['bar', 'line', 'pie', 'hbar']

export const TYPE_LABEL = { bar: '柱状图', line: '折线图', pie: '饼图', hbar: '横向条形' }

function fmtNum(v) {
  if (typeof v !== 'number') return v
  if (Math.abs(v) >= 10000) return (v / 10000).toFixed(v % 10000 === 0 ? 0 : 1) + '万'
  return v.toLocaleString('zh-CN')
}

const legendCfg = { type: 'scroll', bottom: 0, icon: 'roundRect', itemWidth: 12, itemHeight: 8, itemGap: 16, textStyle: { color: '#52525b', fontFamily: FONT, fontSize: 12 } }
const baseTooltip = (item = false) => ({
  trigger: item ? 'item' : 'axis',
  axisPointer: { type: 'shadow', shadowStyle: { color: 'rgba(17,17,17,.04)' } },
  backgroundColor: '#ffffff', borderColor: '#ececef', borderWidth: 1,
  textStyle: { color: '#18181b', fontFamily: FONT, fontSize: 12 }, padding: [9, 13],
  extraCssText: 'box-shadow:0 6px 20px -6px rgba(17,17,17,.14); border-radius:10px;',
  valueFormatter: item ? undefined : fmtNum,
})
const baseText = { fontFamily: FONT, color: '#52525b' }
const barGrad = (horizontal) => new echarts.graphic.LinearGradient(
  ...(horizontal ? [0, 0, 1, 0] : [0, 0, 0, 1]),
  [{ offset: 0, color: '#dc2626' }, { offset: 1, color: '#f87171' }],
)

function isFullOption(p) {
  return p && typeof p === 'object' && !p.chart_type && !p.dimension && ('series' in p || 'xAxis' in p || 'yAxis' in p)
}
function isNumericCol(rows, j) {
  return rows.length > 0 && rows.every((r) => { const v = r[j]; return v == null || typeof v === 'number' || (v !== '' && !isNaN(Number(v))) })
}

/**
 * 归一化图表描述符 → { dimension, measures[], defaultType, switchable[], title, chartable }
 * 兼容：新描述符 / 旧 {chart_type,x,y} / 完整 option / 缺失（按数据形状推断）。
 */
export function normalizeChartSpec(payload, columns = [], rows = []) {
  const p = (payload && typeof payload === 'object') ? payload : {}

  let dimension = p.dimension ?? p.x ?? null
  let measures = Array.isArray(p.measures) && p.measures.length ? p.measures.slice()
    : (p.y != null ? [p.y] : null)
  let defaultType = String(p.default_type || p.chart_type || (isFullOption(p) ? (p.series?.[0]?.type || '') : '')).toLowerCase()
  if (defaultType === 'bar' && isFullOption(p) && p.yAxis?.type === 'category') defaultType = 'hbar'
  let applicable = Array.isArray(p.applicable_types) ? p.applicable_types.map((s) => String(s).toLowerCase()) : null
  const title = p.title || ''

  const numIdxs = columns.map((_, j) => j).filter((j) => isNumericCol(rows, j))
  if (!dimension) { const di = columns.findIndex((_, j) => !numIdxs.includes(j)); dimension = columns[di >= 0 ? di : 0] }
  if (!measures || !measures.length) {
    measures = numIdxs.map((j) => columns[j]).filter((c) => c !== dimension)
    if (!measures.length && columns.length > 1) measures = [columns[1]]
  }
  measures = (measures || []).filter((m) => columns.includes(m))

  const chartable = measures.length > 0 && defaultType !== 'table'
  let switchable = applicable ? applicable.filter((t) => KNOWN.includes(t)) : KNOWN.slice()
  if (!switchable.length) switchable = KNOWN.slice()
  if (!KNOWN.includes(defaultType)) defaultType = switchable[0] || 'bar'
  if (!switchable.includes(defaultType)) switchable.unshift(defaultType)

  return { dimension, measures, defaultType, switchable, title, chartable }
}

/** 按指定图型用同一份数据构造 option（含 legend、多系列）。不可画返回 null。 */
export function buildOptionByType(type, columns, rows, spec) {
  if (!spec || !spec.chartable || !rows.length || !columns.length) return null
  const di = columns.indexOf(spec.dimension)
  const dimIdx = di >= 0 ? di : 0
  const cats = rows.map((r) => String(r[dimIdx]))
  const measures = spec.measures
  const multi = measures.length > 1
  const valsOf = (m) => { const mi = columns.indexOf(m); return rows.map((r) => { const v = Number(r[mi]); return isNaN(v) ? 0 : v }) }

  if (type === 'pie') {
    const m0 = measures[0]
    const vals = valsOf(m0)
    return {
      color: PALETTE, textStyle: baseText,
      tooltip: { ...baseTooltip(true), formatter: (p) => `${p.name}<br/><b>${fmtNum(p.value)}</b> (${p.percent}%)` },
      legend: { ...legendCfg },
      series: [{
        type: 'pie', name: m0, radius: ['46%', '70%'], center: ['50%', '44%'],
        itemStyle: { borderColor: '#ffffff', borderWidth: 3, borderRadius: 6 },
        label: { color: '#52525b', fontFamily: FONT },
        labelLine: { lineStyle: { color: '#dcdce0' } },
        data: cats.map((c, i) => ({ name: c, value: vals[i] })),
      }],
    }
  }

  const horizontal = type === 'hbar'
  const catAxis = { type: 'category', data: cats, axisLine: AXISLINE, axisTick: { show: false }, axisLabel: { color: AXIS, fontFamily: FONT, interval: 0, ...(horizontal ? {} : { rotate: cats.length > 6 ? 30 : 0 }) } }
  const valAxis = { type: 'value', axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: AXIS, fontFamily: MONO, formatter: fmtNum }, splitLine: SPLIT }

  if (type === 'line') {
    return {
      color: PALETTE, textStyle: baseText,
      grid: { left: 12, right: 22, top: 28, bottom: 38, containLabel: true },
      tooltip: baseTooltip(), legend: { ...legendCfg },
      xAxis: { ...catAxis, boundaryGap: false },
      yAxis: valAxis,
      series: measures.map((m, i) => ({
        type: 'line', name: m, smooth: 0.4, data: valsOf(m), symbol: 'circle', symbolSize: 6,
        itemStyle: { color: PALETTE[i % PALETTE.length] }, lineStyle: { width: 2.6, color: PALETTE[i % PALETTE.length] },
        ...(multi ? {} : {
          itemStyle: { color: '#dc2626' }, lineStyle: { width: 3, color: '#dc2626' },
          areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: 'rgba(220,38,38,.16)' }, { offset: 1, color: 'rgba(220,38,38,0)' }]) },
        }),
      })),
    }
  }

  // bar / hbar（多系列分组）
  return {
    color: PALETTE, textStyle: baseText,
    grid: { left: 12, right: 22, top: 28, bottom: 38, containLabel: true },
    tooltip: baseTooltip(), legend: { ...legendCfg },
    xAxis: horizontal ? valAxis : catAxis,
    yAxis: horizontal ? { ...catAxis, inverse: true } : valAxis,
    series: measures.map((m, i) => ({
      type: 'bar', name: m, data: valsOf(m), barMaxWidth: multi ? 22 : 34,
      itemStyle: { color: multi ? PALETTE[i % PALETTE.length] : barGrad(horizontal), borderRadius: horizontal ? [0, 5, 5, 0] : [5, 5, 0, 0] },
      ...(multi ? {} : { emphasis: { itemStyle: { color: '#b91c1c' } } }),
    })),
  }
}
