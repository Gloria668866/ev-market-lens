<script setup>
import { ref, nextTick, watch } from 'vue'
const props = defineProps({ sending: Boolean, lastQuestion: String })
const emit = defineEmits(['send', 'stop'])
const text = ref(''); const ta = ref(null)
function resize() { const el = ta.value; if (!el) return; el.style.height = 'auto'; el.style.height = Math.min(el.scrollHeight, 140) + 'px' }
watch(text, () => nextTick(resize))
function submit() { const q = text.value.trim(); if (!q || props.sending) return; emit('send', q); text.value = ''; nextTick(resize) }
function onKey(e) {
  if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); submit(); return }
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); submit(); return }
  if (e.key === 'ArrowUp' && !text.value && props.lastQuestion) { e.preventDefault(); text.value = props.lastQuestion; nextTick(() => { resize(); if (ta.value) ta.value.setSelectionRange(ta.value.value.length, ta.value.value.length) }) }
}
</script>

<template>
  <div class="composer">
    <div class="box" :class="{ sending }">
      <textarea ref="ta" v-model="text" rows="1" placeholder="继续追问，或换个问题……" @keydown="onKey" />
      <button v-if="!sending" class="send" :disabled="!text.trim()" @click="submit">
        发送 <svg width="13" height="13" viewBox="0 0 16 16" fill="none"><path d="M3 8h9M9 4l4 4-4 4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>
      </button>
      <button v-else class="stop" @click="emit('stop')"><span class="sq"></span>停止</button>
    </div>
  </div>
</template>

<style scoped>
.composer { flex: none; padding: 14px 24px 18px; background: linear-gradient(180deg, transparent, var(--bg-subtle) 36%); }
.box {
  max-width: var(--maxw-thread); margin: 0 auto;
  display: flex; align-items: flex-end; gap: 10px;
  background: var(--bg); border: 1px solid var(--line-strong); border-radius: var(--r-lg);
  box-shadow: var(--sh-md); padding: 7px 7px 7px 16px; transition: border-color .15s, box-shadow .15s;
}
.box:focus-within { border-color: var(--accent); box-shadow: var(--sh-md), 0 0 0 4px var(--accent-wash); }
textarea { flex: 1; border: none; outline: none; resize: none; background: transparent; font-size: 14.5px; line-height: 1.5; padding: 8px 0; max-height: 140px; color: var(--ink); font-family: var(--font-body); }
textarea::placeholder { color: var(--ink-4); }
.send, .stop { flex: none; display: inline-flex; align-items: center; gap: 6px; padding: 10px 16px; font-size: 13.5px; font-weight: 700; border-radius: var(--r-md); }
.send { background: var(--accent); color: #fff; transition: background .12s; }
.send:hover:not(:disabled) { background: var(--accent-press); }
.send:disabled { background: var(--bg-sunken-2); color: var(--ink-4); cursor: not-allowed; }
.stop { background: var(--bg-sunken); color: var(--ink-2); }
.stop:hover { background: var(--accent-wash); color: var(--accent); }
.stop .sq { width: 9px; height: 9px; border-radius: 2px; background: currentColor; }
</style>
