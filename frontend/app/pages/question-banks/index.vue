<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { BookOpen, Loader2, Plus, Pencil, RefreshCw } from '@lucide/vue'
import { toast } from 'vue-sonner'
import PageHeader from '@/components/PageHeader.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

definePageMeta({ layout: 'default' })

interface ManagedQuestionBank {
  id: number
  original_filename: string
  scope: 'personal' | 'shared'
  publication_status: 'pending' | 'published'
  question_count: number
  published_count: number
  created_at: string
  can_edit: boolean
}

const { $api } = useNuxtApp()
const { currentSubjectId, currentSubject, init: initSubject } = useSubjectContext()
const banks = ref<ManagedQuestionBank[]>([])
const scope = ref<'personal' | 'shared'>('personal')
const loading = ref(false)
const error = ref<string | null>(null)
const requestId = ref(0)

const loadBanks = async () => {
  const request = ++requestId.value
  if (!currentSubjectId.value) {
    banks.value = []
    return
  }
  loading.value = true
  error.value = null
  try {
    const result = await $api<ManagedQuestionBank[]>('/practice/manage-question-banks', {
      query: { scope: scope.value, subject_id: currentSubjectId.value },
    })
    if (request === requestId.value) banks.value = result
  } catch (cause: any) {
    if (request !== requestId.value) return
    error.value = cause?.data?.detail || cause?.message || '读取个人题库失败'
    toast.error('读取个人题库失败', { description: error.value || undefined })
  } finally {
    if (request === requestId.value) loading.value = false
  }
}

watch([currentSubjectId, scope], loadBanks)
await initSubject()
await loadBanks()

const pendingCount = computed(() =>
  banks.value.filter((bank) => bank.publication_status === 'pending').length,
)
</script>

<template>
  <div class="flex flex-1 flex-col">
    <PageHeader title="我的题库">
      <template #actions>
        <Button as-child size="sm">
          <NuxtLink to="/import/smart"><Plus class="mr-2 h-4 w-4" />导入题库</NuxtLink>
        </Button>
      </template>
    </PageHeader>
    <main class="mx-auto w-full max-w-5xl space-y-6 p-4 sm:p-6">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 class="text-2xl font-bold tracking-tight">个人题库</h1>
          <p class="mt-1 text-sm text-muted-foreground">
            {{ currentSubject?.name || '当前学科' }} · 每份导入文档独立保存为一个题库
          </p>
        </div>
        <div class="flex gap-2">
          <Button
            v-for="option in [{ value: 'personal', label: '个人空间' }, { value: 'shared', label: '共享空间' }] as const"
            :key="option.value"
            size="sm"
            :variant="scope === option.value ? 'default' : 'outline'"
            @click="scope = option.value"
          >
            {{ option.label }}
          </Button>
        </div>
        <div class="flex items-center gap-2">
        <Badge v-if="pendingCount" variant="secondary">
          {{ pendingCount }} 个{{ scope === 'personal' ? '待发布' : '待审核' }}
        </Badge>
          <Button variant="outline" size="sm" :disabled="loading" @click="loadBanks">
            <RefreshCw class="mr-2 h-4 w-4" />刷新
          </Button>
        </div>
      </div>

      <Card v-if="loading && banks.length === 0">
        <CardContent class="flex items-center justify-center gap-2 py-12 text-sm text-muted-foreground">
          <Loader2 class="h-4 w-4 animate-spin" />正在读取题库…
        </CardContent>
      </Card>
      <Card v-else-if="error && banks.length === 0">
        <CardContent class="space-y-3 py-10 text-center">
          <p class="text-sm text-destructive">{{ error }}</p>
          <Button variant="outline" @click="loadBanks">重试</Button>
        </CardContent>
      </Card>
      <Card v-else-if="banks.length === 0">
        <CardContent class="space-y-4 py-12 text-center">
          <BookOpen class="mx-auto h-10 w-10 text-muted-foreground" />
          <div class="space-y-1">
            <p class="font-medium">此空间还没有题库</p>
            <p class="text-sm text-muted-foreground">导入并审核一份题库文档，它会作为独立题库保存在这里。</p>
          </div>
          <Button as-child><NuxtLink to="/import/smart">导入第一份题库</NuxtLink></Button>
        </CardContent>
      </Card>
      <div v-else class="grid gap-3">
        <Card v-for="bank in banks" :key="bank.id">
          <CardHeader class="flex flex-row items-start justify-between gap-4 space-y-0">
            <div class="min-w-0 space-y-1">
              <CardTitle class="truncate text-base">{{ bank.original_filename }}</CardTitle>
              <CardDescription>
                {{ bank.question_count }} 道题 · 导入于 {{ new Date(bank.created_at).toLocaleDateString() }}
              </CardDescription>
            </div>
            <Badge :variant="bank.publication_status === 'published' ? 'default' : 'secondary'">
              {{ bank.publication_status === 'published' ? '已发布' : bank.scope === 'personal' ? '待发布' : '待审核' }}
            </Badge>
          </CardHeader>
          <CardContent class="flex justify-end pt-0">
            <Button as-child variant="outline" size="sm">
              <NuxtLink :to="`/question-banks/${bank.id}`">
                <Pencil class="mr-2 h-4 w-4" />修改题库
              </NuxtLink>
            </Button>
          </CardContent>
        </Card>
      </div>
    </main>
  </div>
</template>
