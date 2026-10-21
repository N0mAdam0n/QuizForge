<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { AlertCircle, ArrowLeft, ArrowRight, Check, CircleHelp, Lock, RotateCcw, Shuffle, Users } from '@lucide/vue'
import { toast } from 'vue-sonner'
import AnswerDisplay from '@/components/AnswerDisplay.vue'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Switch } from '@/components/ui/switch'
import RichContent from '@/components/rich-editor/RichContent.vue'
import type { AnswerSpec, OptionSpec, QuestionType, RichDoc } from '@/types'
import { collectBlankIds } from '@/components/rich-editor/richDoc'

definePageMeta({ layout: 'default' })

type PracticeMode = 'sequential' | 'random' | 'type' | 'wrong'
type PracticeScope = 'personal' | 'shared'

interface PracticeQuestionBank {
  id: number
  original_filename: string
  scope: PracticeScope
  question_count: number
}

interface PracticeQuestion {
  id: number
  content: RichDoc
  q_type: QuestionType
  options: OptionSpec[]
  difficulty: number
  blank_count: number
}

interface PracticeQuestionSet {
  mode: PracticeMode
  questions: PracticeQuestion[]
  total_count: number
  has_more: boolean
  next_offset: number
}

interface PracticeAnswerResult {
  question_id: number
  is_correct: boolean | null
  score: number | null
  requires_self_assessment: boolean
  correct_answer: AnswerSpec | null
  analysis: RichDoc
  dont_know: boolean
}

const { $api } = useNuxtApp()
const { currentSubjectId, currentSubject, subjects, init: initSubject } = useSubjectContext()

const practiceScope = ref<PracticeScope>('personal')
const banks = ref<PracticeQuestionBank[]>([])
const selectedBankId = ref<number | null>(null)
const banksLoading = ref(false)
const banksError = ref<string | null>(null)
const mode = ref<PracticeMode>('sequential')
const selectedType = ref<QuestionType>('single_choice')
const autoAdvanceCorrect = useCookie<boolean>('practice-auto-advance-correct', {
  default: () => false,
})
const autoAdvancePending = ref(false)
const questionSet = ref<PracticeQuestionSet | null>(null)
const questionIndex = ref(0)
const questionOffset = ref(0)
const practiceSubjectId = ref<number | null>(null)
const practiceBankId = ref<number | null>(null)
const practiceSubject = computed(
  () => subjects.value.find((subject) => subject.id === practiceSubjectId.value) ?? currentSubject.value,
)
const loading = ref(false)
const submitting = ref(false)
const error = ref<string | null>(null)
const answerResults = ref<Record<number, PracticeAnswerResult>>({})
const submittedAnswers = ref<Record<number, string | string[] | boolean | null>>({})
interface PracticeDraft {
  selectedOptionIds: string[]
  selectedBoolean: boolean | null
  blankAnswers: string[]
  responseText: string
  selfAssessed: boolean | null
}
const answerDrafts = ref<Record<number, PracticeDraft>>({})
const selectedOptionIds = ref<string[]>([])
const selectedBoolean = ref<boolean | null>(null)
const blankAnswers = ref<string[]>([])
const responseText = ref('')
const selfAssessed = ref<boolean | null>(null)

const currentQuestion = computed(
  () => questionSet.value?.questions[questionIndex.value] ?? null,
)
const totalQuestions = computed(() => questionSet.value?.questions.length ?? 0)
const blankIds = computed(() => collectBlankIds(currentQuestion.value?.content ?? null))
const blankCount = computed(() => Math.max(blankIds.value.length, currentQuestion.value?.blank_count ?? 0))
const hasStarted = computed(() => questionSet.value !== null)
const answerSheetCount = computed(
  () => questionSet.value?.total_count || totalQuestions.value,
)
const selectedBank = computed(
  () => banks.value.find((bank) => bank.id === (practiceBankId.value ?? selectedBankId.value)) ?? null,
)
const answerResult = computed(() => {
  const questionId = currentQuestion.value?.id
  return questionId == null ? null : answerResults.value[questionId] ?? null
})
const modeLabels: Record<PracticeMode, string> = {
  sequential: '顺序刷题',
  random: '乱序刷题',
  type: '按题型刷题',
  wrong: '错题练习',
}
const typeLabels: Record<QuestionType, string> = {
  single_choice: '单选题',
  multiple_choice: '多选题',
  true_false: '判断题',
  fill_in_the_blank: '填空题',
  free_response: '解答题',
}
let autoAdvanceTimer: ReturnType<typeof setTimeout> | null = null

const clearAutoAdvanceTimer = () => {
  if (autoAdvanceTimer !== null) {
    clearTimeout(autoAdvanceTimer)
    autoAdvanceTimer = null
  }
  autoAdvancePending.value = false
}

onBeforeUnmount(clearAutoAdvanceTimer)
watch(autoAdvanceCorrect, (enabled) => {
  if (!enabled) clearAutoAdvanceTimer()
})

const resetAnswer = (question = currentQuestion.value) => {
  const draft = question ? answerDrafts.value[question.id] : null
  selectedOptionIds.value = draft?.selectedOptionIds ?? []
  selectedBoolean.value = draft?.selectedBoolean ?? null
  blankAnswers.value = draft?.blankAnswers ?? Array.from({ length: blankCount.value }, () => '')
  responseText.value = draft?.responseText ?? ''
  selfAssessed.value = draft?.selfAssessed ?? null
}

watch(currentQuestion, (question, previousQuestion) => {
  if (previousQuestion && !answerResults.value[previousQuestion.id]) {
    answerDrafts.value[previousQuestion.id] = {
      selectedOptionIds: selectedOptionIds.value,
      selectedBoolean: selectedBoolean.value,
      blankAnswers: blankAnswers.value,
      responseText: responseText.value,
      selfAssessed: selfAssessed.value,
    }
  }
  resetAnswer(question)
}, { immediate: true })

const startPractice = async () => {
  if (!currentSubjectId.value || !selectedBankId.value) {
    toast.error('请先选择学科')
    return
  }
  loading.value = true
  error.value = null
  questionOffset.value = 0
  clearAutoAdvanceTimer()
  practiceSubjectId.value = currentSubjectId.value
  practiceBankId.value = selectedBankId.value
  try {
    const query: Record<string, string | number> = {
      subject_id: practiceSubjectId.value,
      scope: practiceScope.value,
      import_task_id: practiceBankId.value,
      mode: mode.value,
      limit: 20,
      offset: questionOffset.value,
    }
    if (mode.value === 'type') query.q_type = selectedType.value
    questionSet.value = await $api<PracticeQuestionSet>('/practice/questions', { query })
    questionIndex.value = 0
    if (questionSet.value.questions.length === 0) {
      toast.info(mode.value === 'wrong' ? '当前题库没有待练习的错题' : '当前题库中没有符合条件的已发布题目')
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载练习题目失败'
  } finally {
    loading.value = false
  }
}

const toggleOption = (optionId: string) => {
  if (currentQuestion.value?.q_type === 'single_choice') {
    selectedOptionIds.value = [optionId]
    return
  }
  selectedOptionIds.value = selectedOptionIds.value.includes(optionId)
    ? selectedOptionIds.value.filter((id) => id !== optionId)
    : [...selectedOptionIds.value, optionId]
}

const selectOption = (optionId: string) => {
  toggleOption(optionId)
  void submitAnswer()
}

const selectBoolean = (value: boolean) => {
  selectedBoolean.value = value
  void submitAnswer()
}

const canSubmit = computed(() => {
  if (!currentQuestion.value || answerResult.value || submitting.value) return false
  switch (currentQuestion.value.q_type) {
    case 'single_choice':
    case 'multiple_choice':
      return selectedOptionIds.value.length > 0
    case 'true_false':
      return selectedBoolean.value !== null
    case 'fill_in_the_blank':
      return blankAnswers.value.length > 0
        && blankAnswers.value.every((answer) => answer.trim())
        && selfAssessed.value !== null
    case 'free_response':
      return responseText.value.trim().length > 0 && selfAssessed.value !== null
  }
})

const submitAnswer = async (dontKnow = false) => {
  const question = currentQuestion.value
  if (
    !question
    || (!dontKnow && !canSubmit.value)
    || submitting.value
    || !questionSet.value
    || !practiceSubjectId.value
    || !practiceBankId.value
  ) return

  let answer: string | string[] | boolean | null = null
  if (!dontKnow) {
    if (question.q_type === 'single_choice') answer = selectedOptionIds.value[0] ?? null
    else if (question.q_type === 'multiple_choice') answer = selectedOptionIds.value
    else if (question.q_type === 'true_false') answer = selectedBoolean.value
    else if (question.q_type === 'fill_in_the_blank') answer = blankAnswers.value
    else answer = responseText.value
  }

  submitting.value = true
  error.value = null
  try {
    const result = await $api<PracticeAnswerResult>('/practice/answers', {
      method: 'POST',
      body: {
        question_id: question.id,
        subject_id: practiceSubjectId.value,
        scope: practiceScope.value,
        import_task_id: practiceBankId.value,
        mode: questionSet.value.mode,
        answer,
        self_assessed: ['fill_in_the_blank', 'free_response'].includes(question.q_type)
          ? selfAssessed.value
          : null,
        dont_know: dontKnow,
      },
    })
    submittedAnswers.value[question.id] = answer
    answerResults.value[question.id] = result
    if (result.is_correct === true && autoAdvanceCorrect.value) {
      clearAutoAdvanceTimer()
      autoAdvancePending.value = true
      autoAdvanceTimer = setTimeout(() => {
        autoAdvanceTimer = null
        autoAdvancePending.value = false
        if (
          autoAdvanceCorrect.value
          && currentQuestion.value?.id === question.id
          && answerResults.value[question.id]?.is_correct === true
        ) {
          void advanceQuestion()
        }
      }, 900)
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : '提交答案失败'
  } finally {
    submitting.value = false
  }
}

const loadMoreQuestions = async (): Promise<boolean> => {
  if (
    !questionSet.value?.has_more
    || !practiceSubjectId.value
    || !practiceBankId.value
    || loading.value
  ) return false

  loading.value = true
  error.value = null
  try {
    const query: Record<string, string | number> = {
      subject_id: practiceSubjectId.value,
      scope: practiceScope.value,
      import_task_id: practiceBankId.value,
      mode: questionSet.value.mode,
      limit: 20,
      offset: questionSet.value.next_offset,
    }
    if (questionSet.value.mode === 'type') query.q_type = selectedType.value
    const nextSet = await $api<PracticeQuestionSet>('/practice/questions', { query })
    questionSet.value = {
      ...nextSet,
      questions: [...questionSet.value.questions, ...nextSet.questions],
    }
    questionOffset.value = nextSet.next_offset
    return true
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载后续练习题失败'
    return false
  } finally {
    loading.value = false
  }
}

const goToQuestion = async (index: number) => {
  clearAutoAdvanceTimer()
  if (index < 0 || index >= answerSheetCount.value) return
  while (index >= totalQuestions.value && questionSet.value?.has_more) {
    if (!await loadMoreQuestions()) return
  }
  if (index < totalQuestions.value) questionIndex.value = index
}

const advanceQuestion = async () => {
  clearAutoAdvanceTimer()
  if (!questionSet.value) return
  if (questionIndex.value + 1 < totalQuestions.value) {
    questionIndex.value += 1
    return
  }
  if (questionSet.value.has_more && questionSet.value.mode !== 'random') {
    while (questionSet.value?.has_more) {
      const previousQuestionCount = totalQuestions.value
      if (!await loadMoreQuestions()) return
      if (totalQuestions.value > previousQuestionCount) {
        questionIndex.value += 1
        return
      }
    }
    questionIndex.value = totalQuestions.value
    return
  }
  questionIndex.value = totalQuestions.value
}

const questionStatus = (index: number) => {
  const question = questionSet.value?.questions[index]
  if (!question) return 'unloaded'
  const result = answerResults.value[question.id]
  if (result?.is_correct === true) return 'correct'
  if (result?.is_correct === false) return 'incorrect'
  if (answerDrafts.value[question.id]) return 'draft'
  if (index === questionIndex.value) {
    if (
      selectedOptionIds.value.length
      || selectedBoolean.value !== null
      || blankAnswers.value.some((value) => value.trim())
      || responseText.value.trim()
    ) return 'draft'
  }
  return 'unanswered'
}

const questionButtonClass = (index: number) => {
  const status = questionStatus(index)
  const statusClasses: Record<string, string> = {
    correct: 'border-emerald-300 bg-emerald-50 text-emerald-800 hover:bg-emerald-100',
    incorrect: 'border-destructive/40 bg-destructive/10 text-destructive hover:bg-destructive/15',
    draft: 'border-amber-300 bg-amber-50 text-amber-800 hover:bg-amber-100',
    unanswered: 'border-border bg-background text-muted-foreground hover:bg-muted',
    unloaded: 'border-dashed border-border bg-background text-muted-foreground hover:bg-muted',
  }
  return [
    'grid h-9 w-full place-items-center rounded-md border text-sm transition-colors',
    statusClasses[status],
    index === questionIndex.value ? 'ring-2 ring-primary ring-offset-1' : '',
  ]
}

const correctCount = computed(
  () => Object.values(answerResults.value).filter((result) => result.is_correct === true).length,
)
const incorrectCount = computed(
  () => Object.values(answerResults.value).filter((result) => result.is_correct === false).length,
)

const restartPractice = () => {
  clearAutoAdvanceTimer()
  questionSet.value = null
  questionIndex.value = 0
  questionOffset.value = 0
  practiceSubjectId.value = null
  practiceBankId.value = null
  answerResults.value = {}
  submittedAnswers.value = {}
  answerDrafts.value = {}
  error.value = null
  resetAnswer()
}

const loadBanks = async () => {
  if (!currentSubjectId.value) {
    banks.value = []
    selectedBankId.value = null
    return
  }
  banksLoading.value = true
  banksError.value = null
  try {
    banks.value = await $api<PracticeQuestionBank[]>('/practice/question-banks', {
      query: { subject_id: currentSubjectId.value, scope: practiceScope.value },
    })
    if (!banks.value.some((bank) => bank.id === selectedBankId.value)) {
      selectedBankId.value = banks.value[0]?.id ?? null
    }
  } catch (e) {
    banksError.value = e instanceof Error ? e.message : '读取题库列表失败'
    banks.value = []
    selectedBankId.value = null
  } finally {
    banksLoading.value = false
  }
}

watch([currentSubjectId, practiceScope], loadBanks)

const submittedAnswerSummary = computed(() => {
  const question = currentQuestion.value
  if (!question) return ''
  const submitted = submittedAnswers.value[question.id]
  if (question.q_type === 'single_choice') {
    return question.options.find((option) => option.id === submitted)?.label ?? '未记录'
  }
  if (question.q_type === 'multiple_choice' && Array.isArray(submitted)) {
    return submitted
      .map((id) => question.options.find((option) => option.id === id)?.label ?? id)
      .join('、')
  }
  if (question.q_type === 'true_false' && typeof submitted === 'boolean') {
    return submitted ? '正确' : '错误'
  }
  if (question.q_type === 'fill_in_the_blank' && Array.isArray(submitted)) {
    return submitted.join('；')
  }
  return typeof submitted === 'string' ? submitted : '未记录'
})

await initSubject()
await loadBanks()
</script>

<template>
  <main class="mx-auto w-full max-w-7xl space-y-6 p-4 sm:p-6">
    <header v-if="!hasStarted" class="space-y-1">
      <h1 class="text-2xl font-bold tracking-tight">自主练习</h1>
      <p class="text-sm text-muted-foreground">
        {{ practiceSubject?.name || currentSubject?.name || '选择学科后开始练习' }} · 选择题和判断题自动判分，填空与解答题由你自评
      </p>
    </header>

    <Alert v-if="error" variant="destructive">
      <AlertCircle class="h-4 w-4" />
      <AlertDescription>{{ error }}</AlertDescription>
    </Alert>

    <Card v-if="!hasStarted">
      <CardHeader>
        <CardTitle>选择练习方式</CardTitle>
        <CardDescription>先选择题库空间和导入批次，再选择练习方式。</CardDescription>
      </CardHeader>
      <CardContent class="space-y-5">
        <section class="space-y-2">
        <Label>题库空间</Label>
        <div class="grid gap-3 sm:grid-cols-2">
          <Button
            type="button"
            variant="outline"
            class="h-auto justify-start gap-3 whitespace-normal p-4 text-left"
            :class="practiceScope === 'personal' ? 'border-primary ring-1 ring-primary' : ''"
            @click="practiceScope = 'personal'"
          >
            <Lock class="h-5 w-5 shrink-0 text-primary" />
            <span class="grid gap-1">
              <span class="font-semibold">个人空间</span>
              <span class="text-xs font-normal text-muted-foreground">自己的个人题库</span>
            </span>
          </Button>
          <Button
            type="button"
            variant="outline"
            class="h-auto justify-start gap-3 whitespace-normal p-4 text-left"
            :class="practiceScope === 'shared' ? 'border-primary ring-1 ring-primary' : ''"
            @click="practiceScope = 'shared'"
          >
            <Users class="h-5 w-5 shrink-0 text-primary" />
            <span class="grid gap-1">
              <span class="font-semibold">共享空间</span>
              <span class="text-xs font-normal text-muted-foreground">当前学科内已发布的共享题库</span>
            </span>
          </Button>
        </div>
        </section>

        <div class="max-w-xl space-y-2">
        <Label for="practice-bank">选择题库 / 导入批次</Label>
        <select
          id="practice-bank"
          v-model="selectedBankId"
          :disabled="banksLoading || banks.length === 0"
          class="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-50"
        >
          <option :value="null" disabled>
            {{ banksLoading ? '正在加载题库…' : banks.length ? '请选择题库' : '当前空间暂无可练习题库' }}
          </option>
          <option v-for="bank in banks" :key="bank.id" :value="bank.id">
            {{ bank.original_filename }}（{{ bank.question_count }} 题）
          </option>
        </select>
        <p v-if="banksError" class="text-sm text-destructive">{{ banksError }}</p>
        <p v-else-if="banks.length === 0 && !banksLoading" class="text-xs text-muted-foreground">
          此处只列出含可练题目的批次。个人空间中的题目由创建者直接发布；共享空间题目需审核发布后才会列出。
        </p>
        </div>

        <div class="grid gap-3 sm:grid-cols-2">
          <Button
            v-for="option in ([
              { value: 'sequential', label: '顺序刷题', icon: ArrowRight, description: '按题目顺序练习' },
              { value: 'random', label: '乱序刷题', icon: Shuffle, description: '随机抽取并打乱顺序' },
              { value: 'type', label: '按题型刷题', icon: CircleHelp, description: '选择题型集中练习' },
              { value: 'wrong', label: '错题练习', icon: RotateCcw, description: '重练自己答错过的题目' },
            ] as const)"
            :key="option.value"
            type="button"
            variant="outline"
            class="h-auto min-h-20 justify-start gap-3 whitespace-normal p-4 text-left"
            :class="mode === option.value ? 'border-primary ring-1 ring-primary' : ''"
            @click="mode = option.value"
          >
            <component :is="option.icon" class="h-5 w-5 shrink-0 text-primary" />
            <span class="grid gap-1">
              <span class="font-semibold">{{ option.label }}</span>
              <span class="text-xs font-normal text-muted-foreground">{{ option.description }}</span>
            </span>
          </Button>
        </div>

        <div v-if="mode === 'type'" class="max-w-sm space-y-2">
          <Label for="practice-type">题型</Label>
          <select
            id="practice-type"
            v-model="selectedType"
            class="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
          >
            <option v-for="(label, value) in typeLabels" :key="value" :value="value">{{ label }}</option>
          </select>
        </div>

        <div class="flex flex-wrap items-center justify-between gap-3 border-t pt-4">
          <Badge variant="secondary">{{ modeLabels[mode] }}</Badge>
          <Button :disabled="loading || !currentSubjectId || !selectedBankId" @click="startPractice">
            {{ loading ? '正在选题…' : '开始练习' }}
          </Button>
        </div>
      </CardContent>
    </Card>

    <template v-else-if="currentQuestion">
      <section class="space-y-4">
        <header class="flex flex-wrap items-end justify-between gap-3">
          <div class="min-w-0 space-y-1">
            <div class="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
              <Button variant="ghost" size="sm" class="-ml-3" @click="restartPractice">
                <ArrowLeft class="mr-1 h-4 w-4" />练习选择
              </Button>
              <span aria-hidden="true">/</span>
              <span class="truncate">{{ practiceSubject?.name || '当前学科' }}</span>
              <span aria-hidden="true">/</span>
              <span class="truncate">{{ selectedBank?.original_filename || '题库练习' }}</span>
            </div>
            <h2 class="truncate text-xl font-semibold tracking-tight">
              {{ selectedBank?.original_filename || '自主练习' }}
            </h2>
          </div>
          <div class="flex items-center gap-2">
            <Badge variant="outline">{{ modeLabels[questionSet!.mode] }}</Badge>
            <span class="text-sm tabular-nums text-muted-foreground">
              {{ questionIndex + 1 }} / {{ answerSheetCount }}
            </span>
          </div>
        </header>

        <div class="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_19rem]">
          <Card class="min-w-0">
            <CardHeader class="space-y-3 border-b bg-muted/20">
              <div class="flex flex-wrap items-center justify-between gap-2">
                <div class="flex items-center gap-2">
                  <Badge variant="secondary">{{ typeLabels[currentQuestion.q_type] }}</Badge>
                  <Badge v-if="mode === 'type'" variant="outline">{{ modeLabels[mode] }}</Badge>
                </div>
                <span class="text-sm tabular-nums text-muted-foreground">
                  第 {{ questionIndex + 1 }} 题，共 {{ answerSheetCount }} 题
                </span>
              </div>
              <div class="h-1.5 overflow-hidden rounded-full bg-muted">
                <div
                  class="h-full rounded-full bg-primary transition-[width]"
                  :style="{ width: `${Math.min(100, ((questionIndex + 1) / Math.max(answerSheetCount, 1)) * 100)}%` }"
                />
              </div>
            </CardHeader>

            <CardContent class="space-y-6 p-5 sm:p-7">
              <div class="flex items-start gap-3">
                <span class="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-md bg-primary/10 text-sm font-semibold text-primary">
                  {{ questionIndex + 1 }}
                </span>
                <RichContent :content="currentQuestion.content" class="min-w-0 flex-1 [&_.prose]:text-base [&_.prose]:leading-7" />
              </div>

              <div v-if="currentQuestion.q_type === 'single_choice' || currentQuestion.q_type === 'multiple_choice'" class="space-y-2">
                <button
                  v-for="option in currentQuestion.options"
                  :key="option.id"
                  type="button"
                  class="flex w-full items-start gap-3 rounded-lg border p-3 text-left transition-colors hover:bg-muted/50 sm:p-4"
                  :class="selectedOptionIds.includes(option.id) ? 'border-primary bg-primary/5 ring-1 ring-primary/20' : ''"
                  :disabled="!!answerResult || submitting"
                  @click="currentQuestion.q_type === 'single_choice' ? selectOption(option.id) : toggleOption(option.id)"
                >
                  <span class="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full border text-xs font-medium"
                    :class="selectedOptionIds.includes(option.id) ? 'border-primary bg-primary text-primary-foreground' : ''">
                    <Check v-if="selectedOptionIds.includes(option.id)" class="h-3.5 w-3.5" />
                    <span v-else>{{ option.label }}</span>
                  </span>
                  <RichContent :content="option.content" class="min-w-0 flex-1 [&_.prose]:my-0" />
                </button>
              </div>

              <div v-else-if="currentQuestion.q_type === 'true_false'" class="grid gap-3 sm:grid-cols-2">
                <Button type="button" variant="outline" class="h-12 justify-start" :disabled="!!answerResult || submitting" :class="selectedBoolean === true ? 'border-primary bg-primary/5 ring-1 ring-primary' : ''" @click="selectBoolean(true)">正确</Button>
                <Button type="button" variant="outline" class="h-12 justify-start" :disabled="!!answerResult || submitting" :class="selectedBoolean === false ? 'border-primary bg-primary/5 ring-1 ring-primary' : ''" @click="selectBoolean(false)">错误</Button>
              </div>

              <div v-else-if="currentQuestion.q_type === 'fill_in_the_blank'" class="space-y-4">
                <div v-for="(_, index) in blankCount" :key="blankIds[index] || index" class="space-y-1.5">
                  <Label :for="`blank-${index}`">第 {{ index + 1 }} 空</Label>
                  <Input :id="`blank-${index}`" v-model="blankAnswers[index]" :disabled="!!answerResult" autocomplete="off" />
                </div>
                <div class="flex flex-wrap items-center gap-2">
                  <span class="text-sm text-muted-foreground">请先填写答案，再自我核对：</span>
                  <Button type="button" size="sm" variant="outline" :disabled="!!answerResult" :class="selfAssessed === true ? 'border-primary ring-1 ring-primary' : ''" @click="selfAssessed = true">我答对了</Button>
                  <Button type="button" size="sm" variant="outline" :disabled="!!answerResult" :class="selfAssessed === false ? 'border-destructive ring-1 ring-destructive' : ''" @click="selfAssessed = false">我答错了</Button>
                </div>
              </div>

              <div v-else class="space-y-4">
                <div class="space-y-1.5">
                  <Label for="free-response">填写你的答案</Label>
                  <Textarea id="free-response" v-model="responseText" :disabled="!!answerResult" placeholder="在这里填写答案或解题思路" />
                </div>
                <div class="flex flex-wrap items-center gap-2">
                  <span class="text-sm text-muted-foreground">请填写后自我核对：</span>
                  <Button type="button" size="sm" variant="outline" :disabled="!!answerResult" :class="selfAssessed === true ? 'border-primary ring-1 ring-primary' : ''" @click="selfAssessed = true">我答对了</Button>
                  <Button type="button" size="sm" variant="outline" :disabled="!!answerResult" :class="selfAssessed === false ? 'border-destructive ring-1 ring-destructive' : ''" @click="selfAssessed = false">我答错了</Button>
                </div>
              </div>

              <Alert v-if="answerResult" :variant="answerResult.is_correct === false ? 'destructive' : 'default'">
                <Check v-if="answerResult.is_correct" class="h-4 w-4" />
                <CircleHelp v-else class="h-4 w-4" />
                <AlertDescription>
                  <span v-if="answerResult.is_correct === true">回答正确。</span>
                  <span v-else-if="answerResult.dont_know">你选择了“我不知道”，已记入错题本。</span>
                  <span v-else-if="answerResult.is_correct === false">本次回答错误，已记入错题本。</span>
                  <span v-else>请对照参考答案自行核对。</span>
                  <div class="mt-2">
                    <span class="font-medium">你的作答：</span>{{ answerResult.dont_know ? '我不知道' : submittedAnswerSummary }}
                  </div>
                  <span v-if="answerResult.score !== null && currentQuestion.q_type === 'fill_in_the_blank'">
                    得分 {{ Math.round(answerResult.score * 100) }}%
                  </span>
                  <div class="mt-3 space-y-2">
                    <div class="font-medium">参考答案</div>
                    <AnswerDisplay :answer="answerResult.correct_answer" :options="currentQuestion.options" />
                    <div v-if="answerResult.analysis" class="border-t pt-2">
                      <div class="mb-1 font-medium">解析</div>
                      <RichContent :content="answerResult.analysis" />
                    </div>
                  </div>
                </AlertDescription>
              </Alert>
            </CardContent>

            <CardContent class="sticky bottom-0 flex flex-wrap items-center justify-between gap-3 border-t bg-background/95 p-4 backdrop-blur">
              <Button variant="outline" :disabled="questionIndex === 0 || submitting" @click="goToQuestion(questionIndex - 1)">
                <ArrowLeft class="mr-2 h-4 w-4" />上一题
              </Button>
              <div v-if="!answerResult" class="flex flex-wrap gap-2">
                <Button variant="outline" :disabled="submitting" @click="submitAnswer(true)">
                  我不知道
                </Button>
                <Button
                  v-if="['multiple_choice', 'fill_in_the_blank', 'free_response'].includes(currentQuestion.q_type)"
                  :disabled="!canSubmit"
                  @click="submitAnswer()"
                >
                  {{ submitting ? '正在判题…' : currentQuestion.q_type === 'multiple_choice' ? '提交答案' : '提交并自评' }}
                </Button>
              </div>
              <Button v-else @click="advanceQuestion" :disabled="loading">
                <template v-if="autoAdvancePending">即将进入下一题…</template>
                <template v-else-if="questionIndex + 1 < totalQuestions">
                  下一题<ArrowRight class="ml-2 h-4 w-4" />
                </template>
                <template v-else-if="questionSet!.has_more && questionSet!.mode !== 'random'">
                  {{ loading ? '正在加载…' : '继续练习' }}<ArrowRight class="ml-2 h-4 w-4" />
                </template>
                <template v-else>完成练习<Check class="ml-2 h-4 w-4" /></template>
              </Button>
            </CardContent>
          </Card>

          <aside class="hidden space-y-4 lg:sticky lg:top-4 lg:block">
            <Card>
              <CardHeader class="pb-3">
                <div class="flex items-center justify-between gap-2">
                  <CardTitle class="text-base">答题卡</CardTitle>
                  <span class="text-xs text-muted-foreground">已答 {{ correctCount + incorrectCount }} / {{ answerSheetCount }}</span>
                </div>
                <CardDescription>
                  <span class="text-emerald-700">正确 {{ correctCount }}</span>
                  <span class="px-1">·</span>
                  <span class="text-destructive">错误 {{ incorrectCount }}</span>
                </CardDescription>
              </CardHeader>
              <CardContent class="space-y-3">
                <div class="grid max-h-[min(55vh,32rem)] grid-cols-5 gap-2 overflow-y-auto p-1">
                  <button
                    v-for="index in answerSheetCount"
                    :key="index"
                    type="button"
                    :aria-label="`跳转到第 ${index} 题`"
                    :aria-current="questionIndex === index - 1 ? 'step' : undefined"
                    :class="questionButtonClass(index - 1)"
                    :disabled="loading || submitting"
                    @click="goToQuestion(index - 1)"
                  >
                    {{ index }}
                  </button>
                </div>
                <div class="flex flex-wrap gap-x-3 gap-y-1 border-t pt-3 text-xs text-muted-foreground">
                  <span><i class="mr-1 inline-block h-2.5 w-2.5 rounded-sm border bg-background" />未答</span>
                  <span><i class="mr-1 inline-block h-2.5 w-2.5 rounded-sm border border-amber-300 bg-amber-50" />已作答</span>
                  <span><i class="mr-1 inline-block h-2.5 w-2.5 rounded-sm border border-emerald-300 bg-emerald-50" />正确</span>
                  <span><i class="mr-1 inline-block h-2.5 w-2.5 rounded-sm border border-destructive/40 bg-destructive/10" />错误</span>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader class="pb-3">
                <CardTitle class="text-base">练习设置</CardTitle>
              </CardHeader>
              <CardContent class="space-y-4">
                <label for="auto-advance-correct" class="flex cursor-pointer items-center justify-between gap-3">
                  <span class="space-y-1">
                    <span class="block text-sm font-medium">答对后自动下一题</span>
                    <span class="block text-xs text-muted-foreground">答错或自评错误时停留查看答案</span>
                  </span>
                  <Switch
                    id="auto-advance-correct"
                    :model-value="autoAdvanceCorrect"
                    aria-label="答对后自动下一题"
                    @update:model-value="autoAdvanceCorrect = $event"
                  />
                </label>
              </CardContent>
            </Card>
          </aside>
        </div>

        <details class="rounded-lg border bg-card lg:hidden">
          <summary class="flex cursor-pointer list-none items-center justify-between gap-3 p-4 font-medium">
            <span>答题卡</span>
            <span class="text-sm font-normal text-muted-foreground">
              {{ questionIndex + 1 }} / {{ answerSheetCount }} · 正确 {{ correctCount }} · 错误 {{ incorrectCount }}
            </span>
          </summary>
          <div class="space-y-3 border-t p-4">
            <div class="grid max-h-64 grid-cols-5 gap-2 overflow-y-auto p-1">
              <button
                v-for="index in answerSheetCount"
                :key="index"
                type="button"
                :aria-label="`跳转到第 ${index} 题`"
                :aria-current="questionIndex === index - 1 ? 'step' : undefined"
                :class="questionButtonClass(index - 1)"
                :disabled="loading || submitting"
                @click="goToQuestion(index - 1)"
              >
                {{ index }}
              </button>
            </div>
            <label for="auto-advance-correct-mobile" class="flex cursor-pointer items-center justify-between gap-3 border-t pt-3">
              <span class="space-y-1">
                <span class="block text-sm font-medium">答对后自动下一题</span>
                <span class="block text-xs text-muted-foreground">答错时停留查看答案</span>
              </span>
              <Switch
                id="auto-advance-correct-mobile"
                :model-value="autoAdvanceCorrect"
                aria-label="答对后自动下一题"
                @update:model-value="autoAdvanceCorrect = $event"
              />
            </label>
          </div>
        </details>
      </section>
    </template>

    <Card v-else-if="questionSet && totalQuestions === 0">
      <CardContent class="space-y-4 p-8 text-center">
        <CircleHelp class="mx-auto h-10 w-10 text-muted-foreground" />
        <div class="space-y-1">
          <h2 class="font-semibold">这组练习暂时没有题目</h2>
          <p class="text-sm text-muted-foreground">
            {{ questionSet.mode === 'wrong' ? '答错的题目会自动加入错题练习。' : '请尝试其他练习方式或确认当前学科已有已发布题目。' }}
          </p>
        </div>
        <Button variant="outline" @click="restartPractice">返回练习选择</Button>
      </CardContent>
    </Card>

    <Card v-else-if="questionSet">
      <CardContent class="space-y-4 p-8 text-center">
        <Check class="mx-auto h-10 w-10 text-primary" />
        <div class="space-y-1">
          <h2 class="font-semibold">本组练习已完成</h2>
          <p class="text-sm text-muted-foreground">答题记录已保存；你可以重新选择练习方式继续。</p>
        </div>
        <Button variant="outline" @click="restartPractice">返回练习选择</Button>
      </CardContent>
    </Card>
  </main>
</template>
