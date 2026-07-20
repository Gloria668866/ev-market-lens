// 把一条助手结果导出为「干净的 Markdown 报告」（贴进周报 / IM / 飞书都可）。
// 纯前端，无依赖；数据脑带表格+SQL，知识脑带答案+引用，统一带品牌页脚。
import { downloadFile, exportName } from './export.js'

function mdTable(columns = [], rows = []) {
  if (!columns.length || !rows.length) return ''
  const esc = (v) => String(v == null ? '' : v).replace(/\|/g, '\\|')
  const head = `| ${columns.map(esc).join(' | ')} |`
  const sep = `| ${columns.map(() => '---').join(' | ')} |`
  const body = rows.slice(0, 50).map((r) => `| ${r.map(esc).join(' | ')} |`).join('\n')
  const more = rows.length > 50 ? `\n\n> 仅展示前 50 行，共 ${rows.length} 行。` : ''
  return `${head}\n${sep}\n${body}${more}`
}

/** msg → markdown 文本 */
export function buildReportMarkdown(msg, question = '') {
  const lines = []
  const title = question || msg.question || '车市镜分析报告'
  lines.push(`# ${title}`, '')
  const intentLabel = { sql: '数据分析', rag: '知识问答', hybrid: '综合分析' }[msg.intent] || '分析'
  lines.push(`> 车市镜 · 新能源车市情报 Agent · ${intentLabel} · ${new Date().toLocaleString('zh-CN')}`, '')

  if (msg.insight) { lines.push('## 结论与归因', '', msg.insight, '') }

  if (msg.columns?.length && msg.rows?.length) {
    lines.push('## 数据明细', '', mdTable(msg.columns, msg.rows), '')
  }

  if (msg.citations?.length) {
    lines.push('## 来源引用', '')
    msg.citations.forEach((c, i) => {
      lines.push(`${i + 1}. 《${c.title || '文档 #' + c.doc_id}》 ${c.heading_path ? '— ' + c.heading_path : ''} （第 ${c.page_no} 页）`)
    })
    lines.push('')
  }

  if (msg.sql) { lines.push('## 生成的 SQL（Text2SQL）', '', '```sql', msg.sql, '```', '') }

  lines.push('---', '', '*由「车市镜 / EV-MarketLens」自动生成 — 双脑 Text2SQL + RAG。*')
  return lines.join('\n')
}

export function exportReport(msg, question = '') {
  downloadFile(exportName('车市镜报告', 'md'), buildReportMarkdown(msg, question), 'text/markdown;charset=utf-8')
}
