import { useEffect, useState } from 'react'
import { BookOpen, Compass, ClipboardList, LibraryBig } from 'lucide-react'
import { readDemo, writeDemo } from './demo-transport'

export type Category = 'home' | 'partners' | 'learning' | 'library'
export type LearningKind = 'book' | 'mastery' | 'practice' | 'reading'
export const learningKinds = [
  { id: 'book', label: '书籍', icon: LibraryBig, description: '把一个主题组织成一本专属的书' },
  { id: 'mastery', label: '精通之路', icon: Compass, description: '循序渐进，直到真正掌握' },
  { id: 'practice', label: '练习', icon: ClipboardList, description: '用练习检验理解，安排复习' },
  {
    id: 'reading',
    label: '沉浸式阅读',
    icon: BookOpen,
    description: '专注阅读，在原文中提问和批注',
  },
] as const
export type LearningRecord = {
  id: string
  title: string
  kind: LearningKind
  detail: string
  notes: string
  sample?: boolean
}
export const initialLearning: LearningRecord[] = [
  {
    id: 'attention',
    title: '理解 Transformer 的注意力机制',
    kind: 'reading',
    detail: '机器学习 · 第 1 / 3 节',
    notes: '',
    sample: true,
  },
  {
    id: 'linear',
    title: '线性代数，从直觉出发',
    kind: 'mastery',
    detail: '6 个目标 · 已完成 2 个',
    notes: '',
    sample: true,
  },
  {
    id: 'book',
    title: '概率论的直觉',
    kind: 'book',
    detail: '书籍 · 3 个章节',
    notes: '',
    sample: true,
  },
  {
    id: 'practice',
    title: '向量与空间 · 巩固练习',
    kind: 'practice',
    detail: '练习 · 1 道待复习',
    notes: '',
    sample: true,
  },
]
export type DemoPartner = { id: string; name: string; description: string; color: string }
export type DemoGroup = { id: string; name: string; members: string[] }
export type DemoSession = {
  id: string
  title: string
  owner: string
  messages: { role: 'user' | 'assistant'; text: string }[]
}
export function useCollections() {
  const [learning, setLearning] = useState(() => readDemo('learning-records', initialLearning))
  const [partners, setPartners] = useState<DemoPartner[]>(() =>
    readDemo('partners', [
      {
        id: 'saturday',
        name: 'Saturday',
        description: '一起研究、整理想法，推进你的每一天。',
        color: '#7a8d75',
      },
      {
        id: 'socrates',
        name: 'Socrates',
        description: '通过追问，帮你把一个问题想明白。',
        color: '#b38d73',
      },
    ])
  )
  const [groups, setGroups] = useState<DemoGroup[]>(() =>
    readDemo('partner-groups', [
      { id: 'research', name: '研究讨论室', members: ['saturday', 'socrates'] },
    ])
  )
  const [sessions, setSessions] = useState<DemoSession[]>(() =>
    readDemo('partner-sessions', [
      {
        id: 'session-one',
        title: '梳理本周的研究方向',
        owner: 'saturday',
        messages: [
          {
            role: 'assistant',
            text: '这是一段示例会话。可以继续讨论研究问题，或打开右上角的伙伴配置。',
          },
        ],
      },
      {
        id: 'session-two',
        title: '关于学习反馈的讨论',
        owner: 'research',
        messages: [
          {
            role: 'assistant',
            text: '这是研究讨论室的示例记录。Saturday 和 Socrates 将从不同的角度参与讨论。',
          },
        ],
      },
    ])
  )
  useEffect(() => writeDemo('learning-records', learning), [learning])
  useEffect(() => writeDemo('partners', partners), [partners])
  useEffect(() => writeDemo('partner-groups', groups), [groups])
  useEffect(() => writeDemo('partner-sessions', sessions), [sessions])
  const records = learning.map(record => {
    if (record.id === 'attention')
      return {
        ...record,
        detail: `机器学习 · 第 ${readDemo('position', { locator: 1 }).locator} / 3 节`,
      }
    if (record.id === 'linear')
      return {
        ...record,
        detail: `6 个目标 · 已完成 ${readDemo<{ isCorrect?: boolean } | null>('grade', null)?.isCorrect ? 3 : 2} 个`,
      }
    if (record.id === 'practice' && readDemo('practice-practice', null))
      return { ...record, detail: '练习 · 本轮已完成' }
    return record
  })
  return {
    learning: records,
    setLearning,
    partners,
    setPartners,
    groups,
    setGroups,
    sessions,
    setSessions,
  }
}
export type Collections = ReturnType<typeof useCollections>
