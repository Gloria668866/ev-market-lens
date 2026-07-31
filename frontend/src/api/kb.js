// 知识库 API：上传 → 轮询解析状态 → 列表 → 删除（全部按当前用户隔离，请求带 Bearer）。
// mock（前端自洽，可离线 demo）↔ live（真后端 /api/kb/*）一个开关切换。
//
// 后端契约（app/kb.py，全部需登录、按 user_id 隔离）：
//   GET    /api/kb/list        -> {documents:[{id,filename,status,file_type,chunk_count,created_at}]}
//   POST   /api/kb/upload      (multipart file) -> {doc_id, status:'parsing', file_type}
//   GET    /api/kb/{doc_id}    -> {doc_id, filename, status, chunk_count, file_type}  （前端轮询）
//   DELETE /api/kb/{doc_id}    -> {doc_id, deleted:true}
// status 取值：parsing（解析中）/ ready（已就绪）/ failed（失败）。
import { ENDPOINTS, IS_MOCK } from './config.js'
import { authHeaders } from './auth.js'

const ALLOW_EXT = ['pdf', 'html', 'htm', 'md', 'txt']
export const MAX_UPLOAD_MB = 20

// 后端文档 → 卡片用归一结构
function normDoc(d) {
  return {
    docId: d.id ?? d.doc_id,
    title: d.title || d.filename || ('文档 #' + (d.id ?? d.doc_id ?? '')),
    filename: d.filename || '',
    sourceUri: d.source_uri || '',
    isPublic: Boolean(d.is_public ?? d.isPublic),
    status: d.status || 'ready',
    chunkCount: d.chunk_count ?? 0,
    fileType: d.file_type || (d.filename || '').split('.').pop()?.toLowerCase() || '',
    createdAt: (d.created_at || '').slice(0, 10),
  }
}

async function jsonOrThrow(r) {
  let data = null
  try { data = await r.json() } catch {}
  if (!r.ok) {
    const d = data && data.detail
    const msg = (typeof d === 'string' && d) || (Array.isArray(d) && d[0]?.msg) || `请求失败（${r.status}）`
    throw new Error(msg)
  }
  return data
}

// —— live 实现 —— //
async function liveList() {
  const r = await fetch(ENDPOINTS.kbList, { headers: { ...authHeaders() } })
  const data = await jsonOrThrow(r)
  return (data.documents || []).map(normDoc)
}
async function liveUpload(file) {
  const fd = new FormData()
  fd.append('file', file)
  // 注意：FormData 不要手动设 Content-Type，浏览器自动带 boundary
  const r = await fetch(ENDPOINTS.kbUpload, { method: 'POST', headers: { ...authHeaders() }, body: fd })
  return jsonOrThrow(r)   // {doc_id, status, file_type}
}
async function liveStatus(docId) {
  const r = await fetch(ENDPOINTS.kbDoc(docId), { headers: { ...authHeaders() } })
  return jsonOrThrow(r)   // {doc_id, filename, status, chunk_count, file_type}
}
async function liveDelete(docId) {
  const r = await fetch(ENDPOINTS.kbDoc(docId), { method: 'DELETE', headers: { ...authHeaders() } })
  return jsonOrThrow(r)
}

// —— mock 实现（文档列表取自 kb_corpus.json：data/build_local_kb.py 从真实语料导出，非占位假数据）—— //
import corpus from './kb_corpus.json'
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
let _mockDocs = (Array.isArray(corpus) ? corpus : (corpus.docs || [])).map((d) => ({
  id: d.id, filename: d.filename || (d.title + '.md'), title: d.title,
  source_uri: d.source_uri || '', is_public: d.is_public ?? true, status: 'ready',
  file_type: d.file_type || d.fileType || 'md',
  chunk_count: d.chunk_count ?? d.chunkCount ?? d.chunks?.length ?? 0,
  created_at: d.created_at || d.createdAt || '',
}))
let _mockSeq = 1000

async function mockList() { await sleep(200); return _mockDocs.map(normDoc) }
async function mockUpload(file) {
  await sleep(500)
  const id = ++_mockSeq
  const ext = (file.name.split('.').pop() || '').toLowerCase()
  const doc = { id, filename: file.name, status: 'parsing', file_type: ext, chunk_count: 0, created_at: new Date().toISOString().slice(0, 10) }
  _mockDocs.unshift(doc)
  // 模拟后台异步解析：约 3.5s 后就绪
  setTimeout(() => { doc.status = 'ready'; doc.chunk_count = 30 + Math.floor(Math.random() * 90) }, 3500)
  return { doc_id: id, status: 'parsing', file_type: ext }
}
async function mockStatus(docId) {
  const d = _mockDocs.find((x) => x.id === docId)
  return d ? { doc_id: d.id, filename: d.filename, status: d.status, chunk_count: d.chunk_count, file_type: d.file_type }
    : { doc_id: docId, status: 'failed' }
}
async function mockDelete(docId) {
  _mockDocs = _mockDocs.filter((x) => x.id !== docId)
  return { doc_id: docId, deleted: true }
}

// —— 对外 —— //
export function validateFile(file) {
  const ext = (file.name.split('.').pop() || '').toLowerCase()
  if (!ALLOW_EXT.includes(ext)) return `不支持的类型「.${ext}」，仅支持 ${ALLOW_EXT.join(' / ')}`
  if (file.size > MAX_UPLOAD_MB * 1024 * 1024) return `文件超过 ${MAX_UPLOAD_MB}MB 上限`
  if (file.size === 0) return '空文件'
  return null
}

export const listDocs = () => (IS_MOCK ? mockList() : liveList())
export const uploadDoc = (file) => (IS_MOCK ? mockUpload(file) : liveUpload(file))
export const getDocStatus = (id) => (IS_MOCK ? mockStatus(id) : liveStatus(id))
export const deleteDoc = (id) => (IS_MOCK ? mockDelete(id) : liveDelete(id))
