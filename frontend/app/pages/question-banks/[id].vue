<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ArrowLeft, Loader2, Pencil, Trash2 } from '@lucide/vue'
import { toast } from 'vue-sonner'
import PageHeader from '@/components/PageHeader.vue'
import QuestionEditDialog from '@/components/QuestionEditDialog.vue'
import RichContent from '@/components/rich-editor/RichContent.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import type { Question, QuestionPage, Subject, KnowledgePoint } from '@/types'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

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

const route = useRoute()
const router = useRouter()
const { $api } = useNuxtApp()
const { currentSubjectId, init: initSubject } = useSubjectContext()
const bankId = Number(route.params.id)
const bank = ref<ManagedQuestionBank | null>(null)
const questionPage = ref<QuestionPage | null>(null)
const subjects = ref<Subject[]>([])
const knowledgePoints = ref<KnowledgePoint[]>([])
const editingQuestion = ref<Question | null>(null)
const loading = ref(false)
const publishing = ref(false)
const error = ref<string | null>(null)
const requestId = ref(0)
const questionTypes: Record<string, string> = {
  single_choice: '单选题',
  multiple_choice: '多选题',
  true_false: '判断题',
  fill_in_the_blank: '填空题',
  free_response: '解答题',
}

const questions = computed(() => questionPage.value?.items ?? [])

const loadBank = async () => {
  const request = ++requestId.value
  if (!Number.isSafeInteger(bankId) || bankId <= 0 || !currentSubjectId.value) return
  loading.value = true
  error.value = null
  try {
    const [bankInfo, page, subjectList, kpList] = await Promise.all([
      $api<ManagedQuestionBank>('/practice/manage-question-banks/' + bankId, {
        query: { subject_id: currentSubjectId.value },
      }),
      $api<QuestionPage>('/questions', {
        query: { import_task_id: bankId, subject_id: currentSubjectId.value, page: 1, size: 500 },
      }),
      $api<Subject[]>('/subjects'),
      $api<KnowledgePoint[]>('/knowledge-points', {
        query: { subject_id: currentSubjectId.value, limit: -1 },
      }),
    ])
    if (request !== requestId.value) return
    bank.value = bankInfo
    questionPage.value = page
    subjects.value = subjectList
    knowledgePoints.value = kpList
  } catch (cause: any) {
    if (request !== requestId.value) return
    error.value = cause?.data?.detail || cause?.message || '读取题库失败'
  } finally {
    if (request === requestId.value) loading.value = false
  }
}

watch(currentSubjectId, loadBank)
await initSubject()
await loadBank()

const publishBank = async () => {
  if (!bank.value || publishing.value) return
  publishing.value = true
  try {
    bank.value = await $api<ManagedQuestionBank>(`/practice/question-banks/${bank.value.id}/publish`, {
      method: 'POST',
    })
    await loadBank()
    toast.success('题库已发布', { description: '有答案的题目现已可用于刷题。' })
  } catch (cause: any) {
    toast.error('发布题库失败', {
      description: cause?.data?.detail || cause?.message || '请稍后重试。',
    })
  } finally {
    publishing.value = false
  }
}

const editQuestion = (question: Question) => { editingQuestion.value = question }

const changeScope = async (scope: string) => {
  if (!bank.value || (scope !== 'personal' && scope !== 'shared') || bank.value.scope === scope) return
  try {
    await $api(`/practice/question-banks/${bank.value.id}/scope`, {
      method: 'PUT',
      body: { scope },
    })
    await loadBank()
    toast.success(scope === 'personal' ? '题库已移入个人空间' : '题库已移入共享空间', {
      description: scope === 'shared'
        ? '共享题目需要重新审核后才可练习。'
        : '符合条件的题目已在个人空间发布。',
    })
  } catch (cause: any) {
    toast.error('更改题库空间失败', {
      description: cause?.data?.detail || cause?.message || '请稍后重试。',
    })
  }
}

const reviewQuestion = async (question: Question) => {
  try {
    await $api(`/questions/${question.id}/review`, {
      method: 'POST',
      body: { action: 'approve', comment: '从共享题库审核通过' },
    })
    toast.success('题目审核已提交')
    await loadBank()
  } catch (cause: any) {
    toast.error('审核题目失败', {
      description: cause?.data?.detail || cause?.message || '请稍后重试。',
    })
  }
}

const deleteQuestion = async (question: Question) => {
  if (!window.confirm('确定从此题库中移除这道题吗？')) return
  try {
    await $api(`/questions/${question.id}`, { method: 'DELETE' })
    toast.success('题目已从题库移除')
    await loadBank()
  } catch (cause: any) {
    toast.error('移除题目失败', {
      description: cause?.data?.detail || cause?.message || '请稍后重试。',
    })
  }
}
</script>

<template>
  <div class="flex flex-1 flex-col">
    <PageHeader :title="bank?.original_filename || '题库详情'">
      <template #actions>
        <Button variant="ghost" size="sm" @click="router.push('/question-banks')">
          <ArrowLeft class="mr-2 h-4 w-4" />我的题库
        </Button>
      </template>
    </PageHeader>
    <main class="mx-auto w-full max-w-5xl space-y-5 p-4 sm:p-6">
      <Card v-if="loading && !bank">
        <CardContent class="flex items-center justify-center gap-2 py-12 text-sm text-muted-foreground">
          <Loader2 class="h-4 w-4 animate-spin" />正在读取题库…
        </CardContent>
      </Card>
      <Card v-else-if="error && !bank">
        <CardContent class="space-y-3 py-10 text-center">
          <p class="text-sm text-destructive">{{ error }}</p>
          <Button variant="outline" @click="loadBank">重试</Button>
        </CardContent>
      </Card>
      <template v-else-if="bank">
        <Card>
          <CardContent class="flex flex-wrap items-center justify-between gap-4 p-5">
            <div class="space-y-1">
              <div class="flex flex-wrap items-center gap-2">
                <Badge :variant="bank.publication_status === 'published' ? 'default' : 'secondary'">
                  {{ bank.publication_status === 'published' ? '已发布' : bank.scope === 'personal' ? '待发布' : '待审核' }}
                </Badge>
                <Select :model-value="bank.scope" :disabled="!bank.can_edit" @update:model-value="changeScope">
                  <SelectTrigger class="h-7 w-[120px]"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="personal">个人空间</SelectItem>
                    <SelectItem value="shared">共享空间</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <p class="text-sm text-muted-foreground">
                {{ bank.question_count }} 道题 · {{ bank.published_count }} 道已发布
              </p>
            </div>
            <Button
              v-if="bank.publication_status === 'pending' && bank.scope === 'personal' && bank.can_edit"
              :disabled="publishing"
              @click="publishBank"
            >
              {{ publishing ? '正在发布…' : '发布整个题库' }}
            </Button>
          </CardContent>
        </Card>

        <div class="flex items-center justify-between gap-3">
          <div>
            <h2 class="text-lg font-semibold">题库内容</h2>
            <p class="text-sm text-muted-foreground">在这里查看、修改或移除本题库中的题目。</p>
          </div>
          <Badge variant="secondary">{{ questions.length }} 道</Badge>
        </div>

        <Card v-if="questions.length === 0">
          <CardContent class="py-10 text-center text-sm text-muted-foreground">该题库目前没有题目。</CardContent>
        </Card>
        <div v-else class="space-y-3">
          <Card v-for="(question, index) in questions" :key="question.id">
            <CardHeader class="flex flex-row items-start justify-between gap-3 space-y-0 pb-3">
              <div class="flex min-w-0 items-center gap-2">
                <Badge variant="outline">{{ questionTypes[question.q_type] || question.q_type }}</Badge>
                <Badge :variant="question.status === 'published' ? 'default' : 'secondary'">
                  {{ question.status === 'published' ? '已发布' : question.status === 'pending' ? '待发布' : '草稿' }}
                </Badge>
                <CardDescription>第 {{ index + 1 }} 题</CardDescription>
              </div>
              <div v-if="bank.can_edit" class="flex shrink-0 gap-1">
                <Button
                  v-if="bank.scope === 'shared' && question.status === 'pending'"
                  variant="outline"
                  size="sm"
                  @click="reviewQuestion(question)"
                >
                  审核通过
                </Button>
                <Button variant="ghost" size="icon" aria-label="编辑题目" @click="editQuestion(question)">
                  <Pencil class="h-4 w-4" />
                </Button>
                <Button variant="ghost" size="icon" aria-label="移除题目" @click="deleteQuestion(question)">
                  <Trash2 class="h-4 w-4 text-destructive" />
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              <RichContent :content="question.content" />
            </CardContent>
          </Card>
        </div>
        <QuestionEditDialog
          :open="!!editingQuestion"
          :question="editingQuestion"
          :subjects="subjects"
          :knowledge-points="knowledgePoints"
          :auto-fill-subject-id="currentSubjectId"
          mode="edit"
          @update:open="(open) => !open && (editingQuestion = null)"
          @success="() => { editingQuestion = null; loadBank() }"
        />
      </template>
    </main>
  </div>
</template>
