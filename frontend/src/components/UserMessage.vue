<script setup>
defineProps({ content: { type: String, required: true } })
</script>

<template>
  <div class="user">
    <div class="bubble">{{ content }}</div>
  </div>
</template>

<style scoped>
.user { display: flex; justify-content: flex-end; animation: fadeUp .26s ease both; }
.bubble {
  max-width: 78%; background: var(--ink); color: #fff;
  padding: 11px 16px; border-radius: 16px 16px 5px 16px;
  font-size: 14.5px; line-height: 1.6; box-shadow: var(--sh-sm); white-space: pre-wrap; word-break: break-word;
}
</style>
