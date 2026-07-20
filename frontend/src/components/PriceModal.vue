<script setup>
// 车型报价：搜索 / 品牌筛选 / 排序，浏览懂车帝实采的指导价。
import { ref, watch, onMounted } from 'vue'
import { listPrices, priceBrands } from '@/api/prices.js'

const emit = defineEmits(['close', 'ask'])
const q = ref(''); const brand = ref(''); const sort = ref('price'); const order = ref('desc')
const items = ref([]); const total = ref(0); const loading = ref(true)
const brands = ref([])

let t = null
async function reload() {
  loading.value = true
  try { const d = await listPrices({ q: q.value.trim(), brand: brand.value, sort: sort.value, order: order.value, limit: 100 }); items.value = d.items; total.value = d.count }
  catch { items.value = [] } finally { loading.value = false }
}
watch([q], () => { clearTimeout(t); t = setTimeout(reload, 220) })
watch([brand, sort, order], reload)
onMounted(async () => { reload(); try { brands.value = await priceBrands() } catch {} })

function setSort(s) { if (sort.value === s) order.value = order.value === 'asc' ? 'desc' : 'asc'; else { sort.value = s; order.value = s === 'price' ? 'desc' : 'asc' } }
function arrow(s) { return sort.value === s ? (order.value === 'asc' ? '↑' : '↓') : '' }
</script>

<template>
  <div class="mask" @click.self="emit('close')">
    <div class="modal">
      <header>
        <div>
          <h3>车型报价</h3>
          <p class="sub">懂车帝实采指导价 · 共 {{ total }} 款车型</p>
        </div>
        <button class="x" @click="emit('close')">✕</button>
      </header>

      <div class="ctrl">
        <div class="search">
          <svg width="13" height="13" viewBox="0 0 16 16" fill="none"><circle cx="7" cy="7" r="5" stroke="currentColor" stroke-width="1.5"/><path d="M11 11l3 3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
          <input v-model="q" placeholder="搜索品牌或车系…" />
        </div>
        <select v-model="brand" class="sel">
          <option value="">全部品牌</option>
          <option v-for="b in brands" :key="b" :value="b">{{ b }}</option>
        </select>
        <div class="sortbar">
          <button :class="{ on: sort === 'price' }" @click="setSort('price')">价格 {{ arrow('price') }}</button>
          <button :class="{ on: sort === 'brand' }" @click="setSort('brand')">品牌 {{ arrow('brand') }}</button>
        </div>
      </div>

      <div class="body">
        <p v-if="loading" class="hint">加载中…</p>
        <p v-else-if="!items.length" class="hint">没有匹配的车型，换个关键词试试。</p>
        <div v-else class="list">
          <div v-for="it in items" :key="it.brand + it.series" class="row" @click="emit('ask', `${it.series}的价格和配置怎么样`)">
            <div class="meta">
              <div class="nm">{{ it.series }}<span class="bd">{{ it.brand }}</span></div>
              <div class="tags">
                <span v-if="it.segment" class="tag">{{ it.segment }}</span>
                <span v-if="it.endurance" class="tag mono">续航 {{ it.endurance }}km</span>
              </div>
            </div>
            <div class="price">
              <span class="pt mono">{{ it.priceText }}</span>
              <span v-if="it.descender > 0" class="down mono">↓{{ it.descender }}万</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.mask { position: fixed; inset: 0; background: rgba(17,17,17,.32); backdrop-filter: blur(4px); display: flex; align-items: center; justify-content: center; z-index: 60; animation: fadeIn .18s ease; padding: 20px; }
.modal { width: min(680px, 96vw); max-height: 86vh; background: var(--bg); border: 1px solid var(--line); border-radius: var(--r-lg); box-shadow: var(--sh-lg); display: flex; flex-direction: column; overflow: hidden; animation: fadeUp .22s ease; }
header { display: flex; align-items: flex-start; padding: 20px 22px 14px; }
h3 { margin: 0; font-family: var(--font-display); font-size: 19px; font-weight: 700; color: var(--ink); }
.sub { margin: 4px 0 0; font-size: 12.5px; color: var(--ink-3); }
.x { margin-left: auto; width: 30px; height: 30px; border-radius: 8px; color: var(--ink-3); font-size: 15px; }
.x:hover { background: var(--bg-subtle); color: var(--ink); }

.ctrl { display: flex; gap: 8px; padding: 0 22px 12px; flex-wrap: wrap; }
.search { position: relative; flex: 1; min-width: 160px; }
.search svg { position: absolute; left: 10px; top: 50%; transform: translateY(-50%); color: var(--ink-3); }
.search input { width: 100%; padding: 8px 10px 8px 30px; font-size: 13px; background: var(--bg-sunken); border: 1px solid transparent; border-radius: var(--r-sm); outline: none; }
.search input:focus { border-color: var(--accent); background: var(--bg); }
.sel { font-size: 13px; padding: 8px 10px; background: var(--bg-sunken); border: 1px solid var(--line); border-radius: var(--r-sm); outline: none; color: var(--ink); max-width: 140px; }
.sortbar { display: inline-flex; background: var(--bg-sunken); border: 1px solid var(--line); border-radius: var(--r-sm); padding: 2px; }
.sortbar button { font-size: 12.5px; font-weight: 600; color: var(--ink-3); padding: 6px 11px; border-radius: 6px; }
.sortbar button.on { background: var(--bg); color: var(--ink); box-shadow: var(--sh-sm); }

.body { padding: 0 22px 20px; overflow-y: auto; }
.hint { text-align: center; color: var(--ink-3); padding: 30px 0; }
.list { display: flex; flex-direction: column; }
.row { display: flex; align-items: center; gap: 12px; padding: 12px 8px; border-bottom: 1px solid var(--line-soft); cursor: pointer; border-radius: 8px; transition: background .12s; }
.row:hover { background: var(--bg-subtle); }
.meta { flex: 1; min-width: 0; }
.nm { font-size: 14.5px; font-weight: 700; color: var(--ink); display: flex; align-items: center; gap: 8px; }
.nm .bd { font-size: 11.5px; font-weight: 500; color: var(--ink-3); }
.tags { display: flex; gap: 5px; margin-top: 4px; flex-wrap: wrap; }
.tag { font-size: 10.5px; color: var(--ink-2); background: var(--bg-sunken); padding: 1px 7px; border-radius: 5px; }
.price { text-align: right; flex: none; }
.pt { font-size: 15px; font-weight: 600; color: var(--accent); }
.down { display: block; font-size: 10.5px; color: var(--up); margin-top: 2px; }

@media (max-width: 560px) { .sel { max-width: none; flex: 1; } }
</style>
