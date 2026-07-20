import { ref, onMounted, onBeforeUnmount } from 'vue'

export function useIsMobile(breakpoint = 720) {
  const isMobile = ref(window.innerWidth < breakpoint)
  function check() { isMobile.value = window.innerWidth < breakpoint }
  onMounted(() => window.addEventListener('resize', check))
  onBeforeUnmount(() => window.removeEventListener('resize', check))
  return { isMobile }
}
