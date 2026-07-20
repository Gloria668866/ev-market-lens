<script setup>
import { ref, computed, nextTick, watch } from 'vue'
import MessageList from '@/components/MessageList.vue'

const props = defineProps({
  messages: Array, sending: Boolean, lastQuestion: String,
  conversations: Array, activeId: [String, Number, null],
})
const emit = defineEmits(['ask', 'stop', 'select', 'new', 'delete'])

const text = ref(''); const ta = ref(null)
function resize() { const el = ta.value; if (!el) return; el.style.height = 'auto'; el.style.height = Math.min(el.scrollHeight, 100) + 'px' }
watch(text, () => nextTick(resize))

function submit() { const q = text.value.trim(); if (!q || props.sending) return; emit('ask', q); text.value = ''; nextTick(resize) }

const showHistory = ref(false)
</script>

<template>
  <div class="chat">
    <!-- 顶栏 -->
    <div class="top">
      <button class="back" @click="showHistory = !showHistory">☰</button>
      <span class="top-title">对话</span>
      <button class="new-chat" @click="emit('new')">＋</button>
    </div>

    <!-- 会话列表（浮层） -->
    <div v-if="showHistory" class="history-overlay" @click.self="showHistory = false">
      <div class="history-panel">
        <div class="hist-title">会话历史</div>
        <div v-for="c in conversations" :key="c.id"
          class="hist-item" :class="{ active: c.id === activeId }"
          @click="emit('select', c.id); showHistory = false">
          {{ c.title }}
          <button class="hist-del" @click.stop="emit('delete', c.id)">×</button>
        </div>
      </div>
    </div>

    <!-- 消息列表 -->
    <div class="chat-body">
      <div v-if="!messages.length" class="empty-hint">
        <div class="empty-icon">💬</div>
        <div class="empty-text">输入问题开始对话</div>
      </div>
      <MessageList v-else :messages="messages" @ask="(q) => emit('ask', q)" />
    </div>

    <!-- 底部输入 -->
    <div class="chat-input">
      <textarea ref="ta" v-model="text" rows="1" placeholder="输入问题…"
        @keydown.enter.exact.prevent="submit" />
      <button v-if="!sending" class="send" :disabled="!text.trim()" @click="submit">发送</button>
      <button v-else class="send stop" @click="emit('stop')">■</button>
    </div>
  </div>
</template>

<style scoped>
.chat { display: flex; flex-direction: column; height: 100%; }
.top { flex: none; display: flex; align-items: center; padding: 8px 12px; background: #fff; border-bottom: 1px solid #e5e7eb; }
.back { font-size: 20px; padding: 4px 8px; }
.top-title { flex: 1; text-align: center; font-size: 15px; font-weight: 700; color: #111827; }
.new-chat { font-size: 20px; padding: 4px 8px; color: #dc2626; }

.history-overlay { position: fixed; inset: 0; z-index: 100; background: rgba(0,0,0,.3); }
.history-panel { position: absolute; left: 0; top: 0; bottom: 0; width: 280px; background: #fff; padding: 16px; overflow-y: auto; }
.hist-title { font-size: 14px; font-weight: 700; margin-bottom: 12px; }
.hist-item { padding: 10px; font-size: 13px; border-bottom: 1px solid #f3f4f6; display: flex; align-items: center; cursor: pointer; }
.hist-item.active { color: #dc2626; font-weight: 600; }
.hist-del { margin-left: auto; color: #9ca3af; font-size: 16px; padding: 0 4px; }

.chat-body { flex: 1; overflow-y: auto; padding: 8px; }
.empty-hint { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; color: #9ca3af; }
.empty-icon { font-size: 40px; margin-bottom: 12px; }
.empty-text { font-size: 14px; }

.chat-input {
  flex: none; display: flex; align-items: flex-end; gap: 8px;
  padding: 8px 12px calc(8px + env(safe-area-inset-bottom));
  background: #fff; border-top: 1px solid #e5e7eb;
}
.chat-input textarea {
  flex: 1; border: 1px solid #e5e7eb; border-radius: 20px; outline: none;
  padding: 8px 14px; font-size: 14px; resize: none; max-height: 100px;
  background: #f9fafb; font-family: inherit;
}
.chat-input textarea:focus { border-color: #dc2626; }
.send {
  flex: none; padding: 8px 16px; border-radius: 20px;
  font-size: 13px; font-weight: 700; background: #dc2626; color: #fff;
}
.send:disabled { background: #e5e7eb; color: #9ca3af; }
.send.stop { background: #6b7280; }
</style>
