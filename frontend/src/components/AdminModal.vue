<script setup>
// 管理员后台：全局概览 + 用户管理（改角色 / 禁用启用 / 重置密码 / 删除）。仅管理员可见。
import { ref, onMounted, computed } from 'vue'
import { useAuth } from '@/composables/useAuth.js'
import { useToast } from '@/composables/useToast.js'
import { listUsers, overview, patchUser, resetPassword, deleteUser } from '@/api/admin.js'

const emit = defineEmits(['close'])
const { state } = useAuth()
const { ok, err } = useToast()

const users = ref([])
const ov = ref(null)
const loading = ref(true)
const meId = computed(() => state.user?.id)

async function refresh() {
  loading.value = true
  try { users.value = await listUsers(); ov.value = await overview() }
  catch (e) { err(e.message || '加载失败') }
  finally { loading.value = false }
}
onMounted(refresh)

async function toggleRole(u) {
  try { await patchUser(u.id, { role: u.role === 'admin' ? 'user' : 'admin' }); ok('角色已更新'); refresh() }
  catch (e) { err(e.message || '操作失败') }
}
async function toggleDisabled(u) {
  try { await patchUser(u.id, { disabled: !u.disabled }); ok(u.disabled ? '已启用' : '已禁用'); refresh() }
  catch (e) { err(e.message || '操作失败') }
}
async function reset(u) {
  const np = window.prompt(`为「${u.nickname || u.username}」设置新密码（至少 6 位）：`)
  if (np == null) return
  try { await resetPassword(u.id, np); ok('密码已重置') }
  catch (e) { err(e.message || '操作失败') }
}
async function remove(u) {
  if (!window.confirm(`删除用户「${u.nickname || u.username}」及其全部数据？此操作不可恢复。`)) return
  try { await deleteUser(u.id); ok('已删除'); refresh() }
  catch (e) { err(e.message || '操作失败') }
}
function fmt(t) { return t ? String(t).slice(0, 10) : '—' }
</script>

<template>
  <div class="mask" @click.self="emit('close')">
    <div class="modal">
      <header>
        <div>
          <h3>⚙ 管理后台</h3>
          <p class="sub">用户管理 · 全局概览</p>
        </div>
        <button class="x" @click="emit('close')">✕</button>
      </header>

      <div class="ov" v-if="ov">
        <div class="ov-card"><div class="v mono">{{ ov.users }}</div><div class="k">用户</div></div>
        <div class="ov-card"><div class="v mono">{{ ov.admins }}</div><div class="k">管理员</div></div>
        <div class="ov-card"><div class="v mono">{{ ov.disabled }}</div><div class="k">已禁用</div></div>
        <div class="ov-card"><div class="v mono">{{ ov.conversations }}</div><div class="k">会话</div></div>
        <div class="ov-card"><div class="v mono">{{ ov.questions }}</div><div class="k">提问</div></div>
        <div class="ov-card"><div class="v mono">{{ ov.insights }}</div><div class="k">收藏</div></div>
      </div>

      <div class="body">
        <p v-if="loading" class="hint">加载中…</p>
        <table v-else class="tbl">
          <thead>
            <tr><th>用户</th><th>角色</th><th>状态</th><th class="num">会话</th><th class="num">提问</th><th class="num">收藏</th><th>注册</th><th class="act-h">操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="u in users" :key="u.id" :class="{ off: u.disabled }">
              <td>
                <div class="u">{{ u.nickname || u.username }}<span v-if="u.id === meId" class="me">你</span></div>
                <div class="un mono">@{{ u.username }}</div>
              </td>
              <td><span class="badge" :class="u.role">{{ u.role === 'admin' ? '管理员' : '用户' }}</span></td>
              <td><span class="dot" :class="u.disabled ? 'red' : 'green'"></span>{{ u.disabled ? '禁用' : '正常' }}</td>
              <td class="num mono">{{ u.conversations }}</td>
              <td class="num mono">{{ u.questions }}</td>
              <td class="num mono">{{ u.insights }}</td>
              <td class="mono dt">{{ fmt(u.created_at) }}</td>
              <td class="acts">
                <button @click="toggleRole(u)">{{ u.role === 'admin' ? '取消管理员' : '设为管理员' }}</button>
                <button v-if="u.id !== meId" @click="toggleDisabled(u)">{{ u.disabled ? '启用' : '禁用' }}</button>
                <button @click="reset(u)">重置密码</button>
                <button v-if="u.id !== meId" class="danger" @click="remove(u)">删除</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<style scoped>
.mask { position: fixed; inset: 0; background: rgba(17,17,17,.32); backdrop-filter: blur(4px); display: flex; align-items: center; justify-content: center; z-index: 60; animation: fadeIn .18s ease; padding: 20px; }
.modal { width: min(960px, 97vw); max-height: 88vh; background: var(--bg); border: 1px solid var(--line); border-radius: var(--r-lg); box-shadow: var(--sh-lg); display: flex; flex-direction: column; overflow: hidden; animation: fadeUp .22s ease; }
header { display: flex; align-items: flex-start; padding: 20px 24px 14px; }
h3 { margin: 0; font-family: var(--font-display); font-size: 19px; font-weight: 700; color: var(--ink); }
.sub { margin: 4px 0 0; font-size: 12.5px; color: var(--ink-3); }
.x { margin-left: auto; width: 30px; height: 30px; border-radius: 8px; color: var(--ink-3); font-size: 15px; }
.x:hover { background: var(--bg-subtle); color: var(--ink); }

.ov { display: grid; grid-template-columns: repeat(6, 1fr); gap: 10px; padding: 0 24px 14px; }
.ov-card { background: var(--bg-subtle); border: 1px solid var(--line); border-radius: var(--r-md); padding: 11px; text-align: center; }
.ov-card .v { font-size: 20px; font-weight: 600; color: var(--ink); }
.ov-card .k { font-size: 11px; color: var(--ink-3); margin-top: 2px; }

.body { padding: 6px 24px 22px; overflow: auto; }
.hint { text-align: center; color: var(--ink-3); padding: 30px 0; }
.tbl { width: 100%; border-collapse: collapse; font-size: 13px; }
.tbl th { text-align: left; font-family: var(--font-mono); font-size: 10px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; color: var(--ink-3); padding: 8px 10px; border-bottom: 1px solid var(--line); white-space: nowrap; }
.tbl th.num { text-align: right; } .tbl th.act-h { text-align: right; }
.tbl td { padding: 10px; border-bottom: 1px solid var(--line-soft); vertical-align: middle; }
.tbl tr.off { opacity: .55; }
.tbl td.num { text-align: right; color: var(--ink-2); }
.u { font-weight: 600; color: var(--ink); display: flex; align-items: center; gap: 6px; }
.me { font-size: 10px; font-weight: 700; color: var(--info); background: var(--info-wash); padding: 0 6px; border-radius: 999px; }
.un { font-size: 11px; color: var(--ink-3); }
.dt { font-size: 11.5px; color: var(--ink-3); }
.badge { font-size: 11px; font-weight: 700; padding: 2px 9px; border-radius: 999px; }
.badge.admin { color: var(--accent); background: var(--accent-wash); }
.badge.user { color: var(--ink-2); background: var(--bg-sunken); }
.dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-right: 5px; vertical-align: middle; }
.dot.green { background: var(--up); } .dot.red { background: var(--down); }
.acts { text-align: right; white-space: nowrap; }
.acts button { font-size: 12px; font-weight: 600; color: var(--ink-2); border: 1px solid var(--line); border-radius: 7px; padding: 4px 9px; margin-left: 5px; transition: .12s; }
.acts button:hover { border-color: var(--accent); color: var(--accent); background: var(--accent-wash); }
.acts button.danger:hover { border-color: var(--down); color: var(--down); background: var(--down-wash); }

@media (max-width: 720px) { .ov { grid-template-columns: repeat(3, 1fr); } }
</style>
