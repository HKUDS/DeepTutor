import { fireEvent, render, screen, within } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { LearningNavigation } from '@/components/sidebar/LearningNavigation'
import type { LearningSources } from '@/lib/learning-dashboard'
import type { SessionSummary } from '@/lib/session-api'

vi.mock('next/navigation', () => ({
  usePathname: () => '/learning',
  useSearchParams: () => new URLSearchParams(),
}))
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }),
}))
vi.mock('@/components/layout/AppShell', () => ({ useSidebarDrawer: () => null }))
const fixture = vi.hoisted(() => ({ sources: {} as LearningSources }))
vi.mock('@/hooks/useLearningIndex', () => ({
  useLearningIndex: () => ({
    loading: false,
    failed: [],
    retry: vi.fn(),
    sources: fixture.sources,
  }),
}))

function session(
  id: string,
  title: string,
  preferences: SessionSummary['preferences'] = {}
): SessionSummary {
  return {
    id,
    session_id: id,
    title,
    created_at: 100,
    updated_at: 900,
    content_workspace_id: 'physics',
    message_count: 1,
    last_message: '',
    preferences,
  }
}

function topic(id: string, name: string, updated = 50): LearningSources['mastery'][number] {
  return {
    path_id: id,
    name,
    updated_at: updated,
    content_workspace_id: 'physics',
    reviews: [],
    sources: [],
    path_revision: 1,
    learner_profile: null,
    session_count: 0,
    metadata: {
      path_id: id,
      status: 'active',
      goal: name,
      created_at: 10,
      updated_at: updated,
      description: '',
      emoji: '',
      map_seed: 1,
    },
    map: {
      name,
      counts: { total: 2, mastered: 1, learning: 1, new: 0 },
      modules: [],
      due_reviews: 0,
      complete: false,
    },
    next: {
      action: 'assess',
      knowledge_point_id: 'kp1',
      knowledge_point_name: 'Vectors',
      knowledge_point_type: 'concept',
      status: 'learning',
      gate: 'qualitative',
      mastery: 0,
      threshold: 1,
      reason: '',
      forgetting_risk: 0,
      pending_prompt: '',
      session_id: '',
    },
  }
}

function show(sessions: SessionSummary[] = []) {
  return render(
    <LearningNavigation
      sessions={{
        rows: sessions,
        activeSessionId: null,
        render: rows => (
          <ul>
            {rows.map(row => (
              <li key={row.session_id}>{row.title}</li>
            ))}
          </ul>
        ),
      }}
    />
  )
}

const records = () => within(screen.getByRole('region', { name: 'navigation.learningRecords' }))
const choose = (value: string) =>
  fireEvent.change(screen.getByRole('combobox', { name: 'Filter by type' }), { target: { value } })

beforeEach(() => {
  localStorage.clear()
  fixture.sources = {
    books: [
      {
        id: 'b1',
        title: 'Mechanics book',
        created_at: 20,
        updated_at: 30,
        revision: 1,
        description: '',
        status: 'ready',
        proposal: null,
        knowledge_bases: [],
        language: 'en',
        page_count: 0,
        chapter_count: 0,
        metadata: {},
      },
    ],
    mastery: [topic('p1', 'Vectors path')],
    reading: [
      {
        workspace_id: 'r1',
        title: 'Lecture collection',
        created_at: 10,
        updated_at: 40,
        description: '',
        active_material_id: null,
        tabs: [],
      },
    ],
    watching: [session('v1', 'Legacy video', { capability: 'immersive_watching' })],
    practice: [
      {
        id: 1,
        question: 'Dot product exercise',
        session_id: 'set',
        session_title: 'Practice set',
        created_at: 20,
        updated_at: 60,
        content_workspace_id: 'physics',
      },
      {
        id: 2,
        question: 'Cross product exercise',
        session_id: 'set',
        session_title: 'Practice set',
        created_at: 30,
        updated_at: 70,
        content_workspace_id: 'physics',
      },
    ],
  }
})

it('starts with all record types and restores them when the filter is cleared', () => {
  const view = show()
  const select = screen.getByRole('combobox', { name: 'Filter by type' })
  expect(select).toHaveValue('all')
  expect(
    within(select)
      .getAllByRole('option')
      .map(option => option.textContent)
  ).toEqual(['All', 'Mastery Path', 'Practice', 'Books', 'Immersive Reading'])
  expect(records().getAllByRole('link')).toHaveLength(5)
  choose('books')
  expect(records().getAllByRole('link')).toHaveLength(1)
  expect(records().getByRole('link')).toHaveTextContent('Mechanics book')
  choose('all')
  expect(records().getAllByRole('link')).toHaveLength(5)
  choose('mastery')
  view.unmount()
  show()
  expect(screen.getByRole('combobox', { name: 'Filter by type' })).toHaveValue('all')
})

it.each<[string, string[], string[]]>([
  ['mastery', ['Vectors path'], ['Archived path chat']],
  ['practice', ['Practice set'], []],
  ['books', ['Mechanics book'], ['Deleted book chat']],
  [
    'reading',
    ['Legacy video', 'Lecture collection'],
    ['Deleted collection chat', 'Unindexed video'],
  ],
])(
  'filters %s records and orphan conversations using their owning surface',
  (kind, titles, loose) => {
    const sessions = [
      session('orphan-path', 'Archived path chat', {
        workspace_mode: 'mastery_path',
        mastery_path_id: 'archived',
      }),
      session('orphan-book', 'Deleted book chat', { book_id: 'deleted', book_page_id: 'page' }),
      session('orphan-reading', 'Deleted collection chat', {
        workspace_mode: 'immersive_reading',
        reading_workspace_id: 'deleted',
      }),
      session('orphan-video', 'Unindexed video', { workspace_mode: 'immersive_watching' }),
      session('unknown', 'Unclassified chat'),
      session('capability-only', 'Ordinary chat using a mastery tool', {
        capability: 'mastery_path',
        mastery_path_id: 'p1',
      }),
    ]
    show(sessions)
    choose(kind)
    const list = records()
    const links = list.getAllByRole('link')
    expect(links).toHaveLength(titles.length)
    titles.forEach((title, index) => expect(links[index]).toHaveTextContent(title))
    for (const row of sessions) {
      if (loose.includes(row.title)) expect(list.getByText(row.title)).toBeVisible()
      else expect(list.queryByText(row.title)).toBeNull()
    }
    choose('all')
    expect(records().getByText('Unclassified chat')).toBeVisible()
    expect(records().getByText('Ordinary chat using a mastery tool')).toBeVisible()
  }
)

it('keeps a path and its conversations together while combining type and child search', () => {
  show([
    session('s1', 'Dot product discussion', {
      workspace_mode: 'mastery_path',
      mastery_path_id: 'p1',
    }),
  ])
  choose('mastery')
  fireEvent.click(records().getByRole('button', { name: 'navigation.showRecordChats' }))
  expect(records().getByText('Dot product discussion')).toBeVisible()
  choose('practice')
  expect(records().queryByText('Dot product discussion')).toBeNull()
  choose('mastery')
  expect(records().getByText('Dot product discussion')).toBeVisible()
  fireEvent.click(records().getByRole('button', { name: 'navigation.hideRecordChats' }))
  fireEvent.click(screen.getByRole('button', { name: 'navigation.searchLearning' }))
  const search = screen.getByRole('searchbox', { name: 'navigation.searchLearning' })
  fireEvent.change(search, { target: { value: 'Dot product' } })
  expect(records().getByRole('link')).toHaveAttribute(
    'href',
    '/learning/mastery/p1?dt_workspace=physics'
  )
  expect(records().getByText('Dot product discussion')).toBeVisible()
  choose('practice')
  expect(search).toHaveValue('Dot product')
  expect(records().getByText('Practice set')).toBeVisible()
  expect(records().getByText('Dot product exercise')).toBeVisible()
  expect(records().queryByText('Dot product discussion')).toBeNull()
  expect(records().getByRole('link', { name: /Dot product exercise/ })).toHaveAttribute(
    'href',
    '/learning/practice?question=1&dt_workspace=physics'
  )
  choose('books')
  expect(records().getByText('navigation.noResults')).toBeVisible()
})

it('keeps record ownership scoped when two workspaces have the same path id', () => {
  fixture.sources.mastery.push({
    ...topic('p1', 'Chemistry path'),
    content_workspace_id: 'chemistry',
  })
  show([
    session('physics-chat', 'Momentum chat', {
      workspace_mode: 'mastery_path',
      mastery_path_id: 'p1',
    }),
    {
      ...session('chemistry-chat', 'Reaction chat', {
        workspace_mode: 'mastery_path',
        mastery_path_id: 'p1',
      }),
      content_workspace_id: 'chemistry',
    },
  ])
  choose('mastery')
  fireEvent.click(screen.getByRole('button', { name: 'navigation.searchLearning' }))
  fireEvent.change(screen.getByRole('searchbox', { name: 'navigation.searchLearning' }), {
    target: { value: 'Reaction' },
  })
  expect(records().getByRole('link')).toHaveAttribute(
    'href',
    '/learning/mastery/p1?dt_workspace=chemistry'
  )
  expect(records().getByText('Reaction chat')).toBeVisible()
  expect(records().queryByText('Momentum chat')).toBeNull()
  expect(records().queryByText('Vectors path')).toBeNull()
})

it('filters the whole list before pagination and resets show-more when switching types', () => {
  fixture.sources.practice = Array.from({ length: 40 }, (_, i) => ({
    id: i + 1,
    question: `Question ${i + 1}`,
    created_at: 1000 + i,
    updated_at: 1000 + i,
  }))
  show()
  expect(records().getAllByRole('link')).toHaveLength(30)
  expect(records().queryByText('Vectors path')).toBeNull()
  choose('mastery')
  expect(records().getByRole('link')).toHaveTextContent('Vectors path')
  choose('practice')
  fireEvent.click(records().getByRole('button', { name: 'Show more' }))
  expect(records().getAllByRole('link')).toHaveLength(40)
  choose('books')
  choose('practice')
  expect(records().getAllByRole('link')).toHaveLength(30)
  expect(records().getByRole('button', { name: 'Show more' })).toBeVisible()
})

it('preserves the selected sort and time groups across filters', () => {
  const now = Math.floor(Date.now() / 1000)
  const earlier = now - 60 * 60 * 24 * 30
  fixture.sources.practice = [
    { id: 1, question: 'Old exercise studied today', created_at: earlier, updated_at: now },
    { id: 2, question: 'New exercise', created_at: now - 60, updated_at: now - 60 },
  ]
  show()
  choose('practice')
  expect(records().getAllByRole('link')[0]).toHaveTextContent('Old exercise studied today')
  fireEvent.click(screen.getByRole('button', { name: 'navigation.sortRecords' }))
  fireEvent.click(screen.getByRole('menuitemradio', { name: 'navigation.createdTime' }))
  expect(records().getAllByRole('link')[0]).toHaveTextContent('New exercise')
  expect(records().getByRole('heading', { name: 'Today' })).toBeVisible()
  expect(records().getByRole('heading', { name: 'Earlier' })).toBeVisible()
  choose('mastery')
  choose('practice')
  expect(records().getAllByRole('link')[0]).toHaveTextContent('New exercise')
  expect(records().getByRole('heading', { name: 'Earlier' })).toBeVisible()
})

it('distinguishes a filtered empty list from a library with no learning records', () => {
  fixture.sources.books = []
  show()
  choose('books')
  expect(records().getByText('navigation.noResults')).toBeVisible()
  expect(records().queryByText('navigation.noLearning')).toBeNull()
  choose('all')
  expect(records().getAllByRole('link')).toHaveLength(4)
})
