<script setup>
import { ref, computed } from 'vue'
import MobileHome from '@/views/MobileHome.vue'
import MobileExplore from '@/views/MobileExplore.vue'
import MobileChat from '@/views/MobileChat.vue'
import MobileKB from '@/views/MobileKB.vue'
import KnowledgeBaseModal from '@/components/KnowledgeBaseModal.vue'
import LoginView from '@/components/LoginView.vue'
import { useChat } from '@/composables/useChat.js'
import { useAuth } from '@/composables/useAuth.js'

const { isAuthed, state: auth, logout } = useAuth()
const { conversations, activeId, messages, sending, newConversation, selectConversation, deleteConversation, renameConversation, send, stop } = useChat()
const showKb = ref(false)

const tab = ref('home')

const tabs = [
  { key: 'home',  label: '首页', icon: '🏠' },
  { key: 'explore', label: '探索', icon: '🔍' },
  { key: 'chat', label: '对话', icon: '💬' },
  { key: 'kb',   label: '知识库', icon: '📚' },
]

const lastQuestion = computed(() => {
  for (let i = messages.value.length - 1; i >= 0; i--) if (messages.value[i].role === 'user') return messages.value[i].content
  return ''
})

function onAsk(q) { if (!activeId.value) newConversation(); send(q); tab.value = 'chat' }
function onSelect(id) { selectConversation(id); tab.value = 'chat' }
function onNew() { newConversation(); tab.value = 'chat' }
</script>

<template>
  <LoginView v-if="!isAuthed" />

  <div v-else class="mobile-app">
    <!-- 页面内容 -->
    <main class="mobile-main">
      <MobileHome    v-if="tab === 'home'"    @ask="onAsk" />
      <MobileExplore v-if="tab === 'explore'" @ask="onAsk" />
      <MobileChat    v-if="tab === 'chat'"
        :messages="messages" :sending="sending" :lastQuestion="lastQuestion"
        :conversations="conversations" :activeId="activeId"
        @ask="onAsk" @stop="stop" @select="onSelect"
        @new="onNew" @delete="deleteConversation" />
      <MobileKB      v-if="tab === 'kb'" @ask="onAsk" @open-kb="showKb = true" />
    </main>

    <!-- 底部 Tab -->
    <nav class="mobile-tabs">
      <button v-for="t in tabs" :key="t.key" :class="{ active: tab === t.key }" @click="tab = t.key">
        <span class="tab-icon">{{ t.icon }}</span>
        <span class="tab-label">{{ t.label }}</span>
      </button>
    </nav>

    <KnowledgeBaseModal v-if="showKb" @close="showKb = false" />
  </div>
</template>

<style scoped>
.mobile-app { height: 100%; display: flex; flex-direction: column; background: #f9fafb; }
.mobile-main { flex: 1; overflow-y: auto; -webkit-overflow-scrolling: touch; }

/* 底部导航 */
.mobile-tabs {
  flex: none; display: flex; background: #fff; border-top: 1px solid #e5e7eb;
  padding: 4px 0 env(safe-area-inset-bottom);
}
.mobile-tabs button {
  flex: 1; display: flex; flex-direction: column; align-items: center; gap: 2px;
  padding: 6px 4px; font-size: 10px; color: #9ca3af; transition: color .12s;
}
.mobile-tabs button.active { color: #dc2626; }
.tab-icon { font-size: 20px; }
.tab-label { font-size: 10px; font-weight: 600; }
</style>
