<script setup>
// 账户设置：用量概览 + 改昵称 + 改密码。重度用户的自助面板。
import { ref, onMounted, computed } from 'vue'
import { useAuth } from '@/composables/useAuth.js'
import { useToast } from '@/composables/useToast.js'
import { updateNickname, changePassword, myStats } from '@/api/account.js'

const emit = defineEmits(['close'])
const { state, isAdmin, setUser } = useAuth()
const { ok, err } = useToast()

const nickname = ref(state.user?.nickname || '')
const stats = ref(null)
const pwd = ref({ old: '', neo: '', confirm: '' })
const busyN = ref(false); const busyP = ref(false)

const initial = computed(() => (state.user?.nickname || state.user?.username || 'U').slice(0, 1).toUpperCase())

onMounted(async () => { try { stats.value = await myStats() } catch {} })

async function saveNick() {
  const v = nickname.value.trim()
  if (!v) { err('昵称不能为空'); return }
  busyN.value = true
  try { const u = await updateNickname(v); setUser({ nickname: u.nickname }); ok('昵称已更新') }
  catch (e) { err(e.message || '更新失败') } finally { busyN.value = false }
}
async function savePwd() {
  if (pwd.value.neo.length < 6) { err('新密码至少 6 位'); return }
  if (pwd.value.neo !== pwd.value.confirm) { err('两次新密码不一致'); return }
  busyP.value = true
  try { await changePassword(pwd.value.old, pwd.value.neo); pwd.value = { old: '', neo: '', confirm: '' }; ok('密码已修改') }
  catch (e) { err(e.message || '修改失败') } finally { busyP.value = false }
}
</script>

<template>
  <div class="mask" @click.self="emit('close')">
    <div class="modal">
      <header>
        <div class="who">
          <span class="avatar">{{ initial }}</span>
          <div>
            <h3>{{ state.user?.nickname }} <span v-if="isAdmin" class="role">管理员</span></h3>
            <p class="sub mono">@{{ state.user?.username }}</p>
          </div>
        </div>
        <button class="x" @click="emit('close')">✕</button>
      </header>

      <div class="body">
        <div class="sec-lbl mono">我的用量</div>
        <div class="stats">
          <div class="st"><div class="v mono">{{ stats?.conversations ?? '—' }}</div><div class="k">会话</div></div>
          <div class="st"><div class="v mono">{{ stats?.questions ?? '—' }}</div><div class="k">提问</div></div>
          <div class="st"><div class="v mono">{{ stats?.insights ?? '—' }}</div><div class="k">收藏</div></div>
        </div>

        <div class="sec-lbl mono">资料</div>
        <label class="field"><span>昵称</span>
          <div class="row"><input v-model="nickname" maxlength="32" /><button class="btn" :disabled="busyN" @click="saveNick">保存</button></div>
        </label>

        <div class="sec-lbl mono">修改密码</div>
        <label class="field"><span>原密码</span><input v-model="pwd.old" type="password" autocomplete="current-password" /></label>
        <label class="field"><span>新密码</span><input v-model="pwd.neo" type="password" autocomplete="new-password" placeholder="至少 6 位" /></label>
        <label class="field"><span>确认新密码</span><input v-model="pwd.confirm" type="password" autocomplete="new-password" /></label>
        <button class="btn primary" :disabled="busyP" @click="savePwd">更新密码</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.mask { position: fixed; inset: 0; background: rgba(17,17,17,.32); backdrop-filter: blur(4px); display: flex; align-items: center; justify-content: center; z-index: 60; animation: fadeIn .18s ease; padding: 20px; }
.modal { width: min(460px, 96vw); max-height: 88vh; background: var(--bg); border: 1px solid var(--line); border-radius: var(--r-lg); box-shadow: var(--sh-lg); display: flex; flex-direction: column; overflow: hidden; animation: fadeUp .22s ease; }
header { display: flex; align-items: center; padding: 20px 22px; border-bottom: 1px solid var(--line); }
.who { display: flex; align-items: center; gap: 12px; }
.avatar { width: 42px; height: 42px; border-radius: 12px; display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 16px; color: #fff; background: linear-gradient(140deg, var(--accent), var(--accent-press)); }
h3 { margin: 0; font-family: var(--font-display); font-size: 17px; font-weight: 700; color: var(--ink); display: flex; align-items: center; gap: 8px; }
.role { font-size: 10.5px; font-weight: 700; color: var(--accent); background: var(--accent-wash); border: 1px solid var(--accent-border); padding: 1px 8px; border-radius: 999px; }
.sub { margin: 3px 0 0; font-size: 11.5px; color: var(--ink-3); }
.x { margin-left: auto; width: 30px; height: 30px; border-radius: 8px; color: var(--ink-3); font-size: 15px; }
.x:hover { background: var(--bg-subtle); color: var(--ink); }

.body { padding: 18px 22px 22px; overflow-y: auto; }
.sec-lbl { font-size: 10px; font-weight: 600; letter-spacing: .12em; text-transform: uppercase; color: var(--ink-3); margin: 4px 0 10px; }
.sec-lbl:not(:first-child) { margin-top: 22px; }
.stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.st { background: var(--bg-subtle); border: 1px solid var(--line); border-radius: var(--r-md); padding: 12px; text-align: center; }
.st .v { font-size: 22px; font-weight: 600; color: var(--ink); }
.st .k { font-size: 11.5px; color: var(--ink-3); margin-top: 3px; }

.field { display: block; margin-bottom: 11px; }
.field span { display: block; font-size: 12px; color: var(--ink-2); margin-bottom: 5px; }
.field input { width: 100%; padding: 9px 12px; font-size: 14px; background: var(--bg-subtle); border: 1px solid var(--line); border-radius: var(--r-sm); outline: none; transition: .15s; }
.field input:focus { border-color: var(--accent); background: var(--bg); box-shadow: 0 0 0 3px var(--accent-wash); }
.row { display: flex; gap: 8px; }
.row input { flex: 1; }
.btn { flex: none; font-size: 13px; font-weight: 700; color: var(--ink-2); background: var(--bg); border: 1px solid var(--line-strong); border-radius: var(--r-sm); padding: 8px 16px; transition: .12s; }
.btn:hover:not(:disabled) { border-color: var(--ink-3); color: var(--ink); }
.btn.primary { width: 100%; margin-top: 4px; color: #fff; background: var(--accent); border-color: var(--accent); }
.btn.primary:hover:not(:disabled) { background: var(--accent-press); }
.btn:disabled { opacity: .55; cursor: not-allowed; }
</style>
