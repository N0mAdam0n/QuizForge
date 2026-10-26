<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useLocalStorage } from '@vueuse/core'
import { toast } from 'vue-sonner'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { Label } from '@/components/ui/label'
import {
  QUESTIONS_PER_ROUND_OPTIONS,
  usePreferences,
  type UserPreferences,
} from '~/composables/usePreferences'

const { $api } = useNuxtApp()
const { user, fetchUser } = useAuth()
const { preferences, load, save } = usePreferences()
const { state: updateState, check: checkUpdate } = useUpdateCheck()

const selectClass = 'flex h-9 w-full max-w-xs rounded-md border border-input bg-background px-3 py-1 text-sm'
const errorMessage = (error: unknown) => (error instanceof Error ? error.message : '请稍后重试。')

const savePreference = async <K extends keyof UserPreferences>(key: K, value: UserPreferences[K]) => {
  try {
    await save({ [key]: value } as Partial<UserPreferences>)
    toast.success('已保存')
  } catch (error) {
    toast.error('保存失败', { description: errorMessage(error) })
  }
}

// ---- 数据：遥测同意 ----
const telemetryConsent = useState<boolean>('telemetry-consent', () => false)
const telemetryEnabled = ref(true)
const telemetrySaving = ref(false)
const consentDecision = useLocalStorage<'accepted' | 'declined' | ''>('telemetry-consent-decision', '')

const loadConsent = async () => {
  try {
    const status = await $api<{ enabled: boolean; consent: boolean }>('/telemetry/consent')
    telemetryEnabled.value = status.enabled
    telemetryConsent.value = status.consent
  } catch (error) {
    console.debug('Could not load telemetry consent', error)
  }
}

const onToggleConsent = async (value: boolean) => {
  telemetrySaving.value = true
  try {
    const status = await $api<{ enabled: boolean; consent: boolean }>('/telemetry/consent', {
      method: 'PUT',
      body: { consent: value },
    })
    telemetryConsent.value = status.consent
    consentDecision.value = status.consent ? 'accepted' : 'declined'
    toast.success(status.consent ? '已同意数据传输' : '已撤回数据传输同意')
  } catch (error) {
    toast.error('保存失败', { description: errorMessage(error) })
  } finally {
    telemetrySaving.value = false
  }
}

// ---- 数据：导出 / 清空 ----
const exporting = ref(false)
const exportHistory = async (format: 'csv' | 'json') => {
  exporting.value = true
  try {
    const blob = await $api<Blob>('/practice/history/export', { query: { format }, responseType: 'blob' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `practice-history.${format}`
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
  } catch (error) {
    toast.error('导出失败', { description: errorMessage(error) })
  } finally {
    exporting.value = false
  }
}

const clearing = ref(false)
const clearHistory = async () => {
  if (!window.confirm('确定要清空你的全部作答记录吗？错题本不会受影响。')) return
  if (!window.confirm('再次确认：清空后无法恢复，是否继续？')) return
  clearing.value = true
  try {
    const result = await $api<{ deleted: number }>('/practice/history', {
      method: 'DELETE',
      query: { confirm: 'CLEAR' },
    })
    toast.success(`已清空 ${result.deleted} 条作答记录`)
  } catch (error) {
    toast.error('清空失败', { description: errorMessage(error) })
  } finally {
    clearing.value = false
  }
}

// ---- 账户 ----
const nickname = ref('')
const nicknameSaving = ref(false)
const saveNickname = async () => {
  const value = nickname.value.trim()
  if (!value) {
    toast.error('昵称不能为空')
    return
  }
  nicknameSaving.value = true
  try {
    await $api('/users/me/nickname', { method: 'PUT', body: { full_name: value } })
    await fetchUser()
    toast.success('昵称已更新')
  } catch (error) {
    toast.error('保存失败', { description: errorMessage(error) })
  } finally {
    nicknameSaving.value = false
  }
}

const currentPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const passwordSaving = ref(false)
const canChangePassword = computed(
  () => !!currentPassword.value && newPassword.value.length >= 6 && newPassword.value === confirmPassword.value,
)
const changePassword = async () => {
  if (!canChangePassword.value) return
  passwordSaving.value = true
  try {
    await $api('/users/me/password', {
      method: 'POST',
      body: { current_password: currentPassword.value, new_password: newPassword.value },
    })
    currentPassword.value = ''
    newPassword.value = ''
    confirmPassword.value = ''
    toast.success('密码已修改')
  } catch (error) {
    toast.error('修改密码失败', { description: errorMessage(error) })
  } finally {
    passwordSaving.value = false
  }
}

// ---- 更新 ----
const checkingUpdate = ref(false)
const manualCheck = async () => {
  checkingUpdate.value = true
  try {
    await checkUpdate()
    if (updateState.value.hasUpdate) toast.info(`发现新版本 v${updateState.value.latest}`)
    else toast.success('当前已是最新版本')
  } finally {
    checkingUpdate.value = false
  }
}
const currentVersion = ref('')

onMounted(async () => {
  nickname.value = user.value?.full_name ?? ''
  await Promise.all([load(), loadConsent()])
  try {
    const info = await $api<{ version: string }>('/system/version')
    currentVersion.value = info.version.replace(/^v/, '')
  } catch {
    currentVersion.value = updateState.value.current.replace(/^v/, '')
  }
})
</script>

<template>
  <div class="grid gap-6">
    <Card>
      <CardHeader>
        <CardTitle class="text-base">练习</CardTitle>
        <CardDescription>调整刷题时的默认行为。</CardDescription>
      </CardHeader>
      <CardContent class="space-y-5">
        <div class="flex flex-wrap items-center justify-between gap-4">
          <Label for="pref-per-round">每轮题量</Label>
          <select
            id="pref-per-round"
            :class="selectClass"
            :value="preferences.questions_per_round"
            @change="savePreference('questions_per_round', Number(($event.target as HTMLSelectElement).value))"
          >
            <option v-for="n in QUESTIONS_PER_ROUND_OPTIONS" :key="n" :value="n">{{ n }} 题</option>
          </select>
        </div>
        <div class="flex flex-wrap items-center justify-between gap-4">
          <Label for="pref-mode">默认练习模式</Label>
          <select
            id="pref-mode"
            :class="selectClass"
            :value="preferences.default_mode"
            @change="savePreference('default_mode', ($event.target as HTMLSelectElement).value as UserPreferences['default_mode'])"
          >
            <option value="sequential">顺序刷题</option>
            <option value="random">乱序刷题</option>
            <option value="wrong">错题练习</option>
          </select>
        </div>
        <div class="flex items-center justify-between gap-4">
          <div class="space-y-0.5">
            <Label>答题后立即显示解析</Label>
            <p class="text-sm text-muted-foreground">关闭后需手动点击才显示参考答案与解析。</p>
          </div>
          <Switch :model-value="preferences.show_explanation_immediately" @update:model-value="savePreference('show_explanation_immediately', $event)" />
        </div>
        <div class="flex items-center justify-between gap-4">
          <div class="space-y-0.5">
            <Label>选项乱序</Label>
            <p class="text-sm text-muted-foreground">选择题的选项以随机顺序显示。</p>
          </div>
          <Switch :model-value="preferences.shuffle_options" @update:model-value="savePreference('shuffle_options', $event)" />
        </div>
        <div class="flex items-center justify-between gap-4">
          <div class="space-y-0.5">
            <Label>计时提示</Label>
            <p class="text-sm text-muted-foreground">答题时显示本题已用时间。</p>
          </div>
          <Switch :model-value="preferences.timer_hint" @update:model-value="savePreference('timer_hint', $event)" />
        </div>
      </CardContent>
    </Card>

    <Card>
      <CardHeader>
        <CardTitle class="text-base">外观</CardTitle>
      </CardHeader>
      <CardContent class="space-y-5">
        <div class="flex flex-wrap items-center justify-between gap-4">
          <Label for="pref-theme">主题</Label>
          <select
            id="pref-theme"
            :class="selectClass"
            :value="preferences.theme"
            @change="savePreference('theme', ($event.target as HTMLSelectElement).value as UserPreferences['theme'])"
          >
            <option value="auto">跟随系统</option>
            <option value="light">浅色</option>
            <option value="dark">深色</option>
          </select>
        </div>
        <div class="flex flex-wrap items-center justify-between gap-4">
          <Label for="pref-font">字体大小</Label>
          <select
            id="pref-font"
            :class="selectClass"
            :value="preferences.font_size"
            @change="savePreference('font_size', ($event.target as HTMLSelectElement).value as UserPreferences['font_size'])"
          >
            <option value="small">小</option>
            <option value="medium">中</option>
            <option value="large">大</option>
          </select>
        </div>
      </CardContent>
    </Card>

    <Card>
      <CardHeader>
        <CardTitle class="text-base">数据</CardTitle>
      </CardHeader>
      <CardContent class="space-y-5">
        <div v-if="telemetryEnabled" class="flex items-center justify-between gap-4">
          <div class="space-y-0.5">
            <Label>允许数据传输</Label>
            <p class="text-sm text-muted-foreground">可随时撤回或重新同意。</p>
          </div>
          <Switch :model-value="telemetryConsent" :disabled="telemetrySaving" @update:model-value="onToggleConsent" />
        </div>
        <div class="flex flex-wrap items-center justify-between gap-4">
          <Label>导出我的作答记录</Label>
          <div class="flex gap-2">
            <Button variant="outline" size="sm" :disabled="exporting" @click="exportHistory('csv')">导出 CSV</Button>
            <Button variant="outline" size="sm" :disabled="exporting" @click="exportHistory('json')">导出 JSON</Button>
          </div>
        </div>
        <div class="flex flex-wrap items-center justify-between gap-4">
          <div class="space-y-0.5">
            <Label>清空作答记录</Label>
            <p class="text-sm text-muted-foreground">只删除你自己的作答记录，错题本保留。</p>
          </div>
          <Button variant="destructive" size="sm" :disabled="clearing" @click="clearHistory">清空记录</Button>
        </div>
      </CardContent>
    </Card>

    <Card>
      <CardHeader>
        <CardTitle class="text-base">账户</CardTitle>
      </CardHeader>
      <CardContent class="space-y-6">
        <div class="space-y-2">
          <Label for="pref-nickname">昵称</Label>
          <div class="flex max-w-md gap-2">
            <Input id="pref-nickname" v-model="nickname" maxlength="64" />
            <Button :disabled="nicknameSaving" @click="saveNickname">保存</Button>
          </div>
        </div>
        <div class="max-w-md space-y-2">
          <Label>修改密码</Label>
          <Input v-model="currentPassword" type="password" autocomplete="current-password" placeholder="当前密码" />
          <Input v-model="newPassword" type="password" autocomplete="new-password" placeholder="新密码（至少 6 位）" />
          <Input v-model="confirmPassword" type="password" autocomplete="new-password" placeholder="再次输入新密码" />
          <p v-if="confirmPassword && newPassword !== confirmPassword" class="text-sm text-destructive">两次输入的新密码不一致</p>
          <Button :disabled="!canChangePassword || passwordSaving" @click="changePassword">修改密码</Button>
        </div>
      </CardContent>
    </Card>

    <Card>
      <CardHeader>
        <CardTitle class="text-base">更新</CardTitle>
      </CardHeader>
      <CardContent class="space-y-5">
        <div class="flex items-center justify-between gap-4">
          <Label>启动时自动检查更新</Label>
          <Switch :model-value="preferences.auto_check_update" @update:model-value="savePreference('auto_check_update', $event)" />
        </div>
        <div class="flex flex-wrap items-center justify-between gap-4">
          <span class="text-sm">当前版本 <span class="font-mono">v{{ currentVersion || '—' }}</span></span>
          <Button variant="outline" size="sm" :disabled="checkingUpdate" @click="manualCheck">检查更新</Button>
        </div>
      </CardContent>
    </Card>
  </div>
</template>
