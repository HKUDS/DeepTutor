/**
 * #2762 — the proposal form must say which sources the book was built from.
 *
 * A book created from notebook notes showed "no knowledge bases selected" and
 * claimed it would rely on general knowledge, even though the notes had been
 * captured. The form only ever knew about knowledge bases.
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import BookCreator from '@/app/(workspace)/learning/books/components/BookCreator'
import type { Book, BookProposal } from '@/lib/book-types'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, values?: Record<string, string>) =>
      key.replace(/{{(\w+)}}/g, (_m, name: string) => values?.[name] ?? ''),
    i18n: { language: 'en' },
  }),
}))

vi.mock('@/context/AppShellContext', () => ({
  useAppShell: () => ({ language: 'en' }),
}))

vi.mock('@/hooks/useTopicSourceLibrary', () => ({
  catalogTranslate: () => (key: string) => key,
  useTopicSourceLibrary: () => ({
    library: [],
    loading: false,
    candidates: [],
    childLists: {},
    loadChildren: vi.fn(),
  }),
  hydrateTopicSource: vi.fn(),
  toggleSourceSelection: vi.fn(),
}))

vi.mock('@/components/space/learning/TopicWizardSteps', () => ({
  SourcesStep: () => <div data-testid="sources-step" />,
}))

vi.mock('@/shared/ui/Tooltip', () => ({ default: ({ children }: any) => children }))

const PROPOSAL: BookProposal = {
  title: 'Attention',
  description: 'How attention works',
  scope: 'transformers',
  target_level: 'intermediate',
  estimated_chapters: 5,
  rationale: '',
}

function renderWith(book: Book | null) {
  return render(
    <BookCreator onCreate={vi.fn()} book={book} proposal={PROPOSAL} onConfirmProposal={vi.fn()} />
  )
}

function book(overrides: Partial<Book> = {}): Book {
  return {
    id: 'bk-1',
    revision: 1,
    title: 'Attention',
    description: 'How attention works',
    status: 'draft',
    proposal: PROPOSAL,
    knowledge_bases: [],
    language: 'en',
    page_count: 0,
    chapter_count: 5,
    created_at: 0,
    updated_at: 0,
    metadata: {},
    ...overrides,
  } as Book
}

describe('BookCreator source display (#2762)', () => {
  it('lists notes the book was created from', () => {
    renderWith(
      book({
        sources: [{ kind: 'notebook', label: 'Chapter 3 — attention notes' }],
      })
    )

    expect(screen.getByText('Chapter 3 — attention notes')).toBeInTheDocument()
  })

  it('does not claim a notes-only book relies on general knowledge', () => {
    renderWith(book({ sources: [{ kind: 'notebook', label: 'My notes' }] }))

    expect(
      screen.queryByText('No knowledge bases selected. The book will rely on general knowledge.')
    ).not.toBeInTheDocument()
  })

  it('still shows both knowledge bases and notes together', () => {
    renderWith(
      book({
        knowledge_bases: ['course-kb'],
        sources: [{ kind: 'notebook', label: 'Section notes' }],
      })
    )

    expect(screen.getByText('course-kb')).toBeInTheDocument()
    expect(screen.getByText('Section notes')).toBeInTheDocument()
  })

  it('keeps the general-knowledge notice when there really are no sources', () => {
    renderWith(book({ sources: [] }))

    expect(
      screen.getByText('No knowledge bases selected. The book will rely on general knowledge.')
    ).toBeInTheDocument()
  })

  it('marks a source that could not be read at creation', () => {
    renderWith(
      book({
        sources: [{ kind: 'file', label: 'broken.pdf', available: false }],
      })
    )

    const chip = screen.getByTitle('Selected, but could not be read when this book was created.')
    expect(chip).toHaveTextContent('broken.pdf')
    expect(chip.className).toContain('line-through')
  })
})
