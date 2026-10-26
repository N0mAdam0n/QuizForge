<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { useLocalStorage } from '@vueuse/core'
import { toast } from 'vue-sonner'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

interface ConsentStatus {
  enabled: boolean
  consent: boolean
}

const { $api } = useNuxtApp()
const { token } = useAuth()
const open = ref(false)
const enabled = ref(true)
const consent = useState<boolean>('telemetry-consent', () => false)
const checked = ref(false)
const saving = ref(false)
const decision = useLocalStorage<'accepted' | 'declined' | ''>(
  'telemetry-consent-decision',
  '',
)

const saveServerConsent = async () => {
  if (!token.value) return false
  saving.value = true
  try {
    const status = await $api<ConsentStatus>('/telemetry/consent', {
      method: 'PUT',
      body: { consent: true },
    })
    enabled.value = status.enabled
    consent.value = status.consent
    if (!status.consent) return false
    decision.value = 'accepted'
    open.value = false
    return true
  } catch (error) {
    toast.error('保存同意状态失败', {
      description: error instanceof Error ? error.message : '请稍后重试。',
    })
    return false
  } finally {
    saving.value = false
  }
}

const loadStatus = async () => {
  if (!token.value) {
    if (decision.value === '') open.value = true
    return
  }
  try {
    const status = await $api<ConsentStatus>('/telemetry/consent')
    enabled.value = status.enabled
    consent.value = status.consent
    if (!status.enabled) return
    if (status.consent) {
      checked.value = true
      decision.value = 'accepted'
      open.value = false
      return
    }
    if (decision.value === 'accepted') {
      await saveServerConsent()
      return
    }
    if (decision.value !== 'declined') open.value = true
  } catch (error) {
    toast.error('无法读取数据收集同意状态', {
      description: error instanceof Error ? error.message : '请稍后重试。',
    })
  }
}

const accept = async () => {
  if (!checked.value) return
  decision.value = 'accepted'
  if (token.value) await saveServerConsent()
  else open.value = false
}

const decline = () => {
  decision.value = 'declined'
  open.value = false
}

const withdraw = async () => {
  saving.value = true
  try {
    const status = await $api<ConsentStatus>('/telemetry/consent', {
      method: 'PUT',
      body: { consent: false },
    })
    enabled.value = status.enabled
    consent.value = false
    decision.value = 'declined'
    open.value = false
    toast.success('已撤回本实例的数据收集同意并清除待上传数据')
  } catch (error) {
    toast.error('撤回同意失败', {
      description: error instanceof Error ? error.message : '请稍后重试。',
    })
  } finally {
    saving.value = false
  }
}

const handleOpenChange = (value: boolean) => {
  open.value = value
  if (!value && !consent.value && decision.value === '') {
    decision.value = 'declined'
  }
  if (value) checked.value = consent.value
}

const handleOpenRequest = () => {
  checked.value = consent.value
  open.value = true
}

onMounted(() => {
  void loadStatus()
  window.addEventListener('open-telemetry-consent', handleOpenRequest)
})

watch(token, (value, previous) => {
  if (value && !previous) void loadStatus()
})

onUnmounted(() => {
  window.removeEventListener('open-telemetry-consent', handleOpenRequest)
})
</script>

<template>
  <Dialog :open="open" @update:open="handleOpenChange">
    <DialogContent class="max-h-[90vh] max-w-2xl overflow-y-auto">
      <DialogHeader>
        <DialogTitle>匿名使用数据收集声明</DialogTitle>
        <DialogDescription>
          {{ consent ? '当前后端实例已启用数据收集。' : '请阅读说明并自行选择是否同意。默认未勾选，不同意不影响软件使用。' }}
        </DialogDescription>
      </DialogHeader>

      <div class="space-y-3 text-sm leading-6 text-muted-foreground">
        <p>
          <strong class="text-foreground">我们会收集：</strong>
          仅在你同意后，收集软件版本、操作系统与语言设置，以及解析质量、题型和数量、处理耗时、练习正误与耗时、审核修改类别等匿名统计信息。题目和任务标识会在本机处理后以摘要形式上报，用于改进软件质量。
        </p>
        <p>
          <strong class="text-foreground">我们不会收集：</strong>
          不会通过这项统计上传题干、选项、答案、解析原文、导入文件内容或文件名，也不会收集姓名、联系方式等直接身份信息，或将剪贴板内容用于统计。服务器常规网络访问日志可能记录连接 IP。
        </p>
        <p>
          <strong class="text-foreground">匿名机器标识：</strong>
          为了统计真实用户人数（同一台电脑重装软件不重复计算），我们会读取本机 Windows 的机器码（MachineGuid），在本机用固定密钥做不可逆的 HMAC-SHA256 摘要后，仅上传这个摘要，不上传机器码原文。非 Windows 系统或读取失败时，改用本机随机生成的标识。该摘要会随注册信息和每条统计数据一起上传，用于把同一台电脑的数据关联起来。
        </p>
        <p>
          是否同意由你决定，不同意不影响使用；同意后可随时从用户菜单中的“数据收集声明”撤回。
        </p>
      </div>

      <label v-if="!consent" class="flex cursor-pointer items-start gap-3 rounded-md border p-3 text-sm">
        <input v-model="checked" type="checkbox" class="mt-1 size-4 accent-primary">
        <span>我已阅读并同意上述匿名使用数据收集说明</span>
      </label>

      <DialogFooter class="gap-2">
        <template v-if="consent">
          <Button variant="outline" :disabled="saving" @click="handleOpenChange(false)">关闭</Button>
          <Button variant="destructive" :disabled="saving" @click="withdraw">撤回同意并清除数据</Button>
        </template>
        <template v-else>
          <Button variant="outline" :disabled="saving" @click="decline">暂不同意</Button>
          <Button :disabled="saving || !checked || !enabled" @click="accept">同意并开始收集</Button>
        </template>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
