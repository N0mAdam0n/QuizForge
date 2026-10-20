<script setup lang="ts">
import { Copy } from '@lucide/vue'
import { Button } from '@/components/ui/button'
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from '@/components/ui/table'
import { toast } from 'vue-sonner'

defineProps<{ open: boolean }>()
const emit = defineEmits<{ (e: 'update:open', value: boolean): void }>()

const tagRows = [
    { tag: '【题目】', required: '必填', note: '每道题的开头，同时作为题目之间的分隔符' },
    { tag: '【题型】', required: '可选', note: '单选/多选/判断/填空/解答；省略时自动推断' },
    { tag: '【选项】', required: '可选', note: '块写法 A. … B. … 或逐项 【选项A】【选项B】' },
    { tag: '【答案】', required: '可选', note: '选择题写字母（多选如 AB），判断题写 对/错' },
    { tag: '【解析】', required: '可选', note: '可多行' },
    { tag: '【思路】', required: '可选', note: '可多行' },
    { tag: '【难度】', required: '可选', note: '1–5，或 简单/中等/困难' },
    { tag: '【小结】', required: '可选', note: '可多行' },
    { tag: '【答案区】', required: '可选', note: '别名【答案表】【统一答案】【答案速查】；用于文末统一答案表' },
]

const examples = [
    {
        key: 'numbered',
        label: '常见题号格式',
        text: `1. 根据图示网络，以下说法正确的是？ ![网络拓扑](/static/media/task-id/image1.png)
A. 选项一
B. 选项二
C. 选项三
D. 选项四
答案：A
解析：图中的网络结构决定了正确选项。`,
    },
    {
        key: 'single',
        label: '单选题',
        text: `【题目】下列关于集合的说法正确的是
【选项】A. 空集是任何集合的子集  B. 0 是空集  C. {0} 是空集  D. 以上都不对
【答案】A
【解析】空集是任何集合的子集。`,
    },
    {
        key: 'truefalse',
        label: '判断题',
        text: `【题目】判断：0 是自然数
【答案】对`,
    },
    {
        key: 'blank',
        label: '填空题',
        text: `【题目】1 + 1 = ____
【答案】2`,
    },
    {
        key: 'answer-section',
        label: '统一答案区',
        text: `【题目】1+1=?
【选项】A. 1 B. 2 C. 3 D. 4
【题目】3+3=?
【选项】A. 5 B. 6 C. 7 D. 8
【答案区】
| 题号 | 1 | 2 |
|:---:|:---:|:---:|
| 答案 | B | B |
1．因为1+1=2，选B。
2．因为3+3=6，选B。`,
    },
]

const copyExample = async (text: string) => {
    await navigator.clipboard.writeText(text)
    toast.success('已复制，可直接粘贴到文档中')
}
</script>

<template>
    <Dialog :open="open" @update:open="emit('update:open', $event)">
        <DialogContent class="w-[95vw] sm:max-w-[680px] max-h-[85vh] overflow-y-auto">
            <DialogHeader>
                <DialogTitle>本地多策略识别：格式说明</DialogTitle>
                <DialogDescription>
                    可识别显式标签模板，也支持以题号开头、后接选项和答案/解析的常见题库排版。
                    文本中的图片引用会保留在题干或解析中；全角【】与半角 [] 均可识别。
                </DialogDescription>
            </DialogHeader>

            <p class="text-sm text-muted-foreground">
                不同文档的排版仍可能有差异，请在识别后检查题目边界、图片位置和答案；结构复杂或扫描件可切换 AI 识别。
            </p>

            <Table>
                <TableHeader>
                    <TableRow>
                        <TableHead class="w-28">标签</TableHead>
                        <TableHead class="w-16">是否必填</TableHead>
                        <TableHead>说明</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    <TableRow v-for="row in tagRows" :key="row.tag">
                        <TableCell><Badge variant="outline">{{ row.tag }}</Badge></TableCell>
                        <TableCell>
                            <Badge :variant="row.required === '必填' ? 'default' : 'secondary'">{{ row.required }}</Badge>
                        </TableCell>
                        <TableCell class="text-sm text-muted-foreground">{{ row.note }}</TableCell>
                    </TableRow>
                </TableBody>
            </Table>

            <Tabs default-value="single" class="mt-2">
                <TabsList class="grid w-full grid-cols-5">
                    <TabsTrigger v-for="ex in examples" :key="ex.key" :value="ex.key">{{ ex.label }}</TabsTrigger>
                </TabsList>
                <TabsContent v-for="ex in examples" :key="ex.key" :value="ex.key" class="mt-3">
                    <div class="relative rounded-md border bg-muted/30">
                        <pre class="whitespace-pre-wrap break-all p-4 pr-12 text-sm font-mono">{{ ex.text }}</pre>
                        <Button
                            variant="ghost"
                            size="sm"
                            class="absolute right-2 top-2"
                            @click="copyExample(ex.text)"
                        >
                            <Copy class="h-4 w-4 mr-1" />复制
                        </Button>
                    </div>
                </TabsContent>
            </Tabs>
        </DialogContent>
    </Dialog>
</template>
