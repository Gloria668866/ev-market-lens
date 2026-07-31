<script setup>
import { ref, computed, nextTick, watch, onMounted } from 'vue'
import { useAuth, isAuthed } from './composables/useAuth.js'
import { useChat } from './composables/useChat.js'
import ChartCard from './components/ChartCard.vue'
import { listDocs } from './api/kb.js'
import { listPrices } from './api/prices.js'

const { state: auth, login, register, logout } = useAuth()
const { conversations, activeId, messages, sending, newConversation, deleteConversation, send, stop, loadHistory } = useChat()

const tab = ref('home')
const TABS = [
  { key: 'home', label: '首页', icon: '⌂' },
  { key: 'explore', label: '探索', icon: '◎' },
  { key: 'chat', label: '对话', icon: '◆' },
  { key: 'kb', label: '知识库', icon: '▤' },
  { key: 'me', label: '我的', icon: '◐' },
]
const INTENT = { sql: ['数据分析', 'sql'], rag: ['知识问答', 'rag'], hybrid: ['综合分析', 'mix'], clarify: ['需要澄清', 'mix'] }

function onAsk(q) { if (!activeId.value) newConversation(); send(q); tab.value = 'chat' }
function onNew() { newConversation(); tab.value = 'chat' }
function pathParts(c) { return (c.heading_path || '').split(/\s*[>›/]\s*/).filter(Boolean) }

onMounted(() => { if (isAuthed.value) { loadHistory(); loadKb() } })

// 知识库
const kbList = ref([]); const kbLoading = ref(false)
async function loadKb() { kbLoading.value = true; try { kbList.value = await listDocs() } catch {} kbLoading.value = false }
watch(tab, (t) => { if (t === 'kb' && !kbList.value.length) loadKb() })

// 探索：品牌 / 报价
const exploreTab = ref('brand')
const priceItems = ref([]); const priceKw = ref(''); const priceLoading = ref(false)
let _pt = null
async function loadPrices() { priceLoading.value = true; try { priceItems.value = (await listPrices({ q: priceKw.value.trim(), limit: 60 })).items } catch {} priceLoading.value = false }
watch(priceKw, () => { clearTimeout(_pt); _pt = setTimeout(loadPrices, 220) })
watch(exploreTab, (t) => { if (t === 'price' && !priceItems.value.length) loadPrices() })

// 登录
const loginMode = ref('login')
const loginForm = ref({ username: '', password: '', nickname: '' })
const busy = ref(false)
async function doAuth() {
  busy.value = true
  if (loginMode.value === 'login') await login(loginForm.value.username, loginForm.value.password)
  else await register(loginForm.value.username, loginForm.value.password, loginForm.value.nickname)
  busy.value = false
  if (isAuthed.value) { loadHistory(); loadKb() }
}

// 对话输入
const inputText = ref(''); const inputEl = ref(null)
function resize() { const el = inputEl.value; if (!el) return; el.style.height = 'auto'; el.style.height = Math.min(el.scrollHeight, 100) + 'px' }
watch(inputText, () => nextTick(resize))
function chatSend() { const q = inputText.value.trim(); if (!q || sending.value) return; onAsk(q); inputText.value = ''; nextTick(resize) }

const initial = computed(() => (auth.user?.nickname || auth.user?.username || 'U').slice(0, 1).toUpperCase())
const isAdmin = computed(() => (auth.user?.role || 'user') === 'admin')
</script>

<template>
  <!-- ===== 登录页 ===== -->
  <div v-if="!isAuthed" class="login-page">
    <div class="login-card">
      <div class="lens"></div>
      <h1 class="login-brand">车<span class="rd">市</span>镜</h1>
      <p class="login-sub mono">EV-MARKETLENS · 新能源车市情报</p>
      <div class="login-tabs">
        <button :class="{ on: loginMode === 'login' }" @click="loginMode = 'login'">登录</button>
        <button :class="{ on: loginMode === 'register' }" @click="loginMode = 'register'">注册</button>
      </div>
      <div v-if="auth.error" class="login-err">{{ auth.error }}</div>
      <input v-model="loginForm.username" class="login-input" placeholder="用户名" />
      <input v-model="loginForm.password" class="login-input" type="password" placeholder="密码" @keyup.enter="doAuth" />
      <input v-if="loginMode === 'register'" v-model="loginForm.nickname" class="login-input" placeholder="昵称（选填）" />
      <button class="login-btn" :disabled="busy" @click="doAuth">{{ busy ? '…' : loginMode === 'login' ? '进入' : '创建账号' }}</button>
      <p class="login-foot mono">双脑 Agent · Text2SQL + RAG</p>
    </div>
  </div>

  <!-- ===== 主界面 ===== -->
  <div v-else class="app">
    <main class="main">
      <!-- 首页 -->
      <div v-if="tab === 'home'" class="page">
        <div class="hd"><div class="overline mono">新能源车市情报 · 双脑 AGENT</div><h1>把提问，<br/>变成<em>市场洞察</em></h1></div>
        <div class="search-bar" @click="tab = 'chat'"><span class="si">⌕</span><span class="sp">搜索品牌、车系或直接提问…</span></div>
        <div class="kpi-row">
          <div class="kpi-item"><b class="mono">409</b><span>车系</span></div>
          <div class="kpi-item"><b class="mono">101</b><span>品牌</span></div>
          <div class="kpi-item"><b class="mono">8,072</b><span>数据</span></div>
        </div>
        <div class="section-title mono">数据脑 · 热门查询</div>
        <div class="hot-grid">
          <button v-for="h in ['2025年纯电销量Top10','比亚迪各车系今年销量','小米SU7和Model 3谁卖得多','增程车型市场占比','新能源月度销量趋势','2025年新上榜车型']" :key="h" class="hot-card" @click="onAsk(h)">{{ h }}<span class="arr">→</span></button>
        </div>
        <div class="section-title mono">知识脑 · 行业解读</div>
        <div class="hot-grid">
          <button v-for="h in ['2025渗透率大概多少','增程和插混的区别','补贴和购置税政策','新能源出口怎么样']" :key="h" class="hot-card rag" @click="onAsk(h)">{{ h }}<span class="arr">→</span></button>
        </div>
      </div>

      <!-- 探索页 -->
      <div v-if="tab === 'explore'" class="page">
        <div class="page-title">探索</div>
        <div class="ex-seg">
          <button :class="{ on: exploreTab === 'brand' }" @click="exploreTab = 'brand'">品牌</button>
          <button :class="{ on: exploreTab === 'price' }" @click="exploreTab = 'price'">车型报价</button>
        </div>

        <template v-if="exploreTab === 'brand'">
          <p class="muted sm">点任意品牌，直接查它的车系销量。</p>
          <div class="brand-grid">
            <button v-for="b in ['比亚迪','特斯拉','理想','蔚来','小鹏','零跑','哪吒','问界','极氪','小米','吉利','长安','奇瑞','长城','五菱','埃安']" :key="b" class="brand-card" @click="onAsk(b+'各车系今年销量')">
              <span class="brand-name">{{ b }}</span><span class="brand-go">销量 →</span>
            </button>
          </div>
        </template>

        <template v-else>
          <div class="price-search">
            <span class="ps-ic">⌕</span>
            <input v-model="priceKw" placeholder="搜索品牌或车系…" />
          </div>
          <p class="muted sm" style="margin:0 2px 10px">懂车帝实采指导价 · 点车型可深入提问</p>
          <p v-if="priceLoading" class="muted sm" style="text-align:center;padding:16px">加载中…</p>
          <div v-else class="price-list">
            <div v-for="it in priceItems" :key="it.brand+it.series" class="price-row" @click="onAsk(`${it.series}的价格和配置怎么样`)">
              <div class="pr-meta">
                <div class="pr-nm">{{ it.series }}<span class="pr-bd">{{ it.brand }}</span></div>
                <div class="pr-tags"><span v-if="it.segment" class="pr-tag">{{ it.segment }}</span><span v-if="it.endurance" class="pr-tag mono">续航{{ it.endurance }}km</span></div>
              </div>
              <div class="pr-price"><span class="pr-pt mono">{{ it.priceText }}</span><span v-if="it.descender>0" class="pr-down mono">↓{{ it.descender }}万</span></div>
            </div>
          </div>
        </template>
      </div>

      <!-- 对话页 -->
      <div v-if="tab === 'chat'" class="page chat-page">
        <div class="chat-top"><span class="chat-title">对话</span><button class="chat-new" @click="onNew()">＋ 新对话</button></div>
        <div class="chat-body">
          <div v-if="!messages.length" class="chat-empty">
            <div class="ce-ic">◆</div>
            <p>问点什么开始</p>
            <span class="sm muted">如「2025纯电销量Top10」「增程和插混区别」</span>
          </div>
          <div v-for="m in messages" :key="m.id" class="msg">
            <div v-if="m.role === 'user'" class="u-row"><div class="u-bubble">{{ m.content }}</div></div>
            <div v-else class="a-row">
              <div class="a-avatar">◈</div>
              <div class="a-body">
                <!-- 思考 / 意图 -->
                <div class="trace">
                  <span class="t-spark">◈</span>
                  <span v-if="m.status === 'thinking'" class="t-txt">Agent 分析中<span class="dots"><i></i><i></i><i></i></span></span>
                  <span v-else class="t-txt mono">AGENT</span>
                  <span v-if="m.intent" class="badge" :class="(INTENT[m.intent]||INTENT.sql)[1]">{{ (INTENT[m.intent]||INTENT.sql)[0] }}<em v-if="m.confidence!=null"> {{ Math.round(m.confidence*100) }}%</em></span>
                </div>
                <!-- 数据图表 -->
                <ChartCard v-if="m.rows.length" :msg="m" />
                <!-- 结论 / 答案 -->
                <div v-if="m.insight" class="a-text">{{ m.insight }}<span v-if="m.status==='streaming'" class="cursor"></span></div>
                <!-- 引用 -->
                <div v-if="m.citations.length" class="cites">
                  <div class="cites-h mono">来源引用 · {{ m.citations.length }}</div>
                  <div v-for="(c,i) in m.citations" :key="c.chunk_id||i" class="cite">
                    <span class="c-idx mono">{{ String(i+1).padStart(2,'0') }}</span>
                    <span class="c-meta">
                      <span class="c-doc">{{ c.title || ('文档 #'+c.doc_id) }}</span>
                      <span v-if="c.heading_path" class="c-path">
                        <span v-for="(seg,k) in pathParts(c)" :key="k" class="c-seg mono">{{ seg }}</span>
                      </span>
                    </span>
                    <span class="c-pg mono">P{{ c.page_no }}</span>
                  </div>
                </div>
                <div v-if="m.status === 'error'" class="a-err">{{ m.error?.message || '出错了，换个问法试试' }}</div>
              </div>
            </div>
          </div>
        </div>
        <div class="chat-input-bar">
          <textarea ref="inputEl" v-model="inputText" rows="1" placeholder="问点什么…" @keydown.enter.exact.prevent="chatSend" />
          <button v-if="!sending" class="chat-send" :disabled="!inputText.trim()" @click="chatSend">发送</button>
          <button v-else class="chat-send stop" @click="stop()">■</button>
        </div>
      </div>

      <!-- 知识库页 -->
      <div v-if="tab === 'kb'" class="page">
        <div class="page-title">知识库</div>
        <p class="muted sm">公共知识库已就绪，可直接就这些文档提问（去「对话」问行业问题即走 RAG 带引用）。</p>
        <p v-if="kbLoading" class="muted sm" style="text-align:center;padding:20px">加载中…</p>
        <div v-else class="kb-list">
          <div v-for="d in kbList" :key="d.docId" class="kb-doc">
            <span class="kb-ft mono">{{ (d.fileType||'md').toUpperCase() }}</span>
            <div class="kb-meta"><span class="kb-title">{{ d.title }}</span><span class="kb-sub mono">{{ d.chunkCount }} 切片 · {{ d.createdAt }}</span></div>
            <span class="kb-ok">已就绪</span>
          </div>
        </div>
        <button class="kb-ask" @click="onAsk('2025渗透率大概多少')">就知识库提问 →</button>
      </div>

      <!-- 我的 -->
      <div v-if="tab === 'me'" class="page">
        <div class="me-card">
          <span class="me-avatar">{{ initial }}</span>
          <div class="me-id"><b>{{ auth.user?.nickname || auth.user?.username }}<span v-if="isAdmin" class="me-role">管理员</span></b><span class="mono">@{{ auth.user?.username }}</span></div>
        </div>
        <div class="me-stats">
          <div class="ms"><b class="mono">{{ conversations.length }}</b><span>会话</span></div>
          <div class="ms"><b class="mono">{{ kbList.length }}</b><span>知识库</span></div>
          <div class="ms"><b class="mono">双脑</b><span>Agent</span></div>
        </div>
        <p class="muted sm" style="margin:18px 4px 8px">车市镜 · 新能源车市情报 Agent。数据脑 Text2SQL 查库出图，知识脑 RAG 读研报带引用。{{ isAdmin ? '管理后台请用桌面端。' : '' }}</p>
        <button class="logout-btn" @click="logout">退出登录</button>
      </div>
    </main>

    <nav class="tabs">
      <button v-for="t in TABS" :key="t.key" :class="{ active: tab === t.key }" @click="tab = t.key">
        <span class="tab-icon">{{ t.icon }}</span><span class="tab-label">{{ t.label }}</span>
      </button>
    </nav>
  </div>
</template>

<style scoped>
.app { height: 100%; display: flex; flex-direction: column; background: var(--bg-subtle); }
.main { flex: 1; overflow-y: auto; -webkit-overflow-scrolling: touch; }
.page { min-height: 100%; padding: 18px 16px 16px; animation: fadeUp .22s ease both; }
.muted { color: var(--ink-3); } .sm { font-size: 12.5px; line-height: 1.6; }

/* 底部导航 */
.tabs { flex: none; display: flex; background: var(--bg); border-top: 1px solid var(--line); padding: 5px 0 env(safe-area-inset-bottom); }
.tabs button { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 3px; padding: 6px 2px; color: var(--ink-3); }
.tabs button.active { color: var(--accent); }
.tab-icon { font-size: 17px; line-height: 1; }
.tab-label { font-size: 10px; font-weight: 600; }

/* 登录 */
.login-page { height: 100%; display: flex; align-items: center; justify-content: center; padding: 24px; background:
  radial-gradient(circle at 50% 28%, rgba(220,38,38,.08), transparent 60%), var(--bg-subtle); }
.login-card { width: 100%; max-width: 340px; text-align: center; }
.lens { width: 48px; height: 48px; margin: 0 auto 14px; border-radius: 50%; border: 3px solid var(--accent); position: relative; }
.lens::after { content: ''; position: absolute; inset: 9px; transform: rotate(45deg); background: var(--accent); border-radius: 2px; }
.login-brand { font-size: 30px; font-weight: 800; margin: 0; letter-spacing: .04em; color: var(--ink); }
.login-brand .rd { color: var(--accent); }
.login-sub { font-size: 10px; color: var(--ink-3); letter-spacing: .14em; margin: 6px 0 22px; }
.login-tabs { display: flex; gap: 3px; background: var(--bg-sunken); padding: 4px; border-radius: var(--r-md); margin-bottom: 14px; }
.login-tabs button { flex: 1; padding: 9px; font-size: 14px; font-weight: 700; color: var(--ink-3); border-radius: 9px; }
.login-tabs button.on { background: var(--bg); color: var(--ink); box-shadow: var(--sh-sm); }
.login-err { font-size: 12.5px; color: var(--accent); background: var(--accent-wash); border: 1px solid var(--accent-border); padding: 8px 12px; margin-bottom: 12px; border-radius: var(--r-sm); }
.login-input { width: 100%; padding: 12px 14px; font-size: 15px; background: var(--bg); border: 1px solid var(--line); border-radius: var(--r-sm); margin-bottom: 9px; outline: none; }
.login-input:focus { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-wash); }
.login-btn { width: 100%; padding: 13px; font-size: 15px; font-weight: 700; background: var(--accent); color: #fff; border-radius: var(--r-md); margin-top: 6px; }
.login-btn:disabled { opacity: .55; }
.login-foot { font-size: 10.5px; color: var(--ink-3); margin-top: 16px; letter-spacing: .04em; }

/* 首页 */
.hd { margin-bottom: 16px; }
.overline { font-size: 10.5px; font-weight: 600; letter-spacing: .14em; color: var(--accent); text-transform: uppercase; }
.hd h1 { font-size: 30px; font-weight: 800; letter-spacing: -.02em; margin: 10px 0 0; line-height: 1.1; color: var(--ink); }
.hd h1 em { font-style: normal; color: var(--accent); }
.search-bar { display: flex; align-items: center; gap: 10px; padding: 13px 15px; background: var(--bg); border: 1px solid var(--line-strong); border-radius: var(--r-md); margin: 18px 0 16px; box-shadow: var(--sh-sm); }
.search-bar .si { color: var(--accent); font-size: 16px; }
.search-bar .sp { color: var(--ink-4); font-size: 14px; }
.kpi-row { display: flex; background: var(--bg); border: 1px solid var(--line); border-radius: var(--r-md); overflow: hidden; margin-bottom: 22px; }
.kpi-item { flex: 1; text-align: center; padding: 13px 8px; }
.kpi-item + .kpi-item { border-left: 1px solid var(--line); }
.kpi-item b { display: block; font-size: 21px; font-weight: 600; color: var(--ink); }
.kpi-item span { display: block; font-size: 10px; color: var(--ink-3); margin-top: 2px; }
.section-title { font-size: 10px; font-weight: 600; color: var(--ink-3); margin: 0 2px 10px; letter-spacing: .1em; text-transform: uppercase; }
.section-title:not(:first-of-type) { margin-top: 20px; }
.hot-grid { display: flex; flex-direction: column; gap: 8px; }
.hot-card { display: flex; align-items: center; justify-content: space-between; padding: 13px 15px; background: var(--bg); border: 1px solid var(--line); border-radius: var(--r-md); font-size: 14px; font-weight: 600; color: var(--ink); text-align: left; }
.hot-card .arr { color: var(--ink-4); }
.hot-card:active { background: var(--accent-wash); border-color: var(--accent-border); }
.hot-card:active .arr { color: var(--accent); }
.hot-card.rag:active { background: var(--up-wash); }

/* 探索 */
.page-title { font-size: 20px; font-weight: 800; margin-bottom: 6px; color: var(--ink); }
.brand-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 9px; margin-top: 14px; }
.brand-card { display: flex; align-items: center; justify-content: space-between; padding: 14px 15px; background: var(--bg); border: 1px solid var(--line); border-radius: var(--r-md); }
.brand-card:active { background: var(--accent-wash); border-color: var(--accent-border); }
.brand-name { font-size: 14.5px; font-weight: 700; color: var(--ink); }
.brand-go { font-size: 11px; color: var(--ink-3); }
.ex-seg { display: flex; gap: 3px; background: var(--bg-sunken); border: 1px solid var(--line); border-radius: var(--r-md); padding: 3px; margin: 6px 0 14px; }
.ex-seg button { flex: 1; padding: 8px; font-size: 13.5px; font-weight: 700; color: var(--ink-3); border-radius: 9px; }
.ex-seg button.on { background: var(--bg); color: var(--ink); box-shadow: var(--sh-sm); }
.price-search { display: flex; align-items: center; gap: 9px; padding: 11px 14px; background: var(--bg); border: 1px solid var(--line-strong); border-radius: var(--r-md); margin-bottom: 10px; box-shadow: var(--sh-sm); }
.price-search .ps-ic { color: var(--accent); font-size: 16px; }
.price-search input { flex: 1; border: none; outline: none; background: transparent; font-size: 14px; }
.price-list { display: flex; flex-direction: column; }
.price-row { display: flex; align-items: center; gap: 12px; padding: 12px 6px; border-bottom: 1px solid var(--line-soft); }
.price-row:active { background: var(--bg-subtle); }
.pr-meta { flex: 1; min-width: 0; }
.pr-nm { font-size: 14.5px; font-weight: 700; color: var(--ink); display: flex; align-items: center; gap: 7px; }
.pr-nm .pr-bd { font-size: 11px; font-weight: 500; color: var(--ink-3); }
.pr-tags { display: flex; gap: 5px; margin-top: 4px; flex-wrap: wrap; }
.pr-tag { font-size: 10px; color: var(--ink-2); background: var(--bg-sunken); padding: 1px 7px; border-radius: 5px; }
.pr-price { text-align: right; flex: none; }
.pr-pt { font-size: 15px; font-weight: 600; color: var(--accent); }
.pr-down { display: block; font-size: 10px; color: var(--up); margin-top: 2px; }

/* 对话 */
.chat-page { display: flex; flex-direction: column; padding: 0; height: 100%; }
.chat-top { flex: none; display: flex; align-items: center; padding: 12px 16px; background: var(--bg); border-bottom: 1px solid var(--line); }
.chat-title { flex: 1; font-size: 16px; font-weight: 700; color: var(--ink); }
.chat-new { color: var(--accent); font-size: 14px; font-weight: 700; }
.chat-body { flex: 1; overflow-y: auto; padding: 14px 12px; }
.chat-empty { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; gap: 6px; text-align: center; }
.chat-empty .ce-ic { width: 52px; height: 52px; border-radius: 16px; background: var(--accent-wash); color: var(--accent); display: flex; align-items: center; justify-content: center; font-size: 22px; }
.chat-empty p { font-size: 15px; font-weight: 600; color: var(--ink); margin: 6px 0 0; }
.msg { margin-bottom: 18px; }
.u-row { display: flex; justify-content: flex-end; }
.u-bubble { max-width: 82%; padding: 10px 14px; background: var(--ink); color: #fff; border-radius: 15px 15px 4px 15px; font-size: 14.5px; line-height: 1.55; word-break: break-word; }
.a-row { display: flex; gap: 9px; }
.a-avatar { flex: none; width: 30px; height: 30px; border-radius: 10px; background: linear-gradient(140deg, var(--accent), var(--accent-press)); color: #fff; display: flex; align-items: center; justify-content: center; font-size: 13px; }
.a-body { flex: 1; min-width: 0; background: var(--bg); border: 1px solid var(--line); border-radius: 4px 14px 14px 14px; padding: 12px 14px; box-shadow: var(--sh-sm); }
.trace { display: flex; align-items: center; gap: 7px; }
.t-spark { color: var(--accent); font-size: 12px; }
.t-txt { font-size: 11px; font-weight: 600; letter-spacing: .08em; color: var(--ink-3); display: inline-flex; align-items: center; }
.dots { display: inline-flex; gap: 3px; margin-left: 5px; }
.dots i { width: 4px; height: 4px; border-radius: 50%; background: var(--accent); animation: skeletonPulse 1.2s ease-in-out infinite; }
.dots i:nth-child(2) { animation-delay: .15s; } .dots i:nth-child(3) { animation-delay: .3s; }
.badge { margin-left: auto; font-size: 10.5px; font-weight: 700; padding: 2px 9px; border-radius: 999px; }
.badge em { font-style: normal; font-family: var(--font-mono); opacity: .75; }
.badge.sql { background: var(--info-wash); color: var(--info); }
.badge.rag { background: var(--up-wash); color: var(--up); }
.badge.mix { background: var(--accent-wash); color: var(--accent); }
.a-text { font-size: 14.5px; line-height: 1.75; color: var(--ink); white-space: pre-wrap; margin-top: 10px; }
.cursor { display: inline-block; width: 6px; height: 14px; background: var(--accent); margin-left: 2px; vertical-align: -2px; animation: blink 1s step-start infinite; }
.a-err { font-size: 13.5px; color: var(--accent); margin-top: 8px; }
.cites { margin-top: 12px; border-top: 1px dashed var(--line-strong); padding-top: 10px; }
.cites-h { font-size: 10px; font-weight: 600; letter-spacing: .1em; color: var(--up); text-transform: uppercase; margin-bottom: 8px; }
.cite { display: flex; align-items: center; gap: 10px; padding: 8px 10px; background: var(--bg-subtle); border: 1px solid var(--line); border-radius: var(--r-sm); margin-bottom: 7px; }
.c-idx { flex: none; width: 24px; height: 24px; border-radius: 7px; background: var(--accent); color: #fff; display: inline-flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 600; }
.c-meta { flex: 1; min-width: 0; }
.c-doc { display: block; font-size: 13px; font-weight: 700; color: var(--ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.c-path { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 3px; }
.c-seg { font-size: 10px; color: var(--ink-2); background: var(--bg-sunken); padding: 1px 6px; border-radius: 4px; }
.c-pg { flex: none; font-size: 11px; font-weight: 600; color: var(--up); align-self: flex-start; }
.chat-input-bar { flex: none; display: flex; align-items: flex-end; gap: 8px; padding: 9px 12px calc(9px + env(safe-area-inset-bottom)); background: var(--bg); border-top: 1px solid var(--line); }
.chat-input-bar textarea { flex: 1; border: 1px solid var(--line-strong); border-radius: 20px; outline: none; padding: 10px 15px; font-size: 15px; resize: none; max-height: 100px; background: var(--bg-subtle); }
.chat-input-bar textarea:focus { border-color: var(--accent); background: var(--bg); }
.chat-send { flex: none; padding: 10px 18px; border-radius: 20px; font-size: 14px; font-weight: 700; background: var(--accent); color: #fff; }
.chat-send:disabled { background: var(--bg-sunken); color: var(--ink-4); }
.chat-send.stop { background: var(--ink-3); }

/* 知识库 */
.kb-list { margin-top: 14px; display: flex; flex-direction: column; gap: 9px; }
.kb-doc { display: flex; align-items: center; gap: 11px; padding: 12px 14px; background: var(--bg); border: 1px solid var(--line); border-radius: var(--r-md); }
.kb-ft { flex: none; width: 38px; height: 38px; border-radius: 10px; background: var(--bg-sunken); color: var(--ink-2); display: inline-flex; align-items: center; justify-content: center; font-size: 9px; font-weight: 600; }
.kb-meta { flex: 1; min-width: 0; }
.kb-title { display: block; font-size: 13.5px; font-weight: 700; color: var(--ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.kb-sub { font-size: 10.5px; color: var(--ink-3); }
.kb-ok { flex: none; font-size: 11px; font-weight: 700; color: var(--up); background: var(--up-wash); padding: 3px 10px; border-radius: 999px; }
.kb-ask { display: block; width: 100%; margin-top: 16px; padding: 13px; background: var(--accent); color: #fff; font-size: 15px; font-weight: 700; border-radius: var(--r-md); }

/* 我的 */
.me-card { display: flex; align-items: center; gap: 13px; padding: 18px; background: var(--bg); border: 1px solid var(--line); border-radius: var(--r-lg); }
.me-avatar { width: 52px; height: 52px; border-radius: 15px; background: linear-gradient(140deg, var(--accent), var(--accent-press)); color: #fff; display: flex; align-items: center; justify-content: center; font-size: 22px; font-weight: 700; }
.me-id b { display: block; font-size: 17px; font-weight: 700; color: var(--ink); }
.me-role { font-size: 10.5px; font-weight: 700; color: var(--accent); background: var(--accent-wash); border: 1px solid var(--accent-border); padding: 1px 8px; border-radius: 999px; margin-left: 7px; }
.me-id span { font-size: 12px; color: var(--ink-3); }
.me-stats { display: flex; gap: 10px; margin-top: 14px; }
.me-stats .ms { flex: 1; text-align: center; background: var(--bg); border: 1px solid var(--line); border-radius: var(--r-md); padding: 14px 8px; }
.me-stats .ms b { display: block; font-size: 19px; font-weight: 600; color: var(--ink); }
.me-stats .ms span { display: block; font-size: 11px; color: var(--ink-3); margin-top: 2px; }
.logout-btn { width: 100%; margin-top: 10px; padding: 13px; background: var(--bg); color: var(--accent); border: 1px solid var(--accent-border); font-size: 15px; font-weight: 700; border-radius: var(--r-md); }
.logout-btn:active { background: var(--accent-wash); }
</style>
