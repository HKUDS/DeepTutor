import { fireEvent, render, screen, within } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { LearningNavigation } from '@/components/sidebar/LearningNavigation'

vi.mock('next/navigation', () => ({ usePathname: () => '/learning', useSearchParams: () => new URLSearchParams() }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }) }))
vi.mock('@/components/learning/LearningCreateMenu', () => ({ LearningCreateMenu: () => <button>Create learning</button> }))
vi.mock('@/components/layout/AppShell', () => ({ useSidebarDrawer: () => null }))
const mastery = vi.hoisted(() => ({ topics: [] as unknown[] }))
vi.mock('@/hooks/useLearningIndex', () => ({ useLearningIndex: () => ({
  loading: false, failed: [], retry: vi.fn(), sources: {
    books: [], mastery: mastery.topics, reading: [], watching: [], practice: [
      { id: 1, question: 'Older material, recently studied', created_at: 100, updated_at: 900, content_workspace_id: 'physics' },
      { id: 2, question: 'Newly created material', created_at: 800, updated_at: 800, content_workspace_id: '' },
    ],
  },
}) }))
beforeEach(() => {
  localStorage.clear()
  mastery.topics = []
})

it('sorts by creation independently of activity and retains the preference', () => {
  const view = render(<LearningNavigation />)
  const records = () => within(screen.getByRole('region', { name: 'navigation.learningRecords' })).getAllByRole('link')
  expect(records()[0]).toHaveTextContent('Older material')
  fireEvent.click(screen.getByRole('button', { name: 'navigation.sortRecords' }))
  fireEvent.click(screen.getByRole('menuitemradio', { name: 'navigation.createdTime' }))
  expect(records()[0]).toHaveTextContent('Newly created material')
  expect(records()[1]).toHaveAttribute('href', '/learning/practice?question=1&dt_workspace=physics')
  view.unmount()
  render(<LearningNavigation />)
  expect(records()[0]).toHaveTextContent('Newly created material')
})

it('searches records without discarding the rest of the library', () => {
  render(<LearningNavigation />)
  fireEvent.click(screen.getByRole('button', { name: 'navigation.searchLearning' }))
  const input = screen.getByRole('searchbox', { name: 'navigation.searchLearning' })
  fireEvent.change(input, { target: { value: 'recently' } })
  const list = within(screen.getByRole('region', { name: 'navigation.learningRecords' }))
  expect(list.getAllByRole('link')).toHaveLength(1)
  expect(list.getByRole('link')).toHaveTextContent('Older material')
  fireEvent.keyDown(input, { key: 'Escape' })
  expect(list.getAllByRole('link')).toHaveLength(2)
})

it('files a conversation under the record it was held in', () => {
  mastery.topics = [{
    path_id: 'p1', name: 'Vectors', updated_at: 50, content_workspace_id: '', reviews: [],
    metadata: { status: 'active', goal: 'Vectors', created_at: 10 },
    map: { counts: { total: 2, mastered: 1 } },
  }]
  const session = (id: string, title: string, updated: number, pathId = '') => ({
    session_id: id, title, created_at: updated, updated_at: updated, content_workspace_id: '',
    preferences: pathId ? { workspace_mode: 'mastery_path' as const, mastery_path_id: pathId } : { workspace_mode: 'mastery_path' as const, mastery_path_id: 'gone' },
  })
  const rows = [session('s1', 'Dot products', 990, 'p1'), session('s2', 'Old path chat', 20)]
  render(<LearningNavigation sessions={{
    rows: rows as never,
    activeSessionId: null,
    render: list => <ul>{list.map(row => <li key={row.session_id}>{row.title}</li>)}</ul>,
  }} />)
  const region = within(screen.getByRole('region', { name: 'navigation.learningRecords' }))
  // The path takes the time of its latest conversation and leads the list.
  expect(region.getAllByRole('link')[0]).toHaveTextContent('Vectors')
  expect(region.queryByText('Dot products')).toBeNull()
  // A conversation whose path is gone stands on its own.
  expect(region.getByText('Old path chat')).toBeInTheDocument()
  fireEvent.click(region.getByRole('button', { name: 'navigation.showRecordChats' }))
  expect(region.getByText('Dot products')).toBeInTheDocument()
  // Searching for a conversation finds it inside its record.
  fireEvent.click(region.getByRole('button', { name: 'navigation.hideRecordChats' }))
  fireEvent.click(screen.getByRole('button', { name: 'navigation.searchLearning' }))
  fireEvent.change(screen.getByRole('searchbox', { name: 'navigation.searchLearning' }), { target: { value: 'dot' } })
  expect(region.getByText('Dot products')).toBeInTheDocument()
  expect(region.queryByText('Old path chat')).toBeNull()
})
