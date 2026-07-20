// 车型报价 API：mock（取自真实导出 prices.json，本地过滤/排序）↔ live（/api/prices）。
import { ENDPOINTS, IS_MOCK } from './config.js'
import { authHeaders } from './auth.js'
import pricesData from './prices.json'

function localQuery({ q = '', brand = '', sort = 'price', order = 'desc', limit = 80 }) {
  let items = pricesData.items.slice()
  if (q) { const k = q.toLowerCase(); items = items.filter((x) => `${x.brand}${x.series}`.toLowerCase().includes(k)) }
  if (brand) items = items.filter((x) => x.brand === brand)
  const key = sort === 'brand' ? 'brand' : sort === 'series' ? 'series' : 'max'
  items.sort((a, b) => {
    const r = key === 'max' ? (a.max || 0) - (b.max || 0) : String(a[key]).localeCompare(String(b[key]), 'zh')
    return order === 'asc' ? r : -r
  })
  return { count: items.length, items: items.slice(0, limit) }
}

export async function listPrices(params = {}) {
  if (IS_MOCK) return localQuery({ q: '', brand: '', sort: 'price', order: 'desc', limit: 80, ...params })
  const qs = new URLSearchParams({ q: '', brand: '', sort: 'price', order: 'desc', limit: 80, ...params })
  const r = await fetch(`${ENDPOINTS.prices}?${qs}`, { headers: { ...authHeaders() } })
  if (!r.ok) throw new Error('加载报价失败')
  return r.json()
}

export async function priceBrands() {
  if (IS_MOCK) return [...new Set(pricesData.items.map((x) => x.brand))].sort((a, b) => a.localeCompare(b, 'zh'))
  const r = await fetch(ENDPOINTS.priceBrands, { headers: { ...authHeaders() } })
  if (!r.ok) return []
  return (await r.json()).brands || []
}
