<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { AlertCircle, BookOpen, Loader2, RefreshCw } from '@lucide/vue'
import { toast } from 'vue-sonner'
import AnswerDisplay from '@/components/AnswerDisplay.vue'
import PageHeader from '@/components/PageHeader.vue'
import RichContent from '@/components/rich-editor/RichContent.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import type { AnswerSpec, OptionSpec, QuestionType, RichDoc } from '@/types'

definePageMeta({ layout: 'default' })

interface WrongBookItem {
  id: number
  subject_id: number
  import_task_id: number | null
  original_filename: string | null
  content: RichDoc
  q_type: QuestionType
  options: OptionSpec[]
  answer: AnswerSpec | null
  analysis: RichDoc
  last_wrong_at: string
  wrong_count: number
}

const { $api } = useNuxtApp()
const items = ref<WrongBookItem[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const pageSize = 100
const hasMore = ref(false)
const nextOffset = ref(0)
const labels: Record<QuestionType, string> = {
  single_choice: '单选题',
  multiple_choice: '多选题',
  true_false: '判断题',
  fill_in_the_blank: '填空题',
  free_response: '解答题',
}

const loadWrongBook = async (reset = true) => {
  loading.value = true
  error.value = null
  try {
    const page = await $api<WrongBookItem[]>('/practice/wrong-book', {
      query: { limit: pageSize, offset: reset ? 0 : nextOffset.value },
    })
    nextOffset.value = (reset ? 0 : nextOffset.value) + page.length
    items.value = reset
      ? page
      : [...items.value, ...page.filter((item) => !items.value.some((existing) => existing.id === item.id))]
    hasMore.value = page.length === pageSize
  } catch (cause: any) {
    error.value = cause?.data?.detail || cause?.message || '读取错题本失败'
    toast.error('读取错题本失败', { description: error.value })
  } finally {
    loading.value = false
  }
}

onMounted(loadWrongBook)
</script>

<template>
  <div class="flex flex-1 flex-col">
    <PageHeader title="错题本">
      <template #actions>
        <Button variant="outline" size="sm" :disabled="loading" @click="loadWrongBook()">
          <RefreshCw class="mr-2 h-4 w-4" />刷新
        </Button>
      </template>
    </PageHeader>
    <main class="mx-auto w-full max-w-4xl space-y-5 p-4 sm:p-6">
      <div class="space-y-1">
        <h1 class="text-2xl font-bold tracking-tight">我的错题本</h1>
        <p class="text-sm text-muted-foreground">来自所有可访问题库的错题会自动汇总到这里，并显示正确答案。</p>
      </div>
      <p v-if="error && items.length" class="text-sm text-destructive">{{ error }}</p>

      <Card v-if="loading && items.length === 0">
        <CardContent class="flex items-center justify-center gap-2 py-12 text-sm text-muted-foreground">
          <Loader2 class="h-4 w-4 animate-spin" />正在读取错题…
        </CardContent>
      </Card>
      <Card v-else-if="error && items.length === 0">
        <CardContent class="space-y-3 py-10 text-center">
          <p class="text-sm text-destructive">{{ error }}</p>
          <Button variant="outline" @click="loadWrongBook()">重试</Button>
        </CardContent>
      </Card>
      <Card v-else-if="items.length === 0">
        <CardContent class="space-y-3 py-12 text-center">
          <BookOpen class="mx-auto h-10 w-10 text-muted-foreground" />
          <p class="font-medium">错题本还是空的</p>
          <p class="text-sm text-muted-foreground">在任意题库中答错或选择“我不知道”，题目就会自动收录。</p>
        </CardContent>
      </Card>
      <div v-else class="space-y-4">
        <Card v-for="item in items" :key="item.id">
          <CardHeader class="space-y-2">
            <div class="flex flex-wrap items-center gap-2">
              <Badge variant="outline">{{ labels[item.q_type] }}</Badge>
              <Badge variant="destructive">
                <AlertCircle class="mr-1 h-3.5 w-3.5" />错 {{ item.wrong_count }} 次
              </Badge>
              <CardDescription>{{ item.original_filename || '题库' }} · {{ new Date(item.last_wrong_at).toLocaleString() }}</CardDescription>
            </div>
            <CardTitle class="sr-only">错题 {{ item.id }}</CardTitle>
          </CardHeader>
          <CardContent class="space-y-4">
            <RichContent :content="item.content" />
            <div v-if="item.options?.length" class="space-y-2">
              <div v-for="option in item.options" :key="option.id" class="flex gap-2 text-sm">
                <span class="font-medium">{{ option.label }}.</span>
                <RichContent :content="option.content" />
              </div>
            </div>
            <div class="space-y-2 border-t pt-4">
              <p class="text-sm font-semibold">正确答案</p>
              <AnswerDisplay :answer="item.answer" :options="item.options" />
            </div>
            <div v-if="item.analysis" class="space-y-2 border-t pt-4">
              <p class="text-sm font-semibold">解析</p>
              <RichContent :content="item.analysis" />
            </div>
            <Button
              v-if="item.import_task_id"
              as-child
              variant="link"
              size="sm"
              class="h-auto p-0"
            >
              <NuxtLink :to="`/question-banks/${item.import_task_id}`">查看所属题库</NuxtLink>
            </Button>
          </CardContent>
        </Card>
        <div v-if="hasMore" class="flex justify-center">
          <Button variant="outline" :disabled="loading" @click="loadWrongBook(false)">
            {{ loading ? '正在加载…' : '加载更多错题' }}
          </Button>
        </div>
      </div>
    </main>
  </div>
</template>
