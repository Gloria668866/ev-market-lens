<script setup>
import { useToast } from '@/composables/useToast.js'
const { toasts, dismiss } = useToast()
</script>

<template>
  <div class="toasts">
    <transition-group name="t">
      <div v-for="t in toasts" :key="t.id" class="toast" :class="t.type" @click="dismiss(t.id)">
        <span class="ic">
          <template v-if="t.type === 'ok'">✓</template>
          <template v-else-if="t.type === 'err'">!</template>
          <template v-else>›</template>
        </span>
        {{ t.message }}
      </div>
    </transition-group>
  </div>
</template>

<style scoped>
.toasts { position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%); z-index: 200; display: flex; flex-direction: column; align-items: center; gap: 8px; pointer-events: none; }
.toast { pointer-events: auto; cursor: pointer; display: inline-flex; align-items: center; gap: 9px; background: var(--ink); color: #fff; font-size: 13px; font-weight: 600; padding: 10px 16px; border-radius: 999px; box-shadow: var(--sh-lg); }
.toast .ic { width: 18px; height: 18px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 700; background: rgba(255,255,255,.18); }
.toast.ok .ic { background: var(--up); }
.toast.err .ic { background: var(--accent); }
.t-enter-active, .t-leave-active { transition: opacity .2s ease, transform .2s ease; }
.t-enter-from { opacity: 0; transform: translateY(8px); }
.t-leave-to { opacity: 0; transform: translateY(8px); }
</style>
