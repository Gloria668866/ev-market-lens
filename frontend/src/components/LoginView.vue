<script setup>
import { ref } from 'vue'
import { useAuth } from '@/composables/useAuth.js'
import LogoMark from './LogoMark.vue'

const { login, register, state } = useAuth()
const mode = ref('login')
const form = ref({ username: '', password: '', nickname: '' })
const busy = ref(false)
async function submit() {
  busy.value = true
  const fn = mode.value === 'login' ? login : register
  await fn({ ...form.value })
  busy.value = false
}

const STATS = [
  { v: '409', l: '车系' },
  { v: '101', l: '品牌' },
  { v: '8,072', l: '销量记录' },
  { v: '29', l: '个月跨度' },
]

const PILLS = ['Text2SQL', 'RAG 知识库', 'LangGraph 编排', '带引用溯源', '自校验重试']
</script>

<template>
  <div class="login">

    <!-- ─── 左侧：英雄图 + 品牌信息 ─── -->
    <div class="hero-side">
      <img src="/images/login-hero.png" alt="" class="hero-bg" />
      <div class="hero-scrim" />

      <div class="hero-content">
        <!-- 顶部品牌 -->
        <div class="hero-logo">
          <LogoMark :size="32" tone="light" />
          <span class="hero-brand-name">车市镜</span>
          <span class="hero-badge">Beta</span>
        </div>

        <!-- 中间主文案 -->
        <div class="hero-copy">
          <p class="hero-eyebrow">新能源车市情报终端</p>
          <h2 class="hero-h">查数据，<br/>读研报，<br/><em>一个对话框。</em></h2>
          <p class="hero-desc">双脑 Agent 自动路由意图——查销量出图表，或读上传研报给带引用答案。</p>
        </div>

        <!-- 数据统计 -->
        <div class="hero-stats">
          <div v-for="s in STATS" :key="s.l" class="stat">
            <span class="stat-v">{{ s.v }}</span>
            <span class="stat-l">{{ s.l }}</span>
          </div>
        </div>

        <!-- 能力标签 -->
        <div class="hero-pills">
          <span v-for="p in PILLS" :key="p" class="pill">{{ p }}</span>
        </div>
      </div>
    </div>

    <!-- ─── 右侧：深色表单区 ─── -->
    <div class="form-side">
      <div class="form-wrap">

        <div class="form-header">
          <div class="form-logo-sm">
            <LogoMark :size="28" tone="brand" />
          </div>
          <div>
            <h1 class="form-title">{{ mode === 'login' ? '欢迎回来' : '创建账号' }}</h1>
            <p class="form-sub">EV-MARKETLENS · 新能源车市情报</p>
          </div>
        </div>

        <!-- Tab 切换 -->
        <div class="tabs">
          <button type="button" :class="{ on: mode === 'login' }" @click="mode = 'login'">登录</button>
          <button type="button" :class="{ on: mode === 'register' }" @click="mode = 'register'">注册</button>
        </div>

        <form @submit.prevent="submit">
          <div v-if="state.error" class="err">
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
              <circle cx="8" cy="8" r="7" stroke="currentColor" stroke-width="1.5"/>
              <path d="M8 5v3.5M8 11h.01" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
            </svg>
            {{ state.error }}
          </div>

          <label class="field">
            <span class="field-label">用户名</span>
            <input v-model="form.username" placeholder="输入用户名" required autocomplete="username" />
          </label>
          <label class="field">
            <span class="field-label">密码</span>
            <input v-model="form.password" type="password" placeholder="输入密码"
                   required :autocomplete="mode === 'login' ? 'current-password' : 'new-password'" />
          </label>
          <label v-if="mode === 'register'" class="field">
            <span class="field-label">昵称 <span class="opt">选填</span></span>
            <input v-model="form.nickname" placeholder="如何称呼你" />
          </label>

          <button class="submit-btn" :disabled="busy">
            <span v-if="busy" class="spinner" />
            <span v-else>{{ mode === 'login' ? '进入工作台' : '创建账号' }}</span>
            <svg v-if="!busy" width="14" height="14" viewBox="0 0 16 16" fill="none">
              <path d="M3 8h9M9 4l4 4-4 4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </button>
        </form>

        <p class="form-footer">
          覆盖 101 品牌 · 409 车系 · 8,072 条市场数据
        </p>
      </div>
    </div>

  </div>
</template>

<style scoped>
/* ── 深色系专属变量 ── */
.login {
  --dk-bg:      #080d18;
  --dk-surface: #0f1629;
  --dk-border:  rgba(255,255,255,.08);
  --dk-text:    #f0f2f8;
  --dk-muted:   rgba(240,242,248,.5);
  --dk-faint:   rgba(240,242,248,.28);
  --dk-input:   rgba(255,255,255,.05);
  --dk-input-focus: rgba(220,38,38,.18);
  --red:        #dc2626;
  --red-hover:  #b91c1c;
}

/* ── 整体：全深色 ── */
.login {
  height: 100%;
  display: flex;
  overflow: hidden;
  background: var(--dk-bg);
}

/* ═══════════════════════════════
   左侧：英雄图区
═══════════════════════════════ */
.hero-side {
  position: relative;
  flex: 1;
  overflow: hidden;
  display: none;
}
@media (min-width: 860px) { .hero-side { display: flex; flex-direction: column; } }

.hero-bg {
  position: absolute; inset: 0;
  width: 100%; height: 100%;
  object-fit: cover; object-position: center top;
}
.hero-scrim {
  position: absolute; inset: 0;
  background:
    linear-gradient(to right,  transparent 60%, var(--dk-bg) 100%),
    linear-gradient(to bottom, rgba(8,13,24,.2) 0%, rgba(8,13,24,.75) 100%);
}

.hero-content {
  position: relative; z-index: 1;
  height: 100%;
  display: flex; flex-direction: column; justify-content: space-between;
  padding: 40px 44px;
}

/* Logo 顶部 */
.hero-logo {
  display: flex; align-items: center; gap: 10px;
}
.hero-brand-name {
  font-family: var(--font-display); font-size: 20px; font-weight: 800;
  color: var(--dk-text); letter-spacing: .03em;
}
.hero-badge {
  font-family: var(--font-mono); font-size: 10px; font-weight: 700;
  letter-spacing: .1em; text-transform: uppercase;
  background: rgba(220,38,38,.2); color: var(--red);
  border: 1px solid rgba(220,38,38,.3); border-radius: 4px;
  padding: 2px 7px;
}

/* 主文案 */
.hero-copy { margin-top: auto; }
.hero-eyebrow {
  font-family: var(--font-mono); font-size: 11px; font-weight: 600;
  letter-spacing: .2em; text-transform: uppercase;
  color: var(--red); margin: 0 0 16px;
  display: flex; align-items: center; gap: 8px;
}
.hero-eyebrow::before { content: ''; width: 24px; height: 1px; background: var(--red); }
.hero-h {
  font-family: var(--font-display);
  font-size: clamp(32px, 3.8vw, 46px);
  font-weight: 800; line-height: 1.1;
  letter-spacing: -.02em;
  color: var(--dk-text); margin: 0 0 16px;
}
.hero-h em { font-style: normal; color: var(--red); }
.hero-desc {
  font-size: 15px; line-height: 1.7;
  color: var(--dk-muted); max-width: 420px; margin: 0;
}

/* 数据统计 */
.hero-stats {
  display: flex; gap: 32px; margin-top: 36px;
  padding-top: 28px; border-top: 1px solid var(--dk-border);
}
.stat { display: flex; flex-direction: column; gap: 4px; }
.stat-v {
  font-family: var(--font-mono); font-size: 22px; font-weight: 700;
  color: var(--dk-text); letter-spacing: -.02em;
}
.stat-l { font-size: 12px; color: var(--dk-faint); }

/* 能力标签 */
.hero-pills {
  display: flex; flex-wrap: wrap; gap: 8px; margin-top: 20px;
}
.pill {
  font-family: var(--font-mono); font-size: 11px; font-weight: 500;
  letter-spacing: .04em;
  background: rgba(255,255,255,.06);
  border: 1px solid var(--dk-border);
  color: var(--dk-faint);
  border-radius: 20px; padding: 4px 12px;
  white-space: nowrap;
}

/* ═══════════════════════════════
   右侧：深色表单区
═══════════════════════════════ */
.form-side {
  flex: none; width: 100%;
  display: flex; align-items: center; justify-content: center;
  background: var(--dk-surface);
  border-left: 1px solid var(--dk-border);
  overflow-y: auto; padding: 32px 24px;
}
@media (min-width: 860px) { .form-side { width: 420px; } }

.form-wrap {
  width: 100%; max-width: 340px;
  animation: fadeUp .4s ease both;
}

/* 表单顶部 */
.form-header {
  display: flex; align-items: center; gap: 14px;
  margin-bottom: 32px;
}
.form-logo-sm {
  width: 48px; height: 48px; border-radius: 14px; flex: none;
  background: rgba(220,38,38,.1); border: 1px solid rgba(220,38,38,.2);
  display: flex; align-items: center; justify-content: center;
}
.form-title {
  font-family: var(--font-display); font-size: 22px; font-weight: 800;
  color: var(--dk-text); margin: 0 0 4px; letter-spacing: -.01em;
}
.form-sub {
  font-family: var(--font-mono); font-size: 10px; font-weight: 500;
  letter-spacing: .1em; text-transform: uppercase;
  color: var(--dk-faint); margin: 0;
}

/* Tab 切换 */
.tabs {
  display: flex; gap: 2px;
  background: rgba(255,255,255,.04);
  border: 1px solid var(--dk-border);
  border-radius: 10px; padding: 3px; margin-bottom: 24px;
}
.tabs button {
  flex: 1; padding: 9px; font-size: 13.5px; font-weight: 600;
  color: var(--dk-faint); border-radius: 8px;
  transition: background .15s, color .15s;
}
.tabs button.on {
  background: rgba(255,255,255,.08);
  color: var(--dk-text);
  box-shadow: 0 1px 3px rgba(0,0,0,.3);
}

/* 错误提示 */
.err {
  display: flex; align-items: center; gap: 8px;
  font-size: 13px; color: #fca5a5;
  background: rgba(220,38,38,.12); border: 1px solid rgba(220,38,38,.2);
  padding: 10px 14px; border-radius: 8px; margin-bottom: 16px;
}

/* 输入字段 */
.field { display: block; margin-bottom: 16px; }
.field-label {
  display: flex; align-items: center; gap: 6px;
  font-family: var(--font-mono); font-size: 10.5px; font-weight: 600;
  letter-spacing: .08em; text-transform: uppercase;
  color: var(--dk-faint); margin-bottom: 7px;
}
.opt {
  font-size: 9px; font-weight: 500; letter-spacing: .04em;
  background: rgba(255,255,255,.06); color: var(--dk-faint);
  border-radius: 4px; padding: 1px 6px; text-transform: none;
}
.field input {
  width: 100%; padding: 12px 14px; font-size: 14px;
  background: var(--dk-input);
  border: 1px solid var(--dk-border);
  border-radius: 9px; outline: none;
  color: var(--dk-text);
  transition: border-color .15s, background .15s, box-shadow .15s;
  box-sizing: border-box;
}
.field input::placeholder { color: var(--dk-faint); }
.field input:focus {
  border-color: var(--red);
  background: var(--dk-input-focus);
  box-shadow: 0 0 0 3px rgba(220,38,38,.15);
}

/* CTA 按钮 */
.submit-btn {
  width: 100%; margin-top: 8px;
  display: flex; align-items: center; justify-content: center; gap: 8px;
  padding: 13px 20px; font-size: 14.5px; font-weight: 700;
  color: #fff; background: var(--red);
  border-radius: 10px;
  transition: background .15s, transform .1s, box-shadow .15s;
  box-shadow: 0 4px 14px rgba(220,38,38,.35);
}
.submit-btn:hover:not(:disabled) {
  background: var(--red-hover);
  transform: translateY(-1px);
  box-shadow: 0 6px 20px rgba(220,38,38,.45);
}
.submit-btn:active:not(:disabled) { transform: translateY(0); }
.submit-btn:disabled { opacity: .45; cursor: not-allowed; box-shadow: none; }

/* Loading spinner */
.spinner {
  width: 16px; height: 16px;
  border: 2px solid rgba(255,255,255,.3);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin .7s linear infinite;
}

/* 底部 */
.form-footer {
  text-align: center; margin-top: 24px;
  font-family: var(--font-mono); font-size: 10.5px;
  color: var(--dk-faint); letter-spacing: .04em;
  border-top: 1px solid var(--dk-border); padding-top: 20px;
}
</style>
