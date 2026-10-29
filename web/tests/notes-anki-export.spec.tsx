import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import NoteTopBar from '@/features/notes/components/NoteTopBar'
import { pageHasFlashcards } from '@/features/notes/model/flashcards'
import type { NoteBlock, NotePage } from '@/lib/notes-api'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('next/link', () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}))
vi.mock('@/components/sidebar/PageBar', () => ({ useShelfFeature: () => null }))
vi.mock('@/components/layout/LocationCrumbs', () => ({
  FeatureCrumb: () => null,
  InstanceCrumb: ({ label }: { label: React.ReactNode }) => <span>{label}</span>,
}))

const flashBlock = (id = 'flash'): NoteBlock => ({
  id,
  type: 'learning',
  props: { kind: 'flashcards', data: '{"cards":[{"front":"Q","back":"A"}]}' },
  children: [],
})

function page(blocks: NoteBlock[] | null): NotePage {
  return {
    id: 'abcdef123456',
    title: 'Fourier',
    content: '',
    blocks,
    parent_id: null,
    icon: '',
    cover: '',
    pinned: false,
    revision: 1,
    created_at: 1,
    updated_at: 1,
  }
}

function openMenu(blocks: NoteBlock[] | null) {
  const onExport = vi.fn()
  render(
    <NoteTopBar
      page={page(blocks)}
      pages={[]}
      invalidParents={new Set()}
      status="Saved"
      busy={false}
      embedded
      treeOpen={false}
      companionOpen={false}
      onToggleTree={vi.fn()}
      onToggleCompanion={vi.fn()}
      onNavigate={vi.fn()}
      onOpenPage={vi.fn()}
      onCreatePage={vi.fn()}
      onMetadata={vi.fn()}
      onInsertFavorite={vi.fn()}
      onExport={onExport}
    />,
  )
  fireEvent.click(screen.getByRole('button', { name: 'More page actions' }))
  return onExport
}

it('hides Export flashcards (Anki) when the page has no flashcard block', () => {
  openMenu([{ id: 'p', type: 'paragraph', props: {}, children: [] }])
  expect(screen.queryByRole('menuitem', { name: 'Export flashcards (Anki)' })).toBeNull()
})

it('shows Export flashcards (Anki) for nested flashcard blocks and exports as anki', () => {
  const onExport = openMenu([
    {
      id: 'cols',
      type: 'noteColumns',
      props: {},
      children: [{ id: 'left', type: 'noteColumn', props: {}, children: [flashBlock('nested')] }],
    },
  ])
  fireEvent.click(screen.getByRole('menuitem', { name: 'Export flashcards (Anki)' }))
  expect(onExport).toHaveBeenCalledWith('anki')
})

it('detects nested flashcard blocks and ignores other learning kinds', () => {
  expect(pageHasFlashcards([flashBlock()])).toBe(true)
  expect(
    pageHasFlashcards([
      {
        id: 'cols',
        type: 'noteColumns',
        props: {},
        children: [{ id: 'left', type: 'noteColumn', props: {}, children: [flashBlock('n')] }],
      },
    ]),
  ).toBe(true)
  expect(
    pageHasFlashcards([
      { id: 'quiz', type: 'learning', props: { kind: 'quiz' }, children: [] },
    ]),
  ).toBe(false)
  expect(pageHasFlashcards(null)).toBe(false)
})
