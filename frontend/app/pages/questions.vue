<script setup lang="ts">
import { onMounted } from 'vue'
import { toast } from 'vue-sonner'
import type { Question } from '@/types'

definePageMeta({ layout: 'default' })

const route = useRoute()
const { $api } = useNuxtApp()

onMounted(async () => {
  const importTaskId = Number(route.query.import_task_id)
  if (Number.isSafeInteger(importTaskId) && importTaskId > 0) {
    await navigateTo(`/question-banks/${importTaskId}`, { replace: true })
    return
  }

  const questionId = Number(route.query.id)
  if (Number.isSafeInteger(questionId) && questionId > 0) {
    try {
      const question = await $api<Question>(`/questions/${questionId}`)
      if (question.import_task_id) {
        await navigateTo(`/question-banks/${question.import_task_id}`, { replace: true })
        return
      }
    } catch (cause: any) {
      toast.error('无法打开题目所属题库', {
        description: cause?.data?.detail || cause?.message || '请检查题目访问权限。',
      })
    }
  }

  await navigateTo('/question-banks', { replace: true })
})
</script>

<template>
  <div class="flex min-h-40 items-center justify-center text-sm text-muted-foreground">
    正在打开题库…
  </div>
</template>
