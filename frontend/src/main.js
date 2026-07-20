import { createApp } from 'vue'
import App from './App.vue'
import PublicShare from './components/PublicShare.vue'
import './styles/global.css'

// 轻量「路由」：/s/{token} 走免登录公开分享页，其余走主应用（无需引入 vue-router）。
const isShare = window.location.pathname.startsWith('/s/')
createApp(isShare ? PublicShare : App).mount('#app')
