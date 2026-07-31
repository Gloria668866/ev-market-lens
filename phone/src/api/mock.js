// 移动端 Mock：无后端也能完整演示。事件形态对齐 useChat（intent/sql_text/rows/chart/insight/citation/done）。
// 知识脑做**离线真检索**：对 kb_corpus.json（主站从真实语料导出）做词法检索，给真实引用。
import corpus from './kb_corpus.json'

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
function tokenize(text) {
  const out = []
  for (const seg of String(text).split(/(\n)/)) {
    if (seg === '\n') { out.push('\n'); continue }
    for (let i = 0; i < seg.length; i += 2) out.push(seg.slice(i, i + 2))
  }
  return out
}

const SCENARIOS = [
  {
    match: (q) => /理想|小米|su7|谁卖|对比|vs/i.test(q),
    sql: "SELECT s.series_name, SUM(f.volume) AS total\nFROM fact_sales_rank f JOIN dim_series s ON s.series_id=f.series_id\nWHERE s.series_name LIKE '%理想%' OR s.series_name LIKE '%小米SU7%'\nGROUP BY s.series_name ORDER BY total DESC LIMIT 10;",
    columns: ['车系', '累计销量'],
    rows: [['小米SU7', 460536], ['理想L6', 387948], ['理想L7', 227192], ['理想L9', 138204], ['理想MEGA', 41260]],
    chart: { default_type: 'bar', applicable_types: ['bar', 'line', 'pie'], dimension: '车系', measures: ['累计销量'], title: '车系销量对比' },
    insight: '小米SU7 以累计 46.05 万辆领跑，超过理想全系单车型最高的 L6（38.79 万）。若按品牌口径合计，理想全系约 79.5 万仍高于小米SU7。',
  },
  {
    match: (q) => /top|前\s*\d+|排名|榜|纯电|插混|增程|销量|趋势/i.test(q),
    sql: "SELECT s.series_name, SUM(f.volume) AS total\nFROM fact_sales_rank f JOIN dim_series s ON s.series_id=f.series_id\nJOIN dim_date d ON d.date_id=f.date_id\nWHERE f.new_energy_type=1 AND d.year=2025\nGROUP BY s.series_name ORDER BY total DESC LIMIT 10;",
    columns: ['车系', '2025累计销量'],
    rows: [['星愿', 465775], ['五菱宏光MINIEV', 435599], ['Model Y', 425337], ['海鸥', 388912], ['Model 3', 261480], ['元UP', 240117], ['海豚', 198640], ['小米SU7', 187233], ['AION S', 165902], ['零跑C10', 152018]],
    chart: { default_type: 'bar', applicable_types: ['bar', 'line', 'pie'], dimension: '车系', measures: ['2025累计销量'], title: '2025 纯电销量 Top10' },
    insight: '2025 年纯电销量 Top10 中，星愿（46.58 万）、五菱宏光MINIEV（43.56 万）、Model Y（42.53 万）位列前三。榜单呈「两端强」：低价代步与中高端各占半壁。',
  },
]

const OUT = ['奔驰', '宝马', '奥迪', '大众', '丰田', '本田', '日产', '雷克萨斯', '沃尔沃', '保时捷', '路虎', '别克', '福特', '现代', '起亚']
const COVERED = ['比亚迪', '特斯拉', '理想', '蔚来', '小鹏', '零跑', '哪吒', '问界', '极氪', '小米', '吉利', '长安', '奇瑞', '长城', '五菱', '埃安', 'model', '宏光']

function pickScenario(q) {
  if (/报告|研报|渗透率|政策|补贴|购置税|技术路线|区别|综述|盘点|怎么看|为什么|解读|文档|出口|智驾|智能驾驶|座舱|口碑/.test(q)) return { kind: 'rag' }
  const lo = q.toLowerCase()
  const out = OUT.find((b) => q.includes(b))
  if (out && !COVERED.some((b) => lo.includes(b.toLowerCase()))) return { kind: 'nodata', brand: out }
  const s = SCENARIOS.find((sc) => sc.match(q))
  return s ? { kind: 'sql', s } : { kind: 'sql', s: SCENARIOS[1] }
}

// —— 知识脑离线真检索（CJK 二元组重叠打分）—— //
function qTerms(q) {
  const t = new Set()
  for (const w of (q.toLowerCase().match(/[a-z0-9]{2,}/g) || [])) t.add(w)
  for (const seg of (q.match(/[一-鿿]+/g) || [])) { if (seg.length === 1) t.add(seg); for (let i = 0; i < seg.length - 1; i++) t.add(seg.slice(i, i + 2)) }
  return [...t]
}
function ragRetrieve(q, k = 3) {
  const terms = qTerms(q); if (!terms.length) return []
  return corpus.passages.map((p) => { let s = 0; for (const t of terms) if (p.text.includes(t)) s += t.length >= 2 ? 1 : 0.3; return { p, s } })
    .filter((x) => x.s > 0).sort((a, b) => b.s - a.s).slice(0, k).map((x) => x.p)
}
function trim(t, n = 160) { if (t.length <= n) return t; const c = t.slice(0, n); const m = Math.max(c.lastIndexOf('。'), c.lastIndexOf('；')); return (m > 50 ? c.slice(0, m + 1) : c) + '…' }

export function kbDocs() {
  return corpus.docs.map((d) => ({ docId: d.id, title: d.title || d.filename, fileType: d.fileType || 'md', chunkCount: d.chunkCount, createdAt: d.createdAt }))
}

export async function mockSSE(body, handlers, signal) {
  const { onEvent, onClose } = handlers
  const q = body.question || ''
  const aborted = () => signal?.aborted
  const picked = pickScenario(q)
  await sleep(380); if (aborted()) return

  if (picked.kind === 'nodata') {
    onEvent({ type: 'intent', intent: 'sql', confidence: 0.9 }); await sleep(500); if (aborted()) return
    onEvent({ type: 'sql', sql_text: `SELECT ... WHERE b.brand_name LIKE '%${picked.brand}%' ...` }); await sleep(420); if (aborted()) return
    const msg = `未查询到「${picked.brand}」的相关数据。它可能不在当前覆盖的 101 个品牌内（以国产新能源为主）。试试「比亚迪」「小米SU7」或更宽泛的问题。`
    for (const tk of tokenize(msg)) { if (aborted()) return; onEvent({ type: 'insight', delta: tk }); await sleep(14) }
    onEvent({ type: 'done', conversation_id: null }); onClose?.(); return
  }

  if (picked.kind === 'rag') {
    onEvent({ type: 'intent', intent: 'rag', confidence: 0.9 }); await sleep(600); if (aborted()) return
    const hits = ragRetrieve(q, 3)
    if (!hits.length) {
      const msg = '未在知识库中检索到相关内容。当前公共库覆盖渗透率/政策/技术路线/价格/品牌/出口/智驾/口碑等主题，换个说法再试。'
      for (const tk of tokenize(msg)) { if (aborted()) return; onEvent({ type: 'insight', delta: tk }); await sleep(14) }
      onEvent({ type: 'done', conversation_id: null }); onClose?.(); return
    }
    const ans = '根据知识库检索到的相关内容：\n\n' + hits.map((p, i) => `${trim(p.text)}[${i + 1}]`).join('\n\n')
    for (const tk of tokenize(ans)) { if (aborted()) return; onEvent({ type: 'insight', delta: tk }); await sleep(15) }
    await sleep(220); if (aborted()) return
    for (const p of hits) { if (aborted()) return; onEvent({ type: 'citation', citation: { doc_id: p.docId, page_no: p.page, chunk_id: p.chunkId, heading_path: p.headingPath, title: p.title } }); await sleep(50) }
    onEvent({ type: 'done', conversation_id: null }); onClose?.(); return
  }

  const s = picked.s
  onEvent({ type: 'intent', intent: 'sql', confidence: 0.94 }); await sleep(560); if (aborted()) return
  onEvent({ type: 'sql', sql_text: s.sql }); await sleep(440); if (aborted()) return
  onEvent({ type: 'rows', columns: s.columns, rows: s.rows }); await sleep(320); if (aborted()) return
  onEvent({ type: 'chart', chart: s.chart }); await sleep(360); if (aborted()) return
  for (const tk of tokenize(s.insight)) { if (aborted()) return; onEvent({ type: 'insight', delta: tk }); await sleep(18) }
  onEvent({ type: 'done', conversation_id: null }); onClose?.()
}
