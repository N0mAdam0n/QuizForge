<script setup lang="ts">
import { SidebarProvider, SidebarInset, SidebarTrigger } from '~/components/ui/sidebar'
import AppSidebar from '~/components/AppSidebar.vue'
import FloatingChatWidget from '~/components/chat/FloatingChatWidget.vue'
import { toast } from 'vue-sonner'
import { useLocalStorage, useMediaQuery, useSessionStorage } from '@vueuse/core'

const { fetchUser, token, user } = useAuth()
const { hasSubjects } = useSubjectContext()
const {
  state: updateState,
  check: checkUpdate,
  downloadAndInstall,
} = useUpdateCheck()
const ignoredVersion = useLocalStorage('ignored-update-version', '')
const hasPrompted = useSessionStorage('update-prompted', false)
const isMobile = useMediaQuery('(max-width: 768px)')
const { preferences, load: loadPreferences } = usePreferences()
useApplyPreferences()

// 普通用户未被分配任何学科时的空状态提示(管理员不受限)。
const showNoSubjectHint = computed(
  () => !!token.value && !user.value?.is_superuser && !hasSubjects.value,
)

onMounted(async () => {
  // 学科上下文已由 auth.global.ts 中间件在进入本布局前初始化完毕
  if (token.value) {
    await fetchUser()
  }
  if (token.value) {
    await loadPreferences()
  }
  // 用户可在设置中关闭启动时自动检查更新
  if (!preferences.value.auto_check_update) return
  // 让所有登录用户都能检查更新，以便进行对应权限的弹窗提示
  await checkUpdate()
  
  const latest = updateState.value.latest
  if (updateState.value.hasUpdate && latest !== ignoredVersion.value && !hasPrompted.value) {
    hasPrompted.value = true
    
    if (user.value?.is_superuser) {
      const startUpdate = () => {
        if (!updateState.value.portable) {
          window.open(updateState.value.releaseUrl, '_blank')
          return
        }
        void downloadAndInstall().catch((error: unknown) => {
          toast.error('更新失败', {
            description: error instanceof Error ? error.message : '请稍后重试。',
          })
        })
      }
      toast.info(`发现新版本 v${latest}`, {
        description: updateState.value.portable
          ? `当前 v${updateState.value.current} · ${updateState.value.isPatch ? '增量更新' : '完整更新'}`
          : `当前 v${updateState.value.current} · 请下载新版安装程序更新`,
        action: {
          label: updateState.value.portable ? '立即更新' : '下载新版',
          onClick: startUpdate,
        },
        cancel: {
          label: '忽略此版',
          onClick: () => {
            ignoredVersion.value = latest
          }
        }
      })
    } else {
      // 普通用户仅提示联系管理员
      toast.info(`发现系统新版本 v${latest}`, {
        description: `当前 v${updateState.value.current} · 为了获得更好的体验，请联系管理员进行升级，或忽略此版本。`,
        cancel: {
          label: '我知道了',
          onClick: () => {
            ignoredVersion.value = latest
          }
        }
      })
    }
  }
})
</script>

<template>
  <SidebarProvider>
    <AppSidebar />
    <SidebarInset>
      <header v-if="isMobile" class="flex h-12 shrink-0 items-center gap-2 border-b px-3">
        <SidebarTrigger aria-label="打开导航菜单" />
      </header>
      <div
        v-if="showNoSubjectHint"
        class="m-4 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300"
      >
        您还没有被分配任何学科，暂时看不到题库内容。请联系管理员在“学科管理 → 成员管理”中为您开通。
      </div>
      <slot />
    </SidebarInset>
    <FloatingChatWidget />
  </SidebarProvider>
</template>
