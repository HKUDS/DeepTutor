import type { MaterialDetail } from '@/lib/reading-api'
import type { MasteryQuestion } from '@/lib/mastery-question'

export type PreviewView =
  | 'home'
  | 'learning'
  | 'new-learning'
  | 'library'
  | 'reading'
  | 'writing'
  | 'mastery'
  | 'chat'
  | 'partners'
  | 'kanban'
  | 'agents'
  | 'resource'
  | 'record'
export const previewItems: {
  id: string
  title: string
  kind: string
  view: PreviewView
  detail: string
  progress?: number
}[] = [
  {
    id: 'attention',
    title: '理解 Transformer 的注意力机制',
    kind: '沉浸式阅读',
    view: 'reading',
    detail: '机器学习 · 第 1 / 3 节',
    progress: 0.33,
  },
  {
    id: 'linear',
    title: '线性代数，从直觉出发',
    kind: '引导式学习',
    view: 'mastery',
    detail: '6 个学习目标 · 已完成 2 个',
    progress: 0.33,
  },
  {
    id: 'research',
    title: '我的研究计划',
    kind: 'Co-Writer',
    view: 'writing',
    detail: '研究笔记 · 今天编辑',
  },
  {
    id: 'chat',
    title: '与 Dito 对话',
    kind: '对话',
    view: 'chat',
    detail: '通用助手 · Auto 模式',
  },
]

export const readingUnits = [
  `# 理解 Transformer 的注意力机制

> 学习笔记 · 从一个句子开始理解注意力

## 01　为什么需要注意力？

读到「小猫没有跨过围栏，因为它太高了」，你会自然地知道「它」指的是围栏。我们理解一个词时，会回看句子中与它相关的部分。

注意力机制做的就是类似的事：让每一个词主动寻找与自己相关的信息，并决定应该关注多少。

## 把句子想成一次讨论

每个词都有三个角色：

- **Query（查询）**：我现在需要什么信息？
- **Key（键）**：我能提供哪一类信息？
- **Value（值）**：我实际携带的信息是什么？

Query 与每个 Key 的匹配程度决定关注的权重，再用这些权重对 Value 加权求和。

## 核心公式

$$\\operatorname{Attention}(Q,K,V)=\\operatorname{softmax}\\left(\\frac{QK^T}{\\sqrt{d_k}}\\right)V$$

先匹配，再归一化，最后汇总。把这三步记住，就抓住了注意力机制的主线。

**边读边想**：如果所有词的匹配分数都一样，最后得到的输出会是什么？

你可以选中一句话做批注，也可以直接向右侧的 Dito 提问。`,
  `# 从匹配分数到注意力权重

## 02　缩放与归一化

Query 和 Key 的点积是匹配分数。当向量的维数变大时，点积的波动也会增大。直接放进 softmax 容易让权重过于集中。

因此我们除以维数的平方根，让分数处于更稳定的范围。

## 一个小例子

假设匹配分数是 2、1、0，经过 softmax 后，权重大约是 0.665、0.245、0.090。

最匹配的词贡献最多，但其他词的信息仍然保留。

## 试着解释

请用自己的话解释：为什么不能直接用原始的点积作为加权系数？`,
  `# 多头注意力：从不同角度理解

## 03　不同的问题，不同的关注点

同一句话里，一个头可能关注语法依赖，另一个头可能关注语义关系。它们各自在投影后的空间里计算注意力，再把结果组合起来。

## 回顾这条主线

1. 一个词用 Query 表达需求。
2. 用 Key 匹配其他位置。
3. 对分数缩放、归一化。
4. 汇总 Value，得到新的表示。

**下一步**：做一道小练习，看看你能不能把这个过程解释清楚。`,
]

export const material: MaterialDetail = {
  material_id: 'preview-attention',
  filename: 'attention-notes.md',
  title: previewItems[0].title,
  unit: 'section',
  unit_count: 3,
  mime: 'text/markdown',
  byte_size: 2400,
  char_count: 1200,
  created_at: 1791792000,
  has_raw_view: false,
  render_mode: 'text',
  content_format: 'web_markdown',
  extractor: 'preview',
  annotation_count: 0,
  revision: 1,
  outline: ['为什么需要注意力？', '缩放与归一化', '多头注意力'].map((title, i) => ({
    locator: i + 1,
    title,
    level: 1,
    synthesised: false,
  })),
  outline_text: '',
  unit_refs: [],
}

export const initialDocument = {
  id: 'preview-research',
  title: '我的研究计划',
  created_at: 1791792000,
  updated_at: 1791792000,
  content: `# 我的研究计划\n\n## 研究问题\n\n如何帮助学习者把零散的知识，转变成能够解释和应用的理解？\n\n## 初步想法\n\n从阅读一篇材料开始，在关键位置记录疑问，再通过针对性的练习确认理解。让阅读、笔记与练习围绕同一个学习目标展开。\n\n## 本周安排\n\n- [x] 整理注意力机制的阅读笔记\n- [ ] 比较三种学习反馈方式\n- [ ] 完成第一版实验设计\n\n## 需要继续探索\n\n1. 怎样发现学习者真正没理解的地方？\n2. 怎样安排复习，而不打断学习节奏？\n3. 怎样让助手的建议保留足够的自主选择？\n`,
}

export const objectives = [
  '向量与线性组合',
  '矩阵作为一种变换',
  '线性无关与基',
  '特征值与特征向量',
  '正交投影',
  '把直觉用在实际问题里',
]
export const question: MasteryQuestion = {
  questionId: 'preview-basis',
  prompt: '在二维平面中，哪一组向量可以构成一组基？',
  questionType: 'multiple_choice',
  objectiveName: '线性无关与基',
  difficulty: 'easy',
  attempt: 1,
  allowFreeText: false,
  options: [
    { label: 'A', body: '(1, 0) 和 (2, 0)' },
    { label: 'B', body: '(1, 0) 和 (0, 1)' },
    { label: 'C', body: '(0, 0) 和 (1, 1)' },
  ],
}
