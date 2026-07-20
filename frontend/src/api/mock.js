// 本地 Mock：后端未就绪时，按 PRD-2 §9.1 的事件节奏模拟 SSE 流，先把界面调通。
// 直接吐「规范事件」（与 events.js 归一化后的形态一致），组件层无感知。
// 数据脑用贴近真实量级的样例；知识脑(RAG)做**离线真检索**——对 kb_corpus.json（由
// data/build_local_kb.py 从真实语料库导出）做词法检索，命中真实原文段落、给真实引用，绝非写死。

import corpus from './kb_corpus.json'

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

// 把一段文字按字切片，模拟逐 token 流式
function tokenize(text) {
  const out = []
  for (const seg of text.split(/(\n)/)) {
    if (seg === '\n') { out.push('\n'); continue }
    for (let i = 0; i < seg.length; i += 2) out.push(seg.slice(i, i + 2))
  }
  return out
}

// —— 场景库 —— //
const SCENARIOS = [
  {
    match: (q) => /理想|小米|su7|谁卖|对比|vs/i.test(q),
    intent: 'sql',
    sql: `SELECT s.series_name, SUM(f.volume) AS total_volume
FROM fact_sales_rank f
JOIN dim_series s ON s.series_id = f.series_id
WHERE s.series_name LIKE '%理想%' OR s.series_name LIKE '%小米SU7%'
GROUP BY s.series_name
ORDER BY total_volume DESC
LIMIT 10;`,
    columns: ['车系', '累计销量'],
    rows: [['小米SU7', 460536], ['理想L6', 387948], ['理想L7', 227192], ['理想L9', 138204], ['理想MEGA', 41260]],
    chart: { default_type: 'bar', applicable_types: ['bar', 'hbar', 'line', 'pie'], dimension: '车系', measures: ['累计销量'], title: '车系销量对比' },
    insight: '小米SU7 以累计 46.05 万辆领跑，超过理想全系单车型最高的 L6（38.79 万辆）。\n\n归因：小米SU7 作为单一爆款车型集中放量，而理想以 L6/L7/L9 多车型分摊销量；若按品牌口径合计，理想全系约 79.5 万辆仍高于小米SU7。建议进一步看月度趋势判断后劲。',
  },
  {
    match: (q) => /top|前\s*\d+|排名|榜|纯电|插混|增程|销量/i.test(q),
    intent: 'sql',
    sql: `SELECT s.series_name, SUM(f.volume) AS total_volume
FROM fact_sales_rank f
JOIN dim_series s ON s.series_id = f.series_id
JOIN dim_date d ON d.date_id = f.date_id
WHERE f.new_energy_type = 1 AND d.year = 2025
GROUP BY s.series_name
ORDER BY total_volume DESC
LIMIT 10;`,
    columns: ['车系', '2025累计销量'],
    rows: [
      ['星愿', 465775], ['五菱宏光MINIEV', 435599], ['Model Y', 425337], ['海鸥', 388912],
      ['Model 3', 261480], ['元UP', 240117], ['海豚', 198640], ['小米SU7', 187233],
      ['AION S', 165902], ['零跑C10', 152018],
    ],
    chart: { default_type: 'bar', applicable_types: ['bar', 'hbar', 'line', 'pie'], dimension: '车系', measures: ['2025累计销量'], title: '2025 纯电销量 Top10' },
    insight: '2025 年纯电销量 Top10 中，星愿（46.58 万）、五菱宏光MINIEV（43.56 万）、Model Y（42.53 万）位列前三。\n\n归因：榜单呈「两端强」格局——低价代步（星愿、宏光MINIEV、海鸥）与中高端（Model Y/3、小米SU7）各占半壁，10-15 万主流家用纯电反而较少进入头部。建议关注小米SU7 作为新势力单车型已挤入 Top8 的势头。',
  },
]

// —— 知识脑离线真检索：对 kb_corpus.json 做词法召回（中文无 jieba → CJK 二元组 + 英数词重叠打分）——
function _qTerms(q) {
  const terms = new Set()
  for (const w of (q.toLowerCase().match(/[a-z0-9]{2,}/g) || [])) terms.add(w)
  for (const seg of (q.match(/[一-鿿]+/g) || [])) {
    if (seg.length === 1) terms.add(seg)
    for (let i = 0; i < seg.length - 1; i++) terms.add(seg.slice(i, i + 2))   // 二元组
  }
  return [...terms]
}
function ragRetrieve(q, k = 3) {
  const terms = _qTerms(q)
  if (!terms.length) return []
  return corpus.passages
    .map((p) => {
      let s = 0
      for (const t of terms) if (p.text.includes(t)) s += t.length >= 2 ? 1 : 0.3
      return { p, s }
    })
    .filter((x) => x.s > 0)
    .sort((a, b) => b.s - a.s)
    .slice(0, k)
    .map((x) => x.p)
}
function _trim(t, n = 180) {
  if (t.length <= n) return t
  const cut = t.slice(0, n)
  const m = Math.max(cut.lastIndexOf('。'), cut.lastIndexOf('；'), cut.lastIndexOf('\n'))
  return (m > 60 ? cut.slice(0, m + 1) : cut) + '…'
}
function synthAnswer(hits) {
  return '根据知识库检索到的相关内容：\n\n' + hits.map((p, i) => `${_trim(p.text)}[${i + 1}]`).join('\n\n')
}

// 覆盖范围外的（合资/进口）品牌：模拟真实后端「查不到就老实说，绝不编造」
const OUT_OF_COVERAGE = ['奔驰', '宝马', '奥迪', '大众', '丰田', '本田', '日产', '马自达', '雷克萨斯', '沃尔沃', '凯迪拉克', '保时捷', '路虎', '捷豹', '别克', '雪佛兰', '福特', '现代', '起亚', '三菱', '英菲尼迪', '讴歌', '林肯']
const COVERED = ['比亚迪', '特斯拉', '理想', '蔚来', '小鹏', '零跑', '哪吒', '问界', '极氪', '小米', '吉利', '长安', '奇瑞', '长城', '五菱', '广汽', '埃安', '深蓝', '腾势', '方程豹', '仰望', '星愿', '海鸥', '海豚', 'model', '宏光', '智己', '阿维塔']

// 与 graph.py _CHAT_KW 对齐：明确的问候/闲聊/超纲词
const _CHAT_KW = ['你好', '您好', '在吗', '吃饭', '谢谢', '多谢', '再见', '拜拜', '晚安', '早安', '笑话', '你是谁', '你叫', '无聊', '天气', '几点', '哈哈', '你会', '帮我']

function pickScenario(question) {
  // 1. 闲聊/超纲优先检测（防止兜底 SQL 误判）
  if (_CHAT_KW.some((k) => question.includes(k))) return { kind: 'chat' }

  // 2. 信息不足检测（对齐后端 _is_incomplete_sql_question）
  const hasEntity = /比亚迪|特斯拉|理想|蔚来|小鹏|零跑|哪吒|问界|极氪|小米|吉利|长安|model|su7|汉|秦|海鸥|海豚|宏光|2024|2025|2026|今年|去年|纯电|插混|增程|top|前\d/.test(question)
  if (question.trim().length <= 4 || !hasEntity) {
    // "销量"、"中国销量"、"排名" → clarify
    return { kind: 'clarify' }
  }

  if (/报告|研报|渗透率|政策|补贴|购置税|双积分|技术路线|区别|综述|盘点|怎么看|为什么|解读|文档|出口|智驾|智能驾驶|座舱|口碑/.test(question)) return { kind: 'rag' }
  // 覆盖范围外品牌（如「奔驰销量」）→ 走 nodata，与真实后端 B1 行为一致
  const q = question.toLowerCase()
  const out = OUT_OF_COVERAGE.find((b) => question.includes(b))
  const covered = COVERED.some((b) => q.includes(b.toLowerCase()))
  if (out && !covered) return { kind: 'nodata', brand: out }
  const s = SCENARIOS.find((sc) => sc.match(question))
  return s ? { kind: 'sql', s } : { kind: 'sql', s: SCENARIOS[1] } // 兜底给 Top10
}

/**
 * mock 版 SSE。签名与真实 transport 对齐：onEvent 收规范事件。
 */
export async function mockSSE(body, handlers, signal) {
  const { onEvent, onClose } = handlers
  const q = body.question || ''
  const aborted = () => signal?.aborted

  const picked = pickScenario(q)
  await sleep(420); if (aborted()) return

  if (picked.kind === 'clarify') {
    onEvent({ type: 'intent', intent: 'clarify', confidence: 1.0 })
    await sleep(300); if (aborted()) return
    const msg = '您的问题信息不够完整，我需要更多细节才能给出准确答案。\n\n请补充：\n· **品牌或车系**：比如「比亚迪」「小米SU7」「理想L6」\n· **时间范围**：比如「2025年」「今年」「最近一个月」\n· **具体指标**：销量？排名？价格？口碑？\n\n示例完整问法：\n✓「2025年纯电销量Top10」\n✓「比亚迪各车系今年销量对比」\n✓「理想L6和小米SU7谁卖得多」'
    for (const tk of tokenize(msg)) { if (aborted()) return; onEvent({ type: 'insight', delta: tk }); await sleep(12) }
    onEvent({ type: 'done', msgId: Date.now() })
    onClose?.()
    return
  }

  if (picked.kind === 'chat') {
    onEvent({ type: 'intent', intent: 'chat', confidence: 1.0 })
    await sleep(300); if (aborted()) return
    const msg = '我是「车市镜」——专注新能源汽车销量数据分析与行业知识问答的助手，暂时只聊车市相关的话题～\n\n你可以这样问我：\n· 数据：「2025年纯电销量 Top10」「比亚迪各车系今年卖了多少」\n· 解读：「小米SU7 口碑怎么样」「最近的购车补贴政策怎么说」'
    for (const tk of tokenize(msg)) { if (aborted()) return; onEvent({ type: 'insight', delta: tk }); await sleep(12) }
    onEvent({ type: 'done', msgId: Date.now() })
    onClose?.()
    return
  }

  if (picked.kind === 'nodata') {
    // 覆盖范围外品牌：出意图 + SQL（展示 Text2SQL 仍尝试了），但 0 行 → 不出图、不编造，老实告知
    onEvent({ type: 'intent', intent: 'sql', confidence: 0.9 })
    await sleep(600); if (aborted()) return
    onEvent({ type: 'sql', sql:
`SELECT s.series_name, SUM(f.volume) AS total_volume
FROM fact_sales_rank f
JOIN dim_series s ON s.series_id = f.series_id
JOIN dim_brand b ON b.brand_id = s.brand_id
WHERE b.brand_name LIKE '%${picked.brand}%'
GROUP BY s.series_id, s.series_name
ORDER BY total_volume DESC` })
    await sleep(520); if (aborted()) return
    const msg = `未查询到「${picked.brand}」的相关数据。「${picked.brand}」可能不在当前数据库覆盖范围内（目前覆盖 101 个品牌，以国产新能源为主）。\n\n可尝试：\n1. 换一个品牌或车系（如「比亚迪」「小米SU7」）\n2. 问更宽泛的问题（如「2025年纯电销量Top10」）`
    for (const tk of tokenize(msg)) { if (aborted()) return; onEvent({ type: 'insight', delta: tk }); await sleep(14) }
    onEvent({ type: 'done', msgId: Date.now() })
    onClose?.()
    return
  }

  if (picked.kind === 'rag') {
    onEvent({ type: 'intent', intent: 'rag', confidence: 0.9 })
    await sleep(700); if (aborted()) return
    const hits = ragRetrieve(q, 3)
    if (!hits.length) {                         // 防幻觉：没检索到就老实说，不编造
      const msg = '未在知识库中检索到与该问题相关的内容。可换个说法，或上传相关文档后再问（当前公共知识库覆盖渗透率 / 政策补贴 / 技术路线 / 价格格局 / 品牌盘点 / 出口 / 智驾 / 口碑等主题）。'
      for (const tk of tokenize(msg)) { if (aborted()) return; onEvent({ type: 'insight', delta: tk }); await sleep(14) }
      onEvent({ type: 'done', msgId: Date.now() }); onClose?.(); return
    }
    // 先流式抽取式答案，再逐条推真实引用（与后端事件节奏一致）
    for (const tk of tokenize(synthAnswer(hits))) {
      if (aborted()) return
      onEvent({ type: 'insight', delta: tk })
      await sleep(16)
    }
    await sleep(260); if (aborted()) return
    for (const p of hits) {
      if (aborted()) return
      // 字段对齐后端 §5.5：{doc_id, page_no, chunk_id, heading_path, title}
      onEvent({ type: 'citation', citation: { doc_id: p.docId, page_no: p.page, chunk_id: p.chunkId, heading_path: p.headingPath, title: p.title } })
      await sleep(60)
    }
    onEvent({ type: 'done', msgId: Date.now() })
    onClose?.()
    return
  }

  const s = picked.s
  onEvent({ type: 'intent', intent: 'sql', confidence: 0.94 })
  await sleep(650); if (aborted()) return
  onEvent({ type: 'sql', sql: s.sql })
  await sleep(520); if (aborted()) return
  onEvent({ type: 'rows', columns: s.columns, rows: s.rows })
  await sleep(360); if (aborted()) return
  onEvent({ type: 'chart', chart: s.chart })
  await sleep(420); if (aborted()) return
  for (const tk of tokenize(s.insight)) {
    if (aborted()) return
    onEvent({ type: 'insight', delta: tk })
    await sleep(20)
  }
  onEvent({ type: 'done', msgId: Date.now() })
  onClose?.()
}
