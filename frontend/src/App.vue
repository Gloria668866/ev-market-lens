<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import Sidebar from './components/Sidebar.vue'
import TopBar from './components/TopBar.vue'
import CommandCenter from './components/CommandCenter.vue'
import MessageList from './components/MessageList.vue'
import Composer from './components/Composer.vue'
import QuickSuggest from './components/QuickSuggest.vue'
import KnowledgeBaseModal from './components/KnowledgeBaseModal.vue'
import BoardModal from './components/BoardModal.vue'
import PriceModal from './components/PriceModal.vue'
import SettingsModal from './components/SettingsModal.vue'
import AdminModal from './components/AdminModal.vue'
import LoginView from './components/LoginView.vue'
import Toasts from './components/Toasts.vue'
import { useChat } from './composables/useChat.js'
import { useAuth } from './composables/useAuth.js'
import { useBoard } from './composables/useBoard.js'

const { isAuthed, isAdmin, state: auth, logout } = useAuth()
const { conversations, activeId, active, messages, sending, newConversation, selectConversation, deleteConversation, renameConversation, send, stop } = useChat()
const { items: boardItems } = useBoard()
const showKb = ref(false)
const showBoard = ref(false)
const showSide = ref(false)
const showSettings = ref(false)
const showAdmin = ref(false)
const showPrices = ref(false)

function onAsk(q) { if (!activeId.value) newConversation(); send(q) }
function onSelect(id) { selectConversation(id); showSide.value = false }
function onNew() { newConversation(); showSide.value = false }

const title = computed(() => (messages.value.length ? (active.value?.title || '对话') : '命令中心'))
const subtitle = computed(() => (messages.value.length ? `${messages.value.filter((m) => m.role === 'user').length} 轮提问` : ''))
const lastQuestion = computed(() => {
  for (let i = messages.value.length - 1; i >= 0; i--) if (messages.value[i].role === 'user') return messages.value[i].content
  return ''
})

// ⌘K 新建对话
function onKey(e) {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault(); if (isAuthed.value && !sending.value) newConversation()
  }
}
onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <LoginView v-if="!isAuthed" />

  <div v-else class="app">
    <Sidebar :class="{ 'side-open': showSide }"
      :conversations="conversations" :activeId="activeId" :user="auth.user" :boardCount="boardItems.length" :isAdmin="isAdmin"
      @new="onNew" @select="onSelect" @delete="deleteConversation" @rename="renameConversation"
      @open-kb="showKb = true" @open-board="showBoard = true" @open-prices="showPrices = true" @logout="logout"
      @open-settings="showSettings = true" @open-admin="showAdmin = true" />
    <div v-if="showSide" class="side-mask" @click="showSide = false"></div>

    <main class="main">
      <TopBar :title="title" :subtitle="subtitle" @toggle-side="showSide = !showSide" />

      <CommandCenter v-if="!messages.length" class="content scroll" @ask="onAsk" />

      <template v-else>
        <MessageList class="content" :messages="messages" @ask="onAsk" />
        <div class="dock">
          <QuickSuggest :messages="messages" @ask="onAsk" />
          <Composer :sending="sending" :lastQuestion="lastQuestion" @send="onAsk" @stop="stop" />
        </div>
      </template>
    </main>

    <KnowledgeBaseModal v-if="showKb" @close="showKb = false" />
    <BoardModal v-if="showBoard" @close="showBoard = false" @ask="(q) => { showBoard = false; onAsk(q) }" />
    <PriceModal v-if="showPrices" @close="showPrices = false" @ask="(q) => { showPrices = false; onAsk(q) }" />
    <SettingsModal v-if="showSettings" @close="showSettings = false" />
    <AdminModal v-if="showAdmin" @close="showAdmin = false" />
  </div>

  <Toasts />
</template>

<style scoped>
.app { display: flex; height: 100%; background: var(--bg-subtle); }
.main { flex: 1; display: flex; flex-direction: column; min-width: 0; background: var(--bg-subtle); }
.content { flex: 1; min-height: 0; }
.scroll { overflow-y: auto; }
.dock { flex: none; }
.side-mask { display: none; }

@media (max-width: 860px) {
  .app :deep(.sidebar) { position: fixed; left: 0; top: 0; bottom: 0; z-index: 60; transform: translateX(-100%); transition: transform .18s ease; box-shadow: var(--sh-lg); }
  .app :deep(.sidebar.side-open) { transform: translateX(0); }
  .side-mask { display: block; position: fixed; inset: 0; z-index: 50; background: rgba(17,17,17,.28); backdrop-filter: blur(2px); }
}
</style>
