// 知识库列表：mock（取自真实语料 kb_corpus.json）↔ live（/api/kb/list）。
import { API, IS_MOCK, authHeaders } from './config.js'
import { kbDocs } from './mock.js'

export async function listDocs() {
  if (IS_MOCK) return kbDocs()
  const r = await fetch(API.kbList, { headers: authHeaders() })
  if (!r.ok) return []
  const d = await r.json().catch(() => ({}))
  return (d.documents || []).map((x) => ({
    docId: x.id, title: x.filename, fileType: x.file_type, chunkCount: x.chunk_count, createdAt: (x.created_at || '').slice(0, 10),
  }))
}
