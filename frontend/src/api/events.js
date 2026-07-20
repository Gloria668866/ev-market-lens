// SSE 事件解码（PRD-2 §9.1 标准协议）
// ------------------------------------------------------------------
// 后端已对齐 §9.1（2026-05-25，后端⑤），故这里**不再做「两种形态都吃」的归一化兼容层**，
// 直接按标准事件名/JSON 结构解码成「组件用的规范事件」：
//
//   intent    {intent, confidence, conversation_id}     → {type:'intent', ...}
//   sql       {sql_text}                                 → {type:'sql'}（仅审计，前端不展示）
//   rows      {columns, rows}                            → {type:'rows', columns, rows}
//   chart     图表描述符 {default_type, applicable_types, dimension, measures, title}
//   insight   {delta}                                    → {type:'insight', delta}（逐段流式）
//   citation  {doc_id, page_no, chunk_id, heading_path, title}  → {type:'citation', citation}
//             ⚠ 后端「一条 citation 一个事件」逐条推，这里解码成单条，由 useChat 累加。
//   done      {msg_id, conversation_id, has_answer}      → {type:'done', ...}
//   error     {code, message}                            → {type:'error', ...}
//
// 只剩这一层「原始 SSE 帧 → 规范事件」的解码，不含任何旧后端兼容分支。

function tryParse(raw) {
  if (typeof raw !== 'string') return raw
  const s = raw.trim()
  if (!s) return null
  try { return JSON.parse(s) } catch { return raw }
}

/**
 * @param {string} event SSE event 名
 * @param {string} raw   data 原文（JSON）
 * @returns {object|null} 规范事件，或 null（忽略未知事件）
 */
export function normalizeEvent(event, raw) {
  const name = (event || 'message').toLowerCase()
  const d = tryParse(raw)
  const o = (d && typeof d === 'object') ? d : {}

  switch (name) {
    case 'stage':
      // 后端在 agent 起跑前立即推送（即时反馈）；旧后端没有此事件，不影响兼容
      return { type: 'stage', stage: o.stage || '', message: o.message || '' }

    case 'intent':
      return { type: 'intent', intent: o.intent || 'sql', confidence: o.confidence ?? null, conversationId: o.conversation_id ?? null }

    case 'sql':
      // §9.1 用 {sql_text}；仅供审计/调试，数据分析卡不展示
      return { type: 'sql', sql: o.sql_text || '' }

    case 'rows':
      return { type: 'rows', columns: o.columns || [], rows: o.rows || [] }

    case 'chart':
      // 图表描述符；chart.js 据此 + rows 自建 option、出切换器与图例
      return { type: 'chart', chart: d }

    case 'insight':
      return { type: 'insight', delta: o.delta ?? '' }

    case 'citation':
      // 后端逐条推：一个事件 = 一条引用对象
      return { type: 'citation', citation: o }

    case 'done':
      return { type: 'done', msgId: o.msg_id ?? null, conversationId: o.conversation_id ?? null, hasAnswer: o.has_answer ?? true }

    case 'error':
      return { type: 'error', code: o.code || 'ERROR', message: o.message || '出错了，请稍后重试' }

    default:
      return null
  }
}
