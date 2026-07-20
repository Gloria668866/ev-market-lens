// 对话状态机：把规范 SSE 事件流装配成「助手消息模型」，并维护会话历史。
// 双脑分流的关键在这里：根据 intent 与到达的事件，决定渲染数据卡还是知识答案。
// 会话历史按「当前登录用户」分桶持久化到 localStorage —— 不同账号只看到自己的历史（数据隔离）。
import { reactive, ref, computed, watch } from 'vue'
import { ask } from '@/api/client.js'
import { IS_MOCK } from '@/api/config.js'
import { listConversations, getConversation, deleteConversation as apiDeleteConversation } from '@/api/history.js'
import { useAuth } from '@/composables/useAuth.js'

let _id = 0
const uid = () => `${Date.now()}-${++_id}`
const convKey = (userId) => `cheshijing.conv.${userId || 'anon'}`

// 服务端历史消息（/api/history/{id}）→ 前端消息模型（还原含图表/引用的对话）
function buildMsgFromHistory(m) {
  if (m.role === 'user') return { id: uid(), role: 'user', content: m.content || '' }
  return reactive({
    id: uid(), role: 'assistant', status: 'done',
    intent: m.intent, confidence: null, stages: [],
    sql: '', columns: m.columns || [], rows: m.rows || [],
    chartPayload: m.chart || null,
    insight: m.content || '', citations: m.citations || [], error: null,
  })
}

function makeStages(intent) {
  if (intent === 'chat' || intent === 'clarify') {
    return [
      { key: 'intent', label: '意图识别', status: 'done' },
      { key: 'produce', label: '生成回复', status: 'active' },
    ]
  }
  const recall = intent === 'rag' ? { key: 'recall', label: '检索知识库' } : { key: 'recall', label: '查询数据库' }
  const produce = intent === 'rag' ? { key: 'produce', label: '生成答案' } : { key: 'produce', label: '生成图表与结论' }
  return [
    { key: 'intent', label: '意图识别', status: 'done' },
    { ...recall, status: 'active' },
    { ...produce, status: 'pending' },
  ]
}

function newAssistant(question = '') {
  return reactive({
    id: uid(), role: 'assistant', status: 'thinking',
    question,                                     // 原问题：错误时一键重试用
    intent: null, confidence: null, stages: [],
    sql: '', columns: [], rows: [],
    chartPayload: null,
    insight: '', citations: [], error: null, startedAt: Date.now(),
  })
}

function setStage(msg, key, status) {
  const s = msg.stages.find((x) => x.key === key)
  if (s) s.status = status
}

export function useChat() {
  const { state: auth } = useAuth()
  const conversations = reactive([])
  const activeId = ref(null)
  const sending = ref(false)
  let handle = null

  const active = computed(() => conversations.find((c) => c.id === activeId.value) || null)
  const messages = computed(() => active.value?.messages || [])

  // —— 持久化（仅 mock：按用户分桶存 localStorage；live 模式服务端已落库，不本地存）—— //
  function persist() {
    if (!auth.user || !IS_MOCK) return
    try {
      const data = conversations.map((c) => ({
        id: c.id, title: c.title, createdAt: c.createdAt, serverConvId: c.serverConvId ?? null,
        messages: c.messages.map((m) => m.role === 'user'
          ? { id: m.id, role: 'user', content: m.content }
          : { // 助手：保留 chartPayload + columns/rows，图表 option 由组件按当前图型重建（不入库）
              id: m.id, role: 'assistant', status: 'done', intent: m.intent, confidence: m.confidence,
              stages: m.stages, sql: m.sql, columns: m.columns, rows: m.rows,
              chartPayload: m.chartPayload, insight: m.insight, citations: m.citations,
            }),
      }))
      localStorage.setItem(convKey(auth.user.id), JSON.stringify(data))
    } catch {}
  }

  function load(userId) {
    conversations.splice(0, conversations.length)
    activeId.value = null
    if (!userId) return
    if (IS_MOCK) { loadLocal(userId); return }
    // live：从 /api/history 拉会话列表（消息按需在 selectConversation 里拉详情还原）
    listConversations().then((list) => {
      if (!list || auth.user?.id !== userId) return   // 期间切了账号则丢弃
      for (const c of list) {
        conversations.push(reactive({
          id: c.serverConvId, title: c.title, createdAt: c.createdAt,
          serverConvId: c.serverConvId, messages: [], loaded: false, loading: false,
        }))
      }
    }).catch(() => {})
  }

  function loadLocal(userId) {
    try {
      const raw = JSON.parse(localStorage.getItem(convKey(userId)) || '[]')
      for (const c of raw) {
        conversations.push(reactive({
          id: c.id, title: c.title, createdAt: c.createdAt, serverConvId: c.serverConvId ?? null,
          loaded: true, loading: false,
          messages: c.messages.map((m) => m.role === 'user'
            ? { id: m.id, role: 'user', content: m.content }
            : reactive({ ...m, error: null })),
        }))
      }
    } catch {}
  }

  // 登录用户变化（登录 / 切换账号 / 退出）→ 切换会话桶
  watch(() => auth.user?.id, (id) => load(id), { immediate: true })

  function newConversation() {
    const conv = reactive({ id: uid(), title: '新对话', messages: [], createdAt: Date.now(), serverConvId: null, loaded: true, loading: false })
    conversations.unshift(conv)
    activeId.value = conv.id
    return conv
  }

  function selectConversation(id) {
    if (sending.value) return
    activeId.value = id
    // live：首次打开历史会话 → 拉详情还原（含图表/引用），mock 本地副本已完整
    const conv = conversations.find((c) => c.id === id)
    if (!conv || conv.loaded || conv.loading || conv.serverConvId == null) return
    conv.loading = true
    getConversation(conv.serverConvId).then((detail) => {
      if (detail) {
        conv.messages.splice(0, conv.messages.length, ...detail.messages.map(buildMsgFromHistory))
        if (detail.title) conv.title = detail.title
      }
    }).catch(() => {}).finally(() => { conv.loaded = true; conv.loading = false })
  }

  async function deleteConversation(id) {
    if (sending.value) return
    const idx = conversations.findIndex((c) => c.id === id)
    if (idx === -1) return
    const conv = conversations[idx]
    // live：先删服务端（失败则不动本地，避免「界面删了库里还在」）
    if (!IS_MOCK && conv.serverConvId != null) {
      try { await apiDeleteConversation(conv.serverConvId) } catch { return }
    }
    conversations.splice(idx, 1)
    if (activeId.value === id) activeId.value = conversations[0]?.id || null
    persist()
  }

  function send(question) {
    const q = (question || '').trim()
    if (!q || sending.value) return
    let conv = active.value
    if (!conv) conv = newConversation()
    if (conv.messages.length === 0) conv.title = q.length > 20 ? q.slice(0, 20) + '…' : q

    conv.messages.push({ id: uid(), role: 'user', content: q })
    const msg = newAssistant(q)
    conv.messages.push(msg)
    sending.value = true
    persist()

    handle = ask(q, {
      onEvent: (ev) => {
        applyEvent(msg, ev)
        // 后端在 meta/done 回带 conversation_id；记到前端会话上，下一轮带回去续接同一后端会话
        if (ev.conversationId != null) conv.serverConvId = ev.conversationId
      },
      onError: (err) => { msg.status = 'error'; msg.error = err; sending.value = false; persist() },
      onClose: () => {
        if (msg.status !== 'error') msg.status = 'done'
        msg.stages.forEach((s) => { if (s.status === 'active') s.status = 'done' })
        sending.value = false
        persist()
      },
    }, conv.serverConvId)
  }

  function applyEvent(msg, ev) {
    switch (ev.type) {
      case 'stage':
        // 后端起跑前的即时反馈：intent 未到时先亮一个「分析问题」步骤，避免长时间无响应感
        if (!msg.stages.length) {
          msg.stages = [{ key: 'intent', label: ev.message || '分析问题中', status: 'active' }]
        }
        break
      case 'intent':
        msg.intent = ev.intent; msg.confidence = ev.confidence
        msg.stages = makeStages(ev.intent); msg.status = 'thinking'; break
      case 'sql':
        msg.sql = ev.sql; setStage(msg, 'recall', 'active'); break
      case 'rows':
        msg.columns = ev.columns; msg.rows = ev.rows
        setStage(msg, 'recall', 'done'); setStage(msg, 'produce', 'active'); break
      case 'chart':
        msg.chartPayload = ev.chart   // 原始建议 {chart_type,x,y,...}；图型/重绘由 DataResultCard 负责
        break
      case 'insight':
        if (msg.status !== 'streaming') {
          msg.status = 'streaming'; setStage(msg, 'recall', 'done'); setStage(msg, 'produce', 'active')
        }
        msg.insight += ev.delta; break
      case 'citation':
        // §9.1 逐条推：累加（一个事件一条引用）
        if (ev.citation) msg.citations.push(ev.citation); break
      case 'done':
        msg.msgId = ev.msgId; break
      case 'error':
        msg.status = 'error'; msg.error = ev; break
    }
  }

  function renameConversation({ id, title }) {
    const conv = conversations.find((c) => c.id === id)
    if (conv) { conv.title = title; persist() }
  }

  function stop() {
    handle?.abort()
    sending.value = false
    const list = active.value?.messages
    const last = list?.[list.length - 1]
    if (last && last.role === 'assistant' && (last.status === 'thinking' || last.status === 'streaming')) {
      last.status = 'done'
      last.stages.forEach((s) => { if (s.status === 'active') s.status = 'done' })
      if (!last.insight) last.insight = '（已停止生成）'
    }
    persist()
  }

  return {
    conversations, activeId, active, messages, sending,
    newConversation, selectConversation, deleteConversation, renameConversation, send, stop,
  }
}
