import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { CategoryBody } from '@/features/preview/PreviewNavigation'
import {
  CreateLearningPage,
  LearningOverview,
} from '@/features/preview/CollectionSurfaces'
import { initialLearning, type Collections } from '@/features/preview/collections'
import { initI18n } from '@/i18n/init'

initI18n('en')

const collections: Collections = {
  learning: initialLearning,
  setLearning: vi.fn(),
  partners: [],
  setPartners: vi.fn(),
  groups: [],
  setGroups: vi.fn(),
  sessions: [],
  setSessions: vi.fn(),
}

it('keeps learning creation out of the overview', () => {
  render(<LearningOverview collections={collections} onOpen={vi.fn()} />)

  expect(screen.queryByRole('button', { name: '新建学习' })).not.toBeInTheDocument()
  expect(screen.queryByText('开始一段新的学习')).not.toBeInTheDocument()
})

it('shows one active creation entry at the top of the learning sidebar', () => {
  const onCreate = vi.fn()
  render(
    <CategoryBody
      category="learning"
      collapsed={false}
      view="new-learning"
      collections={collections}
      activeRecord=""
      activePartner=""
      resourceHref=""
      onGo={vi.fn()}
      onRecord={vi.fn()}
      onCreate={onCreate}
      onPartner={vi.fn()}
      onNewPartner={vi.fn()}
      onNewGroup={vi.fn()}
      onResource={vi.fn()}
    />
  )

  const create = screen.getByRole('button', { name: '新建学习' })
  const overview = screen.getByRole('button', { name: '所有学习' })
  expect(screen.getAllByRole('button', { name: '新建学习' })).toHaveLength(1)
  expect(screen.queryByText('个性化学习')).not.toBeInTheDocument()
  expect(create).toHaveAttribute('aria-current', 'page')
  expect(create.compareDocumentPosition(overview) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()

  fireEvent.click(create)
  expect(onCreate).toHaveBeenCalledOnce()
})

it('creates the selected learning kind from the standalone page', () => {
  const onBack = vi.fn()
  const onCreate = vi.fn()
  render(<CreateLearningPage onBack={onBack} onCreate={onCreate} />)

  expect(screen.getByRole('heading', { name: '新建学习' })).toBeInTheDocument()
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: '创建书籍' })).toBeDisabled()

  fireEvent.click(screen.getByRole('button', { name: /精通之路/ }))
  fireEvent.change(screen.getByLabelText('名称'), { target: { value: '  线性代数基础  ' } })
  fireEvent.change(screen.getByLabelText('你想学会什么？'), {
    target: { value: '理解向量与矩阵' },
  })
  fireEvent.click(screen.getByRole('button', { name: '创建精通之路' }))

  expect(onCreate).toHaveBeenCalledWith(
    expect.objectContaining({
      title: '线性代数基础',
      kind: 'mastery',
      notes: '理解向量与矩阵',
      detail: '刚刚创建 · 草稿',
    })
  )

  fireEvent.click(screen.getByRole('button', { name: '返回所有学习' }))
  expect(onBack).toHaveBeenCalledOnce()
})
