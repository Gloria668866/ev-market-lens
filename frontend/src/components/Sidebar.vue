<script setup>
// 侧栏：品牌 · 新对话(⌘K) · 搜索 · 会话列表(按时间分组) · 收藏看板 · 知识库 · 用户。
import { ref, computed } from 'vue'
import LogoMark from './LogoMark.vue'

const props = defineProps({
  conversations: Array,
  activeId: [String, Number, null],
  user: Object,
  boardCount: { type: Number, default: 0 },
  isAdmin: { type: Boolean, default: false },
})
const emit = defineEmits(['new', 'select', 'open-kb', 'open-board', 'open-prices', 'delete', 'rename', 'logout', 'open-settings', 'open-admin'])

const kw = ref('')
const filtered = computed(() => {
  const k = kw.value.trim().toLowerCase()
  return k ? props.conversations.filter((c) => (c.title || '').toLowerCase().includes(k)) : props.conversations
})

// 会话按时间分组：今天 / 近 7 天 / 更早（createdAt 可能是 ms 或 ISO）
function ts(c) { const t = c.createdAt; if (t == null) return 0; const n = typeof t === 'number' ? t : Date.parse(t); return isNaN(n) ? 0 : n }
const groups = computed(() => {
  const now = new Date(); const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const week = startToday - 6 * 864e5
  const g = { today: [], week: [], earlier: [] }
  for (const c of filtered.value) { const t = ts(c); if (t >= startToday) g.today.push(c); else if (t >= week) g.week.push(c); else g.earlier.push(c) }
  return [
    { key: 'today', label: '今天', items: g.today },
    { key: 'week', label: '近 7 天', items: g.week },
    { key: 'earlier', label: '更早', items: g.earlier },
  ].filter((s) => s.items.length)
})

const initial = computed(() => (props.user?.nickname || props.user?.username || 'U').slice(0, 1).toUpperCase())
const menuOpen = ref(false)

const renamingId = ref(null); const renameValue = ref('')
function startRename(c) { renamingId.value = c.id; renameValue.value = c.title || '' }
function finishRename(id) { const v = renameValue.value.trim(); if (v) emit('rename', { id, title: v }); renamingId.value = null }
</script>

<template>
  <aside class="sidebar">
    <div class="brand">
      <LogoMark :size="26" tone="brand" />
      <span class="name">车<b>市</b>镜</span>
    </div>

    <button class="new-btn" @click="emit('new')">
      <svg width="14" height="14" viewBox="0 0 16 16" fill="none"><path d="M8 3v10M3 8h10" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
      新对话 <span class="k">⌘K</span>
    </button>

    <div class="search">
      <svg width="13" height="13" viewBox="0 0 16 16" fill="none"><circle cx="7" cy="7" r="5" stroke="currentColor" stroke-width="1.5"/><path d="M11 11l3 3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
      <input v-model="kw" placeholder="搜索对话…" />
    </div>

    <nav class="list">
      <p v-if="!conversations.length" class="empty">还没有对话<br/><span>问点什么开始吧</span></p>
      <template v-for="sec in groups" :key="sec.key">
        <div class="grp">{{ sec.label }}</div>
        <div v-for="c in sec.items" :key="c.id" class="conv" :class="{ active: c.id === activeId }"
          @click="emit('select', c.id)" @dblclick.stop="startRename(c)">
          <span class="dot"></span>
          <input v-if="renamingId === c.id" class="rename" v-model="renameValue"
            @keyup.enter="finishRename(c.id)" @keyup.escape="renamingId = null" @blur="finishRename(c.id)" @click.stop />
          <span v-else class="t">{{ c.title || '未命名会话' }}</span>
          <button class="del" title="删除" @click.stop="emit('delete', c.id)">
            <svg width="13" height="13" viewBox="0 0 16 16" fill="none"><path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
          </button>
        </div>
      </template>
    </nav>

    <div class="links">
      <button class="side-link" @click="emit('open-board')">
        <span class="star">★</span> 收藏看板 <span v-if="boardCount" class="badge">{{ boardCount }}</span>
      </button>
      <button class="side-link" @click="emit('open-prices')">
        <svg width="15" height="15" viewBox="0 0 16 16" fill="none"><path d="M2.5 2.5h5l6 6-5 5-6-6z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/><circle cx="5.3" cy="5.3" r="1" fill="currentColor"/></svg>
        车型报价
      </button>
      <button class="side-link" @click="emit('open-kb')">
        <svg width="15" height="15" viewBox="0 0 16 16" fill="none"><path d="M3 2.5h7l3 3V13.5H3z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/><path d="M9.5 2.5V6h3.5" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/></svg>
        知识库
      </button>
      <button v-if="isAdmin" class="side-link admin" @click="emit('open-admin')">
        <svg width="15" height="15" viewBox="0 0 16 16" fill="none"><circle cx="8" cy="8" r="2.2" stroke="currentColor" stroke-width="1.3"/><path d="M8 1.5v2M8 12.5v2M1.5 8h2M12.5 8h2M3.4 3.4l1.4 1.4M11.2 11.2l1.4 1.4M12.6 3.4l-1.4 1.4M4.8 11.2l-1.4 1.4" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>
        管理后台 <span class="tag-admin">ADMIN</span>
      </button>
    </div>

    <div class="foot" @click="menuOpen = !menuOpen">
      <span class="avatar">{{ initial }}</span>
      <span class="u"><b>{{ user?.nickname || user?.username }}</b><small>已登录</small></span>
      <svg class="caret" :class="{ up: menuOpen }" width="13" height="13" viewBox="0 0 16 16" fill="none"><path d="M4 10l4-4 4 4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
      <div v-if="menuOpen" class="menu" @click.stop>
        <button class="mi" @click="emit('open-settings'); menuOpen = false">账户设置</button>
        <button class="mi danger" @click="emit('logout'); menuOpen = false">退出登录</button>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.sidebar { width: var(--sidebar-w); flex: none; height: 100%; display: flex; flex-direction: column; background: var(--bg); border-right: 1px solid var(--line); padding: 14px 12px; }
.brand { display: flex; align-items: center; gap: 10px; padding: 6px 8px 14px; }
.brand .name { font-family: var(--font-display); font-size: 17px; font-weight: 800; letter-spacing: .01em; color: var(--ink); }
.brand .name b { color: var(--accent); }

.new-btn { display: flex; align-items: center; gap: 8px; width: 100%; padding: 10px 12px; font-size: 13.5px; font-weight: 700; color: #fff; background: var(--accent); border-radius: var(--r-sm); box-shadow: 0 1px 2px rgba(220,38,38,.32); transition: background .15s; }
.new-btn:hover { background: var(--accent-press); }
.new-btn .k { margin-left: auto; font-family: var(--font-mono); font-size: 10.5px; font-weight: 600; opacity: .8; background: rgba(255,255,255,.18); padding: 1px 6px; border-radius: 5px; }

.search { margin: 14px 2px 4px; position: relative; }
.search svg { position: absolute; left: 9px; top: 50%; transform: translateY(-50%); color: var(--ink-3); }
.search input { width: 100%; padding: 8px 10px 8px 30px; font-size: 12.5px; background: var(--bg-sunken); border: 1px solid transparent; border-radius: var(--r-sm); outline: none; transition: .15s; }
.search input:focus { border-color: var(--line-strong); background: var(--bg); }
.search input::placeholder { color: var(--ink-3); }

.grp { font-family: var(--font-mono); font-size: 10px; font-weight: 600; letter-spacing: .12em; color: var(--ink-3); text-transform: uppercase; margin: 16px 8px 6px; }
.list { flex: 1; overflow-y: auto; margin: 4px -4px 0; padding: 0 4px; }
.empty { font-size: 13px; color: var(--ink-3); padding: 16px 10px; line-height: 1.7; }
.empty span { font-size: 12px; color: var(--ink-4); }

.conv { display: flex; align-items: center; gap: 9px; padding: 8px 10px; font-size: 13px; color: var(--ink-2); border-radius: var(--r-sm); cursor: pointer; transition: background .12s, color .12s; }
.conv:hover { background: var(--bg-subtle); }
.conv.active { background: var(--accent-wash); color: var(--ink); font-weight: 600; }
.conv .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--ink-4); flex: none; }
.conv.active .dot { background: var(--accent); }
.conv .t { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rename { flex: 1; font-size: 12.5px; padding: 2px 6px; border: 1px solid var(--accent); border-radius: 6px; outline: none; font-family: inherit; background: var(--bg); }
.del { flex: none; width: 20px; height: 20px; display: flex; align-items: center; justify-content: center; border-radius: 5px; color: var(--ink-3); opacity: 0; transition: opacity .12s, background .12s, color .12s; }
.conv:hover .del { opacity: 1; }
.del:hover { background: var(--accent-wash); color: var(--accent); }

.links { border-top: 1px solid var(--line); margin-top: 8px; padding-top: 8px; }
.side-link { display: flex; align-items: center; gap: 9px; width: 100%; padding: 9px 10px; font-size: 13px; font-weight: 600; color: var(--ink-2); border-radius: var(--r-sm); transition: background .12s, color .12s; }
.side-link:hover { background: var(--bg-subtle); color: var(--ink); }
.side-link .star { color: var(--accent); font-size: 13px; }
.side-link .badge { margin-left: auto; font-family: var(--font-mono); font-size: 10.5px; color: var(--ink-3); background: var(--bg-sunken); padding: 1px 7px; border-radius: 6px; }

.foot { position: relative; display: flex; align-items: center; gap: 9px; margin-top: 6px; padding: 8px 10px; border-radius: var(--r-sm); cursor: pointer; transition: background .12s; }
.foot:hover { background: var(--bg-subtle); }
.avatar { flex: none; width: 30px; height: 30px; border-radius: 9px; display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 12px; color: #fff; background: linear-gradient(140deg, var(--accent), var(--accent-press)); }
.foot .u { display: flex; flex-direction: column; line-height: 1.3; min-width: 0; }
.foot .u b { font-size: 12.5px; font-weight: 600; color: var(--ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.foot .u small { font-family: var(--font-mono); font-size: 9.5px; color: var(--ink-3); letter-spacing: .04em; }
.caret { margin-left: auto; color: var(--ink-3); transition: transform .15s; }
.caret.up { transform: rotate(180deg); }
.menu { position: absolute; left: 10px; right: 10px; bottom: calc(100% + 6px); background: var(--bg); border: 1px solid var(--line); border-radius: var(--r-md); box-shadow: var(--sh-md); padding: 5px; z-index: 30; }
.mi { width: 100%; text-align: left; padding: 8px 11px; font-size: 13px; color: var(--ink-2); border-radius: 7px; }
.mi:hover { background: var(--bg-subtle); color: var(--ink); }
.mi.danger:hover { background: var(--down-wash); color: var(--down); }
.side-link.admin .tag-admin { margin-left: auto; font-family: var(--font-mono); font-size: 9px; font-weight: 700; letter-spacing: .08em; color: var(--accent); background: var(--accent-wash); border: 1px solid var(--accent-border); padding: 1px 6px; border-radius: 5px; }
.side-link.admin .star, .side-link.admin svg { color: var(--accent); }
</style>
