<script setup>
// 知识库管理：上传文档（选文件 → /api/kb/upload → 轮询 status parsing→ready/failed 显示进度）、
// 文档列表（/api/kb/list）、删除（/api/kb/delete）。全部按当前用户隔离（请求带 Bearer，后端按 user_id 过滤）。
import { onMounted, onUnmounted, ref } from 'vue'
import { listDocs, uploadDoc, getDocStatus, deleteDoc, validateFile, MAX_UPLOAD_MB } from '@/api/kb.js'

defineEmits(['close'])

const docs = ref([])
const loading = ref(true)
const err = ref('')
const uploading = ref(false)
const fileInput = ref(null)
const polling = new Map()   // docId → intervalId

const STATUS = { ready: ['已就绪', 'ok'], parsing: ['解析中', 'warn'], failed: ['解析失败', 'err'] }

onMounted(refresh)
onUnmounted(() => { for (const t of polling.values()) clearInterval(t); polling.clear() })

async function refresh() {
  loading.value = true
  try {
    docs.value = await listDocs()
    // 进来时若有仍在解析的，续上轮询
    for (const d of docs.value) if (d.status === 'parsing') startPoll(d.docId)
  } catch (e) { err.value = e.message || '加载失败' }
  loading.value = false
}

function pickFile() { if (!uploading.value) fileInput.value?.click() }

async function onFile(e) {
  const file = e.target.files?.[0]
  e.target.value = ''           // 允许再次选同一文件
  if (!file) return
  err.value = ''
  const bad = validateFile(file)
  if (bad) { err.value = bad; return }
  uploading.value = true
  try {
    const r = await uploadDoc(file)              // {doc_id, status:'parsing', file_type}
    // 乐观插入一条「解析中」，随后轮询刷新状态
    docs.value.unshift({
      docId: r.doc_id, title: file.name, status: r.status || 'parsing',
      chunkCount: 0, fileType: r.file_type || (file.name.split('.').pop() || '').toLowerCase(),
      createdAt: new Date().toISOString().slice(0, 10),
    })
    startPoll(r.doc_id)
  } catch (e) { err.value = e.message || '上传失败' }
  uploading.value = false
}

// 轮询单个文档状态：parsing → ready/failed 即停
function startPoll(docId) {
  if (polling.has(docId)) return
  const t = setInterval(async () => {
    try {
      const s = await getDocStatus(docId)
      const d = docs.value.find((x) => x.docId === docId)
      if (d) { d.status = s.status; d.chunkCount = s.chunk_count ?? d.chunkCount }
      if (s.status === 'ready' || s.status === 'failed') stopPoll(docId)
    } catch { stopPoll(docId) }
  }, 2000)
  polling.set(docId, t)
}
function stopPoll(docId) {
  const t = polling.get(docId)
  if (t) { clearInterval(t); polling.delete(docId) }
}

async function remove(d) {
  if (!confirm(`删除《${d.title}》？删除后问答将不再引用该文档。`)) return
  try {
    await deleteDoc(d.docId)
    stopPoll(d.docId)
    docs.value = docs.value.filter((x) => x.docId !== d.docId)
  } catch (e) { err.value = e.message || '删除失败' }
}
</script>

<template>
  <div class="mask" @click.self="$emit('close')">
    <div class="modal">
      <header>
        <div>
          <h3>知识库</h3>
          <p class="sub">上传行研报告 / 政策 / 车评，问答即可带章节页码引用溯源</p>
        </div>
        <button class="x" @click="$emit('close')">✕</button>
      </header>

      <!-- 上传区：点击选文件 → 上传 → 轮询解析进度 -->
      <input ref="fileInput" type="file" accept=".pdf,.html,.htm,.md,.txt" hidden @change="onFile" />
      <div class="upload" :class="{ busy: uploading }" @click="pickFile">
        <svg v-if="!uploading" viewBox="0 0 24 24" width="22" height="22"><path d="M12 16V5m0 0l-4 4m4-4l4 4M5 19h14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>
        <span v-else class="spin"></span>
        <div>
          <strong>{{ uploading ? '上传中…' : '上传文档' }}</strong>
          <span>支持 PDF / HTML / Markdown / TXT · 单文件 ≤ {{ MAX_UPLOAD_MB }}MB · 点击选择文件</span>
        </div>
      </div>
      <p v-if="err" class="err-bar">{{ err }}</p>

      <div class="list">
        <p v-if="loading" class="hint">加载中…</p>
        <p v-else-if="!docs.length" class="hint">知识库还是空的，上传第一份文档开始吧。</p>
        <div v-for="d in docs" :key="d.docId" class="doc">
          <span class="ftype">{{ (d.fileType || (d.title || '').split('.').pop()).toUpperCase() }}</span>
          <div class="dmeta">
            <span class="dtitle">{{ d.title }}</span>
            <span class="dinfo">
              <template v-if="d.status === 'ready'">{{ d.chunkCount }} 切片</template>
              <template v-else-if="d.status === 'parsing'">解析中，请稍候…</template>
              <template v-else>无法解析，可删除后重传</template>
              <span v-if="d.createdAt"> · {{ d.createdAt }}</span>
            </span>
          </div>
          <span class="dstatus" :class="STATUS[d.status]?.[1]">
            <span v-if="d.status === 'parsing'" class="dot"></span>{{ STATUS[d.status]?.[0] || d.status }}
          </span>
          <button class="del" title="删除文档" @click="remove(d)">✕</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.mask {
  position: fixed; inset: 0; background: rgba(17,17,17,.32); backdrop-filter: blur(4px);
  display: flex; align-items: center; justify-content: center; z-index: 50; animation: fadeIn .2s ease; padding: 20px;
}
.modal {
  width: min(580px, 96vw); max-height: 84vh; background: var(--bg); border-radius: var(--r-lg);
  box-shadow: var(--sh-lg); display: flex; flex-direction: column; overflow: hidden;
  border: 1px solid var(--line); animation: fadeUp .22s ease;
}
header { display: flex; align-items: flex-start; padding: 22px 24px 16px; border-bottom: 1px solid var(--line); }
h3 { margin: 0; font-family: var(--font-display); font-size: 19px; font-weight: 700; color: var(--ink); }
.sub { margin: 5px 0 0; font-size: 12.5px; color: var(--ink-3); }
.x { margin-left: auto; font-size: 15px; color: var(--ink-3); width: 30px; height: 30px; border-radius: 8px; }
.x:hover { background: var(--bg-subtle); color: var(--ink); }

.upload {
  margin: 18px 24px 8px; display: flex; align-items: center; gap: 14px;
  border: 1.5px dashed var(--accent-border); border-radius: var(--r-md); padding: 17px 18px;
  color: var(--accent); background: var(--accent-wash); cursor: pointer; transition: border-color .15s, background .15s;
}
.upload:hover { border-color: var(--accent); }
.upload.busy { cursor: progress; opacity: .8; }
.upload strong { display: block; font-size: 13.5px; color: var(--ink); }
.upload span { font-size: 12px; color: var(--ink-3); }
.spin { width: 20px; height: 20px; border: 2.5px solid var(--accent-wash-2); border-top-color: var(--accent); border-radius: 50%; animation: spin .8s linear infinite; }

.err-bar { margin: 6px 24px 0; font-size: 12.5px; color: var(--accent); background: var(--accent-wash); border: 1px solid var(--accent-border); border-radius: var(--r-sm); padding: 8px 12px; }

.list { padding: 8px 24px 22px; overflow-y: auto; }
.hint { font-size: 13px; color: var(--ink-3); padding: 16px 0; text-align: center; }
.doc { display: flex; align-items: center; gap: 13px; padding: 12px 0; border-bottom: 1px solid var(--line); }
.doc:last-child { border-bottom: none; }
.doc:hover .del { opacity: 1; }
.ftype {
  flex: none; width: 40px; height: 40px; border-radius: 10px; background: var(--bg-sunken); color: var(--ink-2);
  font-family: var(--font-mono); font-size: 10px; font-weight: 600; display: inline-flex; align-items: center; justify-content: center;
}
.dmeta { display: flex; flex-direction: column; gap: 2px; min-width: 0; flex: 1; }
.dtitle { font-size: 13.5px; font-weight: 700; color: var(--ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dinfo { font-size: 12px; color: var(--ink-3); }
.dstatus { flex: none; display: inline-flex; align-items: center; gap: 5px; font-size: 11.5px; font-weight: 700; padding: 3px 11px; border-radius: 999px; }
.dstatus.ok { background: var(--up-wash); color: var(--up); }
.dstatus.warn { background: var(--accent-wash); color: var(--accent); }
.dstatus.err { background: var(--down-wash); color: var(--down); }
.dstatus .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--accent); animation: blink 1s ease-in-out infinite; }
.del { flex: none; width: 26px; height: 26px; border-radius: 7px; color: var(--ink-3); font-size: 12px; opacity: 0; transition: opacity .15s, background .12s, color .12s; }
.del:hover { background: var(--down-wash); color: var(--down); }
</style>
