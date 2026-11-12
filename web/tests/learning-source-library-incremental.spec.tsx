import { act, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { useTopicSourceLibrary } from '@/hooks/useTopicSourceLibrary'
import type { SourceCandidate, SourceLibrary } from '@/hooks/useTopicSourceLibrary'
import { SourcesStep } from '@/components/space/learning/TopicWizardSteps'
import { initI18n } from '@/i18n/init'
import { apiFetch } from '@/lib/api'

vi.mock('@/lib/api', () => ({ apiUrl: (path: string) => path, apiFetch: vi.fn() }))
vi.mock('@/lib/partners-api', () => ({ listPartners: async () => [], getPartnerSessions: vi.fn() }))
vi.mock('@/lib/partner-groups-api', () => ({
  listPartnerGroups: async () => [],
  listPartnerGroupSessions: vi.fn(),
}))
vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({}),
  usePathname: () => '/learning/books',
}))

initI18n('en')
const translate = (cn: string, en: string) => en

// One small, ready KB; every other kind empty. `practice` is whatever the test
// hands back — a pending promise (the large bank still loading) or a rejection.
function mockSources(practice: () => Promise<Response>) {
  vi.mocked(apiFetch).mockImplementation(async url => {
    const path = new URL(String(url), 'http://localhost').pathname
    if (path.endsWith('/source-library/practice')) return practice()
    const items = path.endsWith('/source-library/knowledge')
      ? [{ id: 'kb:course', name: 'Course KB', content_workspace_id: '', content_workspace_name: '' }]
      : []
    return new Response(JSON.stringify({ items, unavailable_workspaces: [] }), { status: 200 })
  })
}

it('lets a ready KB be selected while a large practice set is still loading', async () => {
  let resolvePractice!: (response: Response) => void
  const pending = new Promise<Response>(resolve => {
    resolvePractice = resolve
  })
  mockSources(() => pending)

  const { result } = renderHook(() => useTopicSourceLibrary(translate))

  // The KB lands on its own — it does not wait for the practice request.
  await waitFor(() => expect(result.current.library.knowledgeBases).toHaveLength(1))
  expect(result.current.candidates.some(c => c.kind === 'knowledge_base')).toBe(true)
  expect(result.current.library.loadingKinds).toContain('questionSets')
  expect(result.current.library.loadingKinds).not.toContain('knowledgeBases')
  // The aggregate is still busy: the KB is usable *before* everything settles.
  expect(result.current.loading).toBe(true)

  // A large synthetic bank finally arrives — none of it is dropped on the floor.
  const big = Array.from({ length: 5000 }, (_, i) => ({ id: String(i), question: `Q${i}` }))
  await act(async () => {
    resolvePractice(new Response(JSON.stringify({ items: big, unavailable_workspaces: [] }), { status: 200 }))
  })
  await waitFor(() => expect(result.current.loading).toBe(false))
  expect(result.current.library.questionSets).toHaveLength(5000)
  expect(result.current.library.loadingKinds ?? []).toHaveLength(0)
})

it('keeps the KB usable when the practice request fails', async () => {
  mockSources(() => Promise.reject(new Error('practice unavailable')))

  const { result } = renderHook(() => useTopicSourceLibrary(translate))

  await waitFor(() => expect(result.current.loading).toBe(false))
  expect(result.current.library.knowledgeBases).toHaveLength(1)
  expect(result.current.candidates.some(c => c.kind === 'knowledge_base')).toBe(true)
  expect(result.current.library.failures).toContain('practice')
  expect(result.current.library.loadingKinds ?? []).toHaveLength(0)
})

it('renders the ready KB tab while the question bank tab is still loading', () => {
  const kb: SourceCandidate = {
    key: '["","knowledge_base","kb:course"]',
    kind: 'knowledge_base',
    sourceId: 'kb:course',
    label: 'Course KB',
    detail: 'Ready to retrieve',
    available: true,
    expandable: true,
    content_workspace_id: '',
    content_workspace_name: '',
  }
  const library: SourceLibrary = {
    books: [],
    notebooks: [],
    knowledgeBases: [kb],
    chats: [],
    questionSets: [],
    drafts: [],
    partners: [],
    failures: [],
    loadingKinds: ['questionSets'],
  }
  render(
    <SourcesStep
      library={library}
      loading={true}
      selected={new Set()}
      onToggle={vi.fn()}
      childLists={{}}
      onExpand={vi.fn()}
    />
  )

  // Default tab is the KB: its row shows even though the aggregate is loading.
  expect(screen.getByRole('button', { name: /Course KB/ })).toBeInTheDocument()

  // The still-loading question bank shows a spinner, not a misleading empty list.
  fireEvent.click(screen.getByRole('tab', { name: /Question bank/ }))
  expect(screen.queryByText('No matching materials')).not.toBeInTheDocument()
  expect(document.querySelector('.animate-spin')).toBeTruthy()
})