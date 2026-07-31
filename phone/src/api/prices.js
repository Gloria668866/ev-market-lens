// 车型报价：mock（取自真实导出 prices.json）↔ live（/api/prices）。
import { API, IS_MOCK, authHeaders } from './config.js'
import data from './prices.json'

export async function listPrices({ q = '', sort = 'price', order = 'desc', limit = 60 } = {}) {
  if (IS_MOCK) {
    let items = data.items.slice()
    if (q) { const k = q.toLowerCase(); items = items.filter((x) => `${x.brand}${x.series}`.toLowerCase().includes(k)) }
    const key = sort === 'brand' ? 'brand' : 'max'
    items.sort((a, b) => { const r = key === 'max' ? (a.max || 0) - (b.max || 0) : String(a[key]).localeCompare(String(b[key]), 'zh'); return order === 'asc' ? r : -r })
    return { count: items.length, items: items.slice(0, limit) }
  }
  const qs = new URLSearchParams({ q, sort, order, limit })
  const r = await fetch(`${API.prices}?${qs}`, { headers: authHeaders() })
  if (!r.ok) throw new Error('加载报价失败')
  return r.json()
}
