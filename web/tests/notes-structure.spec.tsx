import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import NotePageTree from '@/features/notes/components/NotePageTree'
import NotePageActions from '@/features/notes/components/NotePageActions'
import { pageDescendants } from '@/features/notes/model/page-tree'
import { moveNoteBlock } from '@/features/notes/model/move-block'
import type { NoteBlock, NoteSummary } from '@/lib/notes-api'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string, vars?: {page: string}) => key.replace('{{page}}', vars?.page || '') }) }))
const block = (id: string, children: NoteBlock[] = []): NoteBlock => ({ id, type: 'paragraph', props: {}, content: [{type: 'text', text: id, styles: {}}], children })
const pages = [
  {id: 'root', title: 'Root', parent_id: null},
  {id: 'child', title: 'Long child page title', parent_id: 'root'},
  {id: 'leaf', title: 'Leaf', parent_id: 'child'},
] as NoteSummary[]
it('moves nested subtrees without losing IDs or siblings and prevents self-nesting', () => {
  const original = [block('first'), block('parent', [block('child', [block('leaf')]), block('sibling')]), block('last')]
  const moved = moveNoteBlock(original, 'child', 'first', 'before')!
  expect(moved.map(b => b.id)).toEqual(['child', 'first', 'parent', 'last'])
  expect(moved[0].children).toEqual([block('leaf')])
  expect(moved[2].children).toEqual([block('sibling')])
  expect(original[1].children).toHaveLength(2)
  expect(moveNoteBlock(original, 'parent', 'leaf', 'after')).toBeNull()
  expect(moveNoteBlock(original, 'parent', 'parent', 'after')).toBeNull()
  expect(moveNoteBlock(original, 'missing', 'last', 'after')).toBeNull()
  const back = moveNoteBlock(moved, 'child', 'sibling', 'before')
  expect(back).toEqual(original)
})
it('allows folding page branches and identifies the current page', () => {
  const onNavigate = vi.fn((event: React.MouseEvent) => event.preventDefault())
  render(<NotePageTree pages={pages} currentId="child" busy={false} onNavigate={onNavigate} onClose={vi.fn()} onCreate={vi.fn()} onDelete={vi.fn()} />)
  const current = screen.getByRole('link', {name: 'Long child page title'})
  expect(current).toHaveAttribute('aria-current', 'page')
  fireEvent.click(screen.getByRole('button', {name: 'Collapse Root'}))
  expect(screen.queryByRole('link', {name: 'Long child page title'})).toBeNull()
  fireEvent.click(screen.getByRole('button', {name: 'Expand Root'}))
  fireEvent.click(screen.getByRole('link', {name: 'Long child page title'}))
  expect(onNavigate).toHaveBeenCalledWith(expect.anything(), 'child')
  expect(pageDescendants(pages, 'root')).toEqual(new Set(['root', 'child', 'leaf']))
})

it('applies right-click and keyboard menu actions to their row while another page is open', async () => {
  const onDelete = vi.fn()
  const onNavigate = vi.fn()
  render(<NotePageTree pages={pages} currentId="root" busy={false} onNavigate={onNavigate} onCreate={vi.fn()} onDelete={onDelete} />)
  fireEvent.contextMenu(screen.getByRole('link', { name: 'Long child page title' }))
  expect((await screen.findByRole('menu')).parentElement).toBe(document.body)
  fireEvent.click(await screen.findByRole('menuitem', { name: 'Delete' }))
  expect(screen.getByRole('status')).toHaveTextContent('Long child page title')
  expect(screen.getByRole('status')).toHaveTextContent('subpages move up')
  expect(onDelete).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('menuitem', { name: 'Delete page' }))
  expect(onDelete).toHaveBeenCalledWith(pages[1])
  fireEvent.click(screen.getByRole('button', { name: 'Page actions for Leaf' }))
  expect(screen.getByRole('menuitem', { name: 'Delete' })).toHaveFocus()
  fireEvent.keyDown(document.activeElement!, { key: 'Escape' })
  expect(screen.queryByRole('menu')).toBeNull()
  expect(screen.getByRole('button', { name: 'Page actions for Leaf' })).toHaveFocus()
  fireEvent.click(screen.getByRole('button', { name: 'Page actions for Leaf' }))
  fireEvent.click(screen.getByRole('menuitem', { name: 'Delete' }))
  fireEvent.click(screen.getByRole('menuitem', { name: 'Delete page' }))
  expect(onDelete).toHaveBeenCalledWith(pages[2])
  expect(onNavigate).not.toHaveBeenCalled()
})

it.each([true, false])('keeps card confirmation compact (has children: %s)', hasChildren => {
  const title = 'Long page title '.repeat(20)
  const onDelete = vi.fn()
  render(<NotePageActions compact page={{ title }} hasChildren={hasChildren} onDelete={onDelete} />)
  fireEvent.click(screen.getByRole('menuitem', { name: 'Delete' }))
  expect(screen.queryByText(title.trim())).toBeNull()
  expect(!!screen.queryByText(/subpages move up/)).toBe(hasChildren)
  expect(onDelete).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('menuitem', { name: 'Confirm delete' }))
  expect(onDelete).toHaveBeenCalledTimes(1)
})
