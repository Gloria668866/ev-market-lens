<script setup>
// 车市镜标志：镜头/准星 —— 外圈镜身 + 四向刻度 + 中心菱形（市场被"对准看清"）。
// tone: 'brand'(车速红) | 'ink'(墨色) | 'light'(浅色，用于红底之上) | 'mono'(currentColor)
defineProps({
  size: { type: Number, default: 28 },
  tone: { type: String, default: 'brand' },
  scan: { type: Boolean, default: false }, // 思考时光圈呼吸
})
</script>

<template>
  <span class="mark" :class="[tone, { scan }]" :style="{ width: size + 'px', height: size + 'px' }">
    <svg viewBox="0 0 48 48" :width="size" :height="size" fill="none" aria-hidden="true">
      <circle cx="24" cy="24" r="20" class="rim" stroke-width="2.6" />
      <circle cx="24" cy="24" r="20" class="rim-dash" stroke-width="1" stroke-dasharray="3.5,3" opacity=".32" />
      <g class="ticks" stroke-width="2.6" stroke-linecap="round">
        <line x1="24" y1="7"  x2="24" y2="13" />
        <line x1="24" y1="35" x2="24" y2="41" />
        <line x1="7"  y1="24" x2="13" y2="24" />
        <line x1="35" y1="24" x2="41" y2="24" />
      </g>
      <polygon class="core" points="24,18 30,24 24,30 18,24" />
    </svg>
  </span>
</template>

<style scoped>
.mark { position: relative; display: inline-flex; align-items: center; justify-content: center; flex: none; }

.brand .rim, .brand .rim-dash, .brand .ticks { stroke: var(--accent); }
.brand .core { fill: var(--accent); }

.ink .rim, .ink .rim-dash, .ink .ticks { stroke: var(--ink); }
.ink .core { fill: var(--ink); }

.light .rim, .light .rim-dash, .light .ticks { stroke: #fff; }
.light .core { fill: #fff; }

.mono .rim, .mono .rim-dash, .mono .ticks { stroke: currentColor; }
.mono .core { fill: currentColor; }

.scan .rim-dash { transform-origin: 24px 24px; animation: spin 8s linear infinite; }
.scan .core { animation: blink 1.6s ease-in-out infinite; }
</style>
