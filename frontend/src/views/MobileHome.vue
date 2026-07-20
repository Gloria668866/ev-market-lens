<script setup>
const emit = defineEmits(['ask'])
const HOT = [
  { q: '2025年纯电销量Top10', icon: '🏆' },
  { q: '比亚迪各车系今年销量', icon: '🚗' },
  { q: '小米SU7和Model 3谁卖得多', icon: '⚡' },
  { q: '新能源月度销量趋势', icon: '📈' },
  { q: '增程车型市场占比变化', icon: '🔋' },
  { q: '2025年新上榜车型有哪些', icon: '🆕' },
]
const KPIS = [
  { label: '覆盖车系', value: '409' },
  { label: '覆盖品牌', value: '101' },
  { label: '数据总量', value: '8,072' },
]
</script>

<template>
  <div class="home">
    <!-- 头部 -->
    <div class="header">
      <h1>车市镜</h1>
      <span class="sub">新能源车市情报终端</span>
    </div>

    <!-- 搜索入口 -->
    <div class="search-bar" @click="emit('ask', '')">
      <span class="search-icon">🔍</span>
      <span class="search-placeholder">搜索品牌、车系或提问…</span>
    </div>

    <!-- KPI -->
    <div class="kpi-row">
      <div v-for="k in KPIS" :key="k.label" class="kpi-item">
        <span class="kpi-val">{{ k.value }}</span>
        <span class="kpi-lbl">{{ k.label }}</span>
      </div>
    </div>

    <!-- 热门查询 -->
    <div class="section">
      <div class="section-title">热门查询</div>
      <div class="hot-grid">
        <button v-for="h in HOT" :key="h.q" class="hot-card" @click="emit('ask', h.q)">
          <span class="hot-icon">{{ h.icon }}</span>
          <span class="hot-q">{{ h.q }}</span>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.home { padding: 16px; animation: fadeUp .25s ease both; }
.header { margin-bottom: 16px; }
h1 { font-size: 22px; font-weight: 800; margin: 0; color: #111827; }
.sub { font-size: 11px; color: #dc2626; letter-spacing: .06em; font-weight: 600; }

.search-bar {
  display: flex; align-items: center; gap: 10px; padding: 12px 16px;
  background: #fff; border: 1px solid #e5e7eb; border-radius: 10px;
  margin-bottom: 16px; cursor: pointer;
}
.search-icon { font-size: 16px; }
.search-placeholder { font-size: 14px; color: #9ca3af; }

.kpi-row { display: flex; gap: 0; margin-bottom: 24px; background: #fff; border: 1px solid #e5e7eb; border-radius: 10px; overflow: hidden; }
.kpi-item { flex: 1; text-align: center; padding: 14px 8px; }
.kpi-item + .kpi-item { border-left: 1px solid #f3f4f6; }
.kpi-val { display: block; font-size: 20px; font-weight: 800; color: #111827; font-family: var(--font-mono); }
.kpi-lbl { display: block; font-size: 10px; color: #9ca3af; margin-top: 2px; }

.section-title { font-size: 12px; font-weight: 700; color: #6b7280; letter-spacing: .06em; margin-bottom: 10px; }
.hot-grid { display: flex; flex-wrap: wrap; gap: 8px; }
.hot-card {
  display: flex; align-items: center; gap: 8px; padding: 10px 14px;
  background: #fff; border: 1px solid #e5e7eb; border-radius: 8px;
  font-size: 13px; font-weight: 600; color: #111827; transition: all .1s;
}
.hot-card:active { background: #fef2f2; border-color: #fca5a5; }
.hot-icon { font-size: 16px; }

@keyframes fadeUp { from { opacity: 0; transform: translateY(8px); } }
</style>
