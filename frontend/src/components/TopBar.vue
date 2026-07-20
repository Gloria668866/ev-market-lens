<script setup>
// 顶栏（薄）：移动端汉堡 + 当前标题 + 引擎状态。用户菜单已下放到侧栏底部。
defineProps({
  title: { type: String, default: '命令中心' },
  subtitle: { type: String, default: '' },
})
const emit = defineEmits(['toggleSide'])
</script>

<template>
  <header class="topbar">
    <button class="burger" @click="emit('toggleSide')" aria-label="菜单">
      <svg width="18" height="18" viewBox="0 0 18 18" fill="none"><path d="M2 4.5h14M2 9h14M2 13.5h14" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>
    </button>
    <span class="title">{{ title }}</span>
    <span v-if="subtitle" class="crumb">· {{ subtitle }}</span>
    <div class="right">
      <span class="status"><span class="live"></span>引擎在线 · 双脑 Agent</span>
    </div>
  </header>
</template>

<style scoped>
.topbar { height: 54px; flex: none; display: flex; align-items: center; gap: 10px; padding: 0 22px; background: var(--bg); border-bottom: 1px solid var(--line); }
.burger { display: none; width: 32px; height: 32px; align-items: center; justify-content: center; border-radius: 8px; color: var(--ink-2); }
.burger:hover { background: var(--bg-subtle); }
.title { font-family: var(--font-display); font-size: 14.5px; font-weight: 700; color: var(--ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 60%; }
.crumb { font-family: var(--font-mono); font-size: 11px; color: var(--ink-3); flex: none; }
.right { margin-left: auto; display: flex; align-items: center; gap: 8px; }
.status { display: inline-flex; align-items: center; gap: 7px; font-family: var(--font-mono); font-size: 11px; color: var(--ink-2); background: var(--bg-subtle); border: 1px solid var(--line); padding: 5px 11px; border-radius: 999px; }
.status .live { width: 7px; height: 7px; border-radius: 50%; background: var(--up); box-shadow: 0 0 0 3px var(--up-wash); }

@media (max-width: 860px) {
  .burger { display: inline-flex; }
  .status { display: none; }
}
</style>
