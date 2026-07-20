<script setup>
// 对话流：用户气泡 + 助手消息，内容增长时自动滚到底。
import { ref, watch, nextTick } from 'vue'
import UserMessage from './UserMessage.vue'
import AssistantMessage from './AssistantMessage.vue'

const props = defineProps({ messages: { type: Array, default: () => [] } })
const emit = defineEmits(['ask'])

const scroller = ref(null)
function toBottom() {
  nextTick(() => {
    const el = scroller.value
    if (el) el.scrollTop = el.scrollHeight
  })
}
// 监听消息数量与最后一条的流式内容长度
watch(
  () => {
    const last = props.messages[props.messages.length - 1]
    return [props.messages.length, last?.insight?.length, last?.status, last?.rows?.length, last?.sql?.length]
  },
  toBottom,
  { deep: true },
)
</script>

<template>
  <div ref="scroller" class="scroller">
    <div class="thread">
      <template v-for="m in messages" :key="m.id">
        <UserMessage v-if="m.role === 'user'" :content="m.content" />
        <AssistantMessage v-else :msg="m" @ask="(q) => emit('ask', q)" />
      </template>
    </div>
  </div>
</template>

<style scoped>
.scroller { flex: 1; overflow-y: auto; min-height: 0; }
.thread {
  max-width: var(--maxw-thread); margin: 0 auto;
  padding: 28px 24px 16px; display: flex; flex-direction: column; gap: 22px;
}
</style>
