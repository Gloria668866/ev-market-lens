import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

// Vite 配置：固定 5173 端口（与后端 CORS 放行口径一致），@ 指向 src。
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    port: 5173,
    strictPort: false,
  },
  build: {
    // ECharts 体积大且极少变动 → 拆独立 chunk：首屏只拉业务代码，且发版后 echarts 缓存仍命中
    // ECharts + zrender 合并后约 560KB（gzip 约 187KB），属于刻意的稳定缓存边界。
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules/echarts') || id.includes('node_modules/zrender')) return 'echarts'
          if (id.includes('node_modules/vue/') || id.includes('node_modules/@vue/')) return 'vue'
          if (id.includes('node_modules')) return 'vendor'
        },
      },
    },
  },
})
