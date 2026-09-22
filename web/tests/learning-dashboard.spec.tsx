import React from 'react'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { LearningDashboard } from '@/components/learning/LearningDashboard'

const mock = vi.hoisted(() => ({
  books: vi.fn(),
  topics: vi.fn(),
  reading: vi.fn(),
  sessions: vi.fn(),
}))
vi.mock('@/lib/book-api', () => ({ bookApi: { list: mock.books } }))
vi.mock('@/lib/learning-api', () => ({ fetchMasteryTopics: mock.topics }))
vi.mock('@/lib/reading-workspace-api', () => ({ listReadingWorkspaces: mock.reading }))
vi.mock('@/lib/api', () => ({
  apiUrl: (url: string) => url,
  apiFetch: vi.fn(async () => {
    const failed: string[] = []
    const fallback = (kind: string) => { failed.push(kind); return [] }
    const [books, mastery, reading, watching] = await Promise.all([
      mock.books().then((result: { books: unknown[] }) => result.books).catch(() => fallback('books')),
      mock.topics().catch(() => fallback('mastery')),
      mock.reading().catch(() => fallback('reading')),
      mock.sessions().catch(() => fallback('watching')),
    ])
    return { ok: true, json: async () => ({ sources: { books, mastery, reading, watching }, failed }) }
  }),
}))
vi.mock('@/hooks/useChatWorkspaces', () => ({ useChatWorkspaces: () => ({
  workspaces: [{ workspace_id: 'ws_a', display_name: 'Physics', kind: 'workspace', status: 'ready' }], error: ''
}) }))
/**
 * The card-to-panel morph is framer-motion's to render, and its exit animation
 * never settles under jsdom — the panel would stay mounted for good. What a
 * test can hold is the behaviour around the morph, so motion elements stand in
 * as plain ones here and `AnimatePresence` mounts and unmounts at once.
 */
vi.mock('framer-motion', async () => {
  const { createElement } = await import('react')
  const strip = (props: Record<string, unknown>) => {
    const plain: Record<string, unknown> = {}
    const motionOnly = new Set([
      'layoutId',
      'layout',
      'initial',
      'animate',
      'exit',
      'transition',
      'variants',
      'whileHover',
      'whileTap',
      'layoutRoot',
    ])
    for (const [name, value] of Object.entries(props))
      if (!motionOnly.has(name)) plain[name] = value
    return plain
  }
  const cache: Record<string, unknown> = {}
  const motion = new Proxy(cache, {
    get: (store, tag: string) =>
      (store[tag] ??= (props: Record<string, unknown>) => createElement(tag, strip(props))),
  })
  return {
    motion,
    m: motion,
    AnimatePresence: ({ children }: { children?: unknown }) => children,
    useReducedMotion: () => false,
  }
})
const t = (key: string) => ({ Home: '主页', Settings: '设置', Memory: '记忆' })[key] || key
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t, i18n: { language: 'en' } }) }))

beforeEach(() => {
  vi.clearAllMocks()
  mock.books.mockResolvedValue({
    books: [{ id: 'b', title: 'Home', updated_at: 10, status: 'ready', metadata: {} }],
  })
  mock.topics.mockResolvedValue([])
  mock.reading.mockResolvedValue([])
  mock.sessions.mockResolvedValue([
    {
      session_id: 'v',
      title: 'Memory',
      updated_at: 20,
      preferences: { workspace_mode: 'immersive_watching' },
    },
  ])
})

it('a failed source preserves other activities and user titles are never translated', async () => {
  mock.reading.mockRejectedValue(new Error('offline'))
  render(<LearningDashboard />)
  expect(await screen.findByRole('link', { name: /Home/ })).toHaveAttribute(
    'href',
    '/learning/books/b?dt_workspace='
  )
  expect(screen.getByRole('link', { name: /Memory/ })).toHaveAttribute(
    'href',
    '/learning/watching/v?dt_workspace='
  )
  expect(screen.queryByText('主页')).toBeNull()
  expect(screen.getByRole('alert')).toBeInTheDocument()
  expect(screen.queryByText('What needs your attention')).toBeNull()
  mock.reading.mockResolvedValue([])
  fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
  await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
})

it('a failed refresh keeps already loaded work visible', async () => {
  render(<LearningDashboard />)
  await screen.findByRole('link', { name: /Home/ })
  mock.books.mockRejectedValue(new Error('offline'))
  await act(async () => {
    window.dispatchEvent(new Event('focus'))
  })
  expect(await screen.findByRole('alert')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /Home/ })).toBeInTheDocument()
})

it('a way introduces itself before it commits you, and hands focus back', async () => {
  render(<LearningDashboard />)
  const card = await screen.findByRole('button', { name: /Mastery Path/ })
  fireEvent.click(card)
  const panel = await screen.findByRole('dialog')
  expect(panel).toHaveTextContent('You and the tutor settle the outline together')
  expect(screen.getByRole('link', { name: 'Start' })).toHaveAttribute('href', '/learning/mastery')
  fireEvent.click(screen.getByRole('button', { name: 'Go back' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect(card).toHaveFocus()
})

it('feature introductions do not show personal activity or source failures', async () => {
  mock.reading.mockRejectedValue(new Error('offline'))
  render(<LearningDashboard />)
  await screen.findByRole('alert')
  const books = screen.getByRole('button', { name: /Books/ })
  expect(books).not.toHaveTextContent('Home')
  const reading = screen.getByRole('button', { name: /Immersive Reading/ })
  expect(reading).not.toHaveTextContent('Nothing here yet.')
  expect(reading).not.toHaveTextContent('Could not be loaded just now.')
  fireEvent.click(books)
  expect(screen.getByRole('dialog')).not.toHaveTextContent('Home')
  expect(screen.getByRole('dialog')).not.toHaveTextContent('{{count}} books')
})

it('contains focus and restores background interaction on Escape', async () => {
  const { container } = render(<LearningDashboard />)
  const card = await screen.findByRole('button', { name: /Mastery Path/ })
  fireEvent.click(card)
  const panel = screen.getByRole('dialog')
  expect(panel).toHaveFocus()
  expect(container.inert).toBe(true)
  expect(document.body.style.overflow).toBe('hidden')
  fireEvent.keyDown(panel, { key: 'Tab', shiftKey: true })
  const start = screen.getByRole('link', { name: 'Start' })
  expect(start).toHaveFocus()
  fireEvent.keyDown(start, { key: 'Tab' })
  expect(screen.getByRole('button', { name: 'Close' })).toHaveFocus()
  fireEvent.keyDown(panel, { key: 'Escape' })
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect(container.inert).not.toBe(true)
  expect(document.body.style.overflow).not.toBe('hidden')
  expect(card).toHaveFocus()
})

it.each([
  ['Books', '/learning/books'],
  ['Mastery Path', '/learning/mastery'],
  ['Immersive Reading', '/learning/reading'],
  ['Immersive Watching', '/learning/watching'],
])('opens the complete library without assigning a workspace for %s', async (label, route) => {
  render(<LearningDashboard />)
  fireEvent.click(await screen.findByRole('button', { name: new RegExp(label) }))
  expect(screen.queryByRole('button', { name: 'Workspace' })).toBeNull()
  expect(screen.getByRole('link', { name: 'Start' })).toHaveAttribute('href', route)
})
