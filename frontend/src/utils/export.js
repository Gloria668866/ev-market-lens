// 导出工具：重度用户高频动作 —— 把结果带走（CSV / PNG / 复制文本）。
// 不引第三方库，全部用浏览器原生能力。

/** columns + 数组行 → CSV 文本（RFC4180 转义；含 UTF-8 BOM，Excel 直接打开不乱码） */
export function toCSV(columns, rows) {
  const esc = (v) => {
    const s = v == null ? '' : String(v)
    return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
  }
  const lines = [columns.map(esc).join(',')]
  for (const r of rows) lines.push(r.map(esc).join(','))
  return '\ufeff' + lines.join('\r\n')
}

/** 触发浏览器下载 */
export function downloadFile(filename, content, mime = 'text/plain') {
  const blob = content instanceof Blob ? content : new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

/** dataURL（如 ECharts getDataURL 的 PNG）→ 下载 */
export function downloadDataURL(filename, dataURL) {
  const a = document.createElement('a')
  a.href = dataURL
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
}

/** 复制文本到剪贴板；返回 Promise<boolean>。带 execCommand 兜底（http 演示环境无 clipboard API）。 */
export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    try {
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      const ok = document.execCommand('copy')
      ta.remove()
      return ok
    } catch {
      return false
    }
  }
}

/** 用消息标题/时间生成安全文件名 */
export function exportName(prefix, ext) {
  const t = new Date()
  const pad = (n) => String(n).padStart(2, '0')
  return `${prefix}_${t.getFullYear()}${pad(t.getMonth() + 1)}${pad(t.getDate())}_${pad(t.getHours())}${pad(t.getMinutes())}.${ext}`
}
