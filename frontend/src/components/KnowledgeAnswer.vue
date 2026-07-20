<script setup>
// 知识问答脑：答案正文 + 来源引用卡（文档名 / 章节 heading_path / 页码，点开就地溯源）。
// 引用结构对齐后端 §5.5：{doc_id, page_no, chunk_id, heading_path, title}。
import { ref } from 'vue'
import { copyText } from '@/utils/export.js'
const props = defineProps({
  msg: { type: Object, required: true },
  streaming: { type: Boolean, default: false },
})
const copied = ref(false)
async function copyAnswer() {
  const cites = (props.msg.citations || [])
    .map((c, i) => `[${i + 1}] 《${c.title || '文档 #' + c.doc_id}》 ${c.heading_path || ''} P${c.page_no}`)
    .join('\n')
  const text = (props.msg.insight || '') + (cites ? `\n\n来源：\n${cites}` : '')
  if (await copyText(text)) { copied.value = true; setTimeout(() => { copied.value = false }, 1500) }
}
const openIdx = ref(-1)
function toggle(i) { openIdx.value = openIdx.value === i ? -1 : i }
function pathParts(c) { return (c.heading_path || '').split(/\s*[>›/]\s*/).filter(Boolean) }
</script>

<template>
  <div class="answer">
    <div class="ans-body">
      <span class="text">{{ msg.insight }}</span><span v-if="streaming" class="cursor"></span>
      <button v-if="msg.insight && !streaming" class="copy" :class="{ ok: copied }" @click="copyAnswer">
        {{ copied ? '✓ 已复制（含来源）' : '复制答案' }}
      </button>
    </div>

    <div v-if="msg.citations && msg.citations.length" class="citations">
      <div class="cite-head"><span class="d"></span>来源引用 · {{ msg.citations.length }}</div>
      <ul>
        <li v-for="(c, i) in msg.citations" :key="c.chunk_id || i">
          <button class="cite" :class="{ open: openIdx === i }" @click="toggle(i)">
            <span class="idx mono">{{ String(i + 1).padStart(2, '0') }}</span>
            <span class="meta">
              <span class="doc">{{ c.title || ('文档 #' + c.doc_id) }}</span>
              <span class="path" v-if="c.heading_path">
                <template v-for="(seg, k) in pathParts(c)" :key="k">
                  <span class="seg">{{ seg }}</span><span v-if="k < pathParts(c).length - 1" class="sep">›</span>
                </template>
              </span>
            </span>
            <span class="page mono">P{{ c.page_no }}</span>
          </button>
          <div v-if="openIdx === i" class="trace-box">
            <span class="trace-k mono">出处定位 ▸</span>
            <span class="trace-v">《{{ c.title || ('文档 #' + c.doc_id) }}》 · {{ c.heading_path || '（无章节）' }} · 第 {{ c.page_no }} 页</span>
          </div>
        </li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.answer { display: flex; flex-direction: column; gap: 18px; }
.ans-body { font-size: 15px; line-height: 1.9; color: var(--ink); white-space: pre-wrap; }
.ans-body .copy { display: block; margin-top: 12px; font-size: 11.5px; font-weight: 600; color: var(--ink-3); border: 1px solid var(--line); border-radius: 8px; padding: 4px 12px; transition: color .12s, border-color .12s; }
.ans-body .copy:hover { color: var(--up); border-color: var(--up); }
.ans-body .copy.ok { color: var(--up); border-color: var(--up); }
.cursor { display: inline-block; width: 7px; height: 15px; background: var(--up); margin-left: 2px; vertical-align: -2px; animation: blink 1s step-start infinite; }

.citations { border-top: 1px dashed var(--line-strong); padding-top: 14px; }
.cite-head { display: flex; align-items: center; gap: 7px; font-family: var(--font-mono); font-size: 10.5px; font-weight: 600; color: var(--up); letter-spacing: .1em; margin-bottom: 10px; text-transform: uppercase; }
.cite-head .d { width: 6px; height: 6px; border-radius: 50%; background: var(--accent); }
.citations ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 9px; }
.cite { width: 100%; display: flex; align-items: center; gap: 13px; text-align: left; background: var(--bg); border: 1px solid var(--line); border-radius: var(--r-md); padding: 11px 14px; transition: border-color .14s, transform .12s, box-shadow .14s; }
.cite:hover { border-color: var(--line-strong); transform: translateX(2px); box-shadow: var(--sh-sm); }
.cite.open { border-color: var(--accent); }
.idx { flex: none; width: 30px; height: 30px; border-radius: 8px; background: var(--accent); color: #fff; display: inline-flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 600; }
.meta { display: flex; flex-direction: column; gap: 3px; min-width: 0; flex: 1; }
.doc { font-size: 13.5px; font-weight: 700; color: var(--ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.path { display: flex; align-items: center; flex-wrap: wrap; gap: 5px; }
.path .seg { font-family: var(--font-mono); font-size: 10.5px; color: var(--ink-2); background: var(--bg-sunken); border-radius: 5px; padding: 1px 7px; }
.path .sep { color: var(--ink-4); }
.page { margin-left: auto; flex: none; font-size: 12px; font-weight: 600; color: var(--up); align-self: flex-start; }

.trace-box { display: flex; gap: 9px; margin: 7px 0 2px 43px; padding: 10px 14px; background: var(--up-wash); border: 1px dashed var(--up); border-radius: var(--r-sm); animation: fadeIn .18s ease; }
.trace-k { flex: none; font-size: 10px; font-weight: 600; color: var(--up); letter-spacing: .06em; text-transform: uppercase; padding-top: 1px; }
.trace-v { font-size: 12.5px; color: var(--ink-2); line-height: 1.6; }
</style>
