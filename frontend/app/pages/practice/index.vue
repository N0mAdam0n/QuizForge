<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { AlertCircle, ArrowLeft, ArrowRight, Check, CircleHelp, RotateCcw, Shuffle } from '@lucide/vue'
import { toast } from 'vue-sonner'
import AnswerDisplay from '@/components/AnswerDisplay.vue'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import RichContent from '@/components/rich-editor/RichContent.vue'
import type { AnswerSpec, OptionSpec, QuestionType, RichDoc } from '@/types'
import { collectBlankIds } from '@/components/rich-editor/richDoc'

definePageMeta({ layout: 'default' })

type PracticeMode = 'sequential' | 'random' | 'type' | 'wrong'

interface PracticeQuestion {
  id: number
  content: RichDoc
  q_type: QuestionType
  options: OptionSpec[]
  difficulty: number
}

interface PracticeQuestionSet {
  mode: PracticeMode
  questions: PracticeQuestion[]
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
}

const { $api } = useNuxtApp()
const { currentSubjectId, currentSubject, subjects, init: initSubject } = useSubjectContext()

const mode = ref<PracticeMode>('sequential')
const selectedType = ref<QuestionType>('single_choice')
const questionSet = ref<PracticeQuestionSet | null>(null)
const questionIndex = ref(0)
const questionOffset = ref(0)
const practiceSubjectId = ref<number | null>(null)
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
const hasStarted = computed(() => questionSet.value !== null)
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

const resetAnswer = (question = currentQuestion.value) => {
  const draft = question ? answerDrafts.value[question.id] : null
  selectedOptionIds.value = draft?.selectedOptionIds ?? []
  selectedBoolean.value = draft?.selectedBoolean ?? null
  blankAnswers.value = draft?.blankAnswers ?? blankIds.value.map(() => '')
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
  if (!currentSubjectId.value) {
    toast.error('请先选择学科')
    return
  }
  loading.value = true
  error.value = null
  practiceSubjectId.value = currentSubjectId.value
  try {
    const query: Record<string, string | number> = {
      subject_id: practiceSubjectId.value,
      mode: mode.value,
      limit: 20,
      offset: questionOffset.value,
    }
    if (mode.value === 'type') query.q_type = selectedType.value
    questionSet.value = await $api<PracticeQuestionSet>('/practice/questions', { query })
    questionIndex.value = 0
    if (questionSet.value.questions.length === 0) {
      toast.info(mode.value === 'wrong' ? '当前没有待练习的错题' : '当前筛选条件下没有可练习的已发布题目')
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

const canSubmit = computed(() => {
  if (!currentQuestion.value || answerResult.value || submitting.value) return false
  switch (currentQuestion.value.q_type) {
    case 'single_choice':
    case 'multiple_choice':
      return selectedOptionIds.value.length > 0
    case 'true_false':
      return selectedBoolean.value !== null
    case 'fill_in_the_blank':
      return blankAnswers.value.length > 0 && blankAnswers.value.every((answer) => answer.trim())
    case 'free_response':
      return selfAssessed.value !== null
  }
})

const submitAnswer = async () => {
  const question = currentQuestion.value
  if (!question || !canSubmit.value || !questionSet.value || !practiceSubjectId.value) return

  let answer: string | string[] | boolean | null = null
  if (question.q_type === 'single_choice') answer = selectedOptionIds.value[0] ?? null
  else if (question.q_type === 'multiple_choice') answer = selectedOptionIds.value
  else if (question.q_type === 'true_false') answer = selectedBoolean.value
  else if (question.q_type === 'fill_in_the_blank') answer = blankAnswers.value
  else answer = responseText.value

  submitting.value = true
  error.value = null
  try {
    const result = await $api<PracticeAnswerResult>('/practice/answers', {
      method: 'POST',
      body: {
        question_id: question.id,
        subject_id: practiceSubjectId.value,
        mode: questionSet.value.mode,
        answer,
        self_assessed: question.q_type === 'free_response' ? selfAssessed.value : null,
      },
    })
    submittedAnswers.value[question.id] = answer
    answerResults.value[question.id] = result
  } catch (e) {
    error.value = e instanceof Error ? e.message : '提交答案失败'
  } finally {
    submitting.value = false
  }
}

const goToQuestion = (index: number) => {
  if (index >= 0 && index < totalQuestions.value) questionIndex.value = index
}

const advanceQuestion = async () => {
  if (!questionSet.value) return
  if (questionIndex.value + 1 < totalQuestions.value) {
    questionIndex.value += 1
    return
  }
  if (questionSet.value.has_more && questionSet.value.mode !== 'random') {
    if (!practiceSubjectId.value) return
    loading.value = true
    error.value = null
    try {
      const query: Record<string, string | number> = {
        subject_id: practiceSubjectId.value,
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
      if (nextSet.questions.length > 0) questionIndex.value += 1
      else questionSet.value.has_more = false
    } catch (e) {
      error.value = e instanceof Error ? e.message : '加载下一组练习题失败'
    } finally {
      loading.value = false
    }
    return
  }
  questionIndex.value = totalQuestions.value
}

const restartPractice = () => {
  questionSet.value = null
  questionIndex.value = 0
  questionOffset.value = 0
  practiceSubjectId.value = null
  answerResults.value = {}
  submittedAnswers.value = {}
  answerDrafts.value = {}
  error.value = null
  resetAnswer()
}

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
</script>

<template>
  <main class="mx-auto w-full max-w-4xl space-y-6 p-4 sm:p-6">
    <header class="space-y-1">
      <h1 class="text-2xl font-bold tracking-tight">自主练习</h1>
      <p class="text-sm text-muted-foreground">
        {{ practiceSubject?.name || currentSubject?.name || '选择学科后开始练习' }} · 答案在提交后由服务端判定
      </p>
    </header>

    <Alert v-if="error" variant="destructive">
      <AlertCircle class="h-4 w-4" />
      <AlertDescription>{{ error }}</AlertDescription>
    </Alert>

    <Card v-if="!hasStarted">
      <CardHeader>
        <CardTitle>选择练习方式</CardTitle>
        <CardDescription>题目仅从当前学科中可见且已发布的题目抽取。</CardDescription>
      </CardHeader>
      <CardContent class="space-y-5">
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
          <Button :disabled="loading || !currentSubjectId" @click="startPractice">
            {{ loading ? '正在选题…' : '开始练习' }}
          </Button>
        </div>
      </CardContent>
    </Card>

    <template v-else-if="currentQuestion">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <div class="flex items-center gap-2">
          <Badge variant="outline">{{ modeLabels[questionSet!.mode] }}</Badge>
          <Badge variant="secondary">{{ typeLabels[currentQuestion.q_type] }}</Badge>
        </div>
        <span class="text-sm tabular-nums text-muted-foreground">
          第 {{ questionIndex + 1 }} / {{ totalQuestions }} 题
        </span>
      </div>

      <Card>
        <CardContent class="space-y-6 p-5 sm:p-7">
          <div class="flex items-start gap-3">
            <span class="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full bg-primary/10 text-sm font-semibold text-primary">
              {{ questionIndex + 1 }}
            </span>
            <RichContent :content="currentQuestion.content" class="min-w-0 flex-1 [&_.prose]:text-base" />
          </div>

          <div v-if="currentQuestion.q_type === 'single_choice' || currentQuestion.q_type === 'multiple_choice'" class="space-y-2">
            <button
              v-for="option in currentQuestion.options"
              :key="option.id"
              type="button"
              class="flex w-full items-start gap-3 rounded-lg border p-3 text-left transition-colors hover:bg-muted/50"
              :class="selectedOptionIds.includes(option.id) ? 'border-primary bg-primary/5' : ''"
              :disabled="!!answerResult"
              @click="toggleOption(option.id)"
            >
              <span class="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full border text-xs"
                :class="selectedOptionIds.includes(option.id) ? 'border-primary bg-primary text-primary-foreground' : ''">
                <Check v-if="selectedOptionIds.includes(option.id)" class="h-3 w-3" />
                <span v-else>{{ option.label }}</span>
              </span>
              <RichContent :content="option.content" class="min-w-0 flex-1 [&_.prose]:my-0" />
            </button>
          </div>

          <div v-else-if="currentQuestion.q_type === 'true_false'" class="flex gap-3">
            <Button type="button" variant="outline" :disabled="!!answerResult" :class="selectedBoolean === true ? 'border-primary ring-1 ring-primary' : ''" @click="selectedBoolean = true">正确</Button>
            <Button type="button" variant="outline" :disabled="!!answerResult" :class="selectedBoolean === false ? 'border-primary ring-1 ring-primary' : ''" @click="selectedBoolean = false">错误</Button>
          </div>

          <div v-else-if="currentQuestion.q_type === 'fill_in_the_blank'" class="space-y-3">
            <div v-for="(_, index) in blankIds" :key="blankIds[index]" class="space-y-1.5">
              <Label :for="`blank-${index}`">第 {{ index + 1 }} 空</Label>
              <Input :id="`blank-${index}`" v-model="blankAnswers[index]" :disabled="!!answerResult" autocomplete="off" />
            </div>
          </div>

          <div v-else class="space-y-3">
            <Label for="free-response">作答后请进行自我核对</Label>
            <Textarea id="free-response" v-model="responseText" :disabled="!!answerResult" placeholder="在这里记录你的解题思路（可选）" />
            <div class="flex flex-wrap gap-2">
              <Button type="button" size="sm" variant="outline" :disabled="!!answerResult" :class="selfAssessed === true ? 'border-primary ring-1 ring-primary' : ''" @click="selfAssessed = true">我已掌握</Button>
              <Button type="button" size="sm" variant="outline" :disabled="!!answerResult" :class="selfAssessed === false ? 'border-destructive ring-1 ring-destructive' : ''" @click="selfAssessed = false">还不确定</Button>
            </div>
          </div>

          <Alert v-if="answerResult" :variant="answerResult.is_correct === false ? 'destructive' : 'default'">
            <Check v-if="answerResult.is_correct" class="h-4 w-4" />
            <CircleHelp v-else class="h-4 w-4" />
            <AlertDescription>
              <span v-if="answerResult.is_correct === true">回答正确。</span>
              <span v-else-if="answerResult.is_correct === false">本次回答未完全正确。</span>
              <span v-else>请对照参考答案自行核对。</span>
              <div class="mt-2">
                <span class="font-medium">你的作答：</span>{{ submittedAnswerSummary }}
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

          <div class="flex flex-wrap items-center justify-between gap-3 border-t pt-4">
            <Button variant="ghost" :disabled="questionIndex === 0 || submitting" @click="goToQuestion(questionIndex - 1)">
              <ArrowLeft class="mr-2 h-4 w-4" />上一题
            </Button>
            <Button v-if="!answerResult" :disabled="!canSubmit" @click="submitAnswer">
              {{ submitting ? '正在判题…' : '提交答案' }}
            </Button>
            <Button v-else @click="advanceQuestion" :disabled="loading">
              <template v-if="questionIndex + 1 < totalQuestions">
              下一题<ArrowRight class="ml-2 h-4 w-4" />
              </template>
              <template v-else-if="questionSet!.has_more && questionSet!.mode !== 'random'">
                {{ loading ? '正在加载…' : '继续练习' }}<ArrowRight class="ml-2 h-4 w-4" />
              </template>
              <template v-else>完成练习<Check class="ml-2 h-4 w-4" /></template>
            </Button>
          </div>
        </CardContent>
      </Card>
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
