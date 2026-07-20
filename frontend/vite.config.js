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
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules/echarts')) return 'echarts'
          if (id.includes('node_modules/vue')) return 'vue'
          if (id.includes('node_modules')) return 'vendor'
        },
      },
    },
  },
})
