import { act, fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { Schema } from '@tiptap/pm/model'
import { EditorState, type Plugin } from '@tiptap/pm/state'
import { EditorView } from '@tiptap/pm/view'
import NoteInlineReviews from '@/features/notes/components/NoteInlineReviews'
import type { NotesEditor } from '@/features/notes/components/NoteEditor'
import type { NoteSuggestion } from '@/lib/notes-api'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('@/features/notes/components/NoteSuggestionContent', () => ({
  default: ({ markdown }: { markdown: string }) => <p>{markdown}</p>,
}))

it('renders and approves each proposal at its target without adding review UI to document data', () => {
  const schema = new Schema({
    nodes: {
      doc: { content: 'blockGroup' },
      blockGroup: { content: 'blockContainer+', toDOM: () => ['div', 0] },
      blockContainer: {
        attrs: { id: { default: null } },
        content: 'paragraph',
        toDOM: node => ['div', { 'data-id': node.attrs.id }, 0],
      },
      paragraph: { content: 'text*', toDOM: () => ['p', 0] },
      text: {},
    },
  })
  const doc = schema.node(
    'doc',
    null,
    schema.node(
      'blockGroup',
      null,
      ['first', 'last'].map(id =>
        schema.node('blockContainer', { id }, schema.node('paragraph', null, schema.text(id)))
      )
    )
  )
  const mount = document.createElement('div')
  document.body.append(mount)
  const listeners = new Set<() => void>()
  const view = new EditorView(mount, {
    state: EditorState.create({ doc }),
    dispatchTransaction: tr => {
      view.updateState(view.state.apply(tr))
      listeners.forEach(listener => listener())
    },
  })
  const tiptap = {
    on: (_event: string, listener: () => void) => listeners.add(listener),
    off: (_event: string, listener: () => void) => listeners.delete(listener),
    view,
    get state() {
      return view.state
    },
    registerPlugin(plugin: Plugin) {
      view.updateState(view.state.reconfigure({ plugins: [plugin] }))
    },
    unregisterPlugin() {
      view.updateState(view.state.reconfigure({ plugins: [] }))
    },
  }
  const editor = { _tiptapEditor: tiptap } as unknown as NotesEditor
  const suggestion: NoteSuggestion = {
    id: 's1',
    block_id: 'first',
    operation: 'replace',
    markdown: 'Proposed first',
    explanation: 'Reason',
    original: null,
    anchors: [{ id: 'last', side: 'before' }],
    blocks: null,
    status: 'pending',
  }
  const onReview = vi.fn()
  const props = { editor, suggestions: [suggestion], busy: false, onReview, onDiscuss: vi.fn() }
  const ui = render(<NoteInlineReviews {...props} />)
  const host = mount.querySelector('[data-review-for="first"]')!
  expect(host.previousElementSibling?.getAttribute('data-id')).toBe('first')
  expect(host.nextElementSibling?.getAttribute('data-id')).toBe('last')
  expect(view.state.doc.textContent).toBe('firstlast')
  fireEvent.click(screen.getByRole('button', { name: 'Accept' }))
  expect(onReview).toHaveBeenCalledWith(suggestion, true)
  expect(view.state.doc.textContent).toBe('firstlast')
  const second = { ...suggestion, id: 's2', block_id: 'last', markdown: 'Proposed last' }
  ui.rerender(<NoteInlineReviews {...props} suggestions={[{ ...suggestion }, second]} />)
  expect(mount.querySelector('[data-review-for="first"]')).toBe(host)
  expect(host).toHaveTextContent('Proposed first')
  expect(mount.querySelector('[data-review-for="last"]')).toHaveTextContent('Proposed last')
  ui.rerender(
    <NoteInlineReviews
      {...props}
      suggestions={[suggestion, second]}
      errors={{ s1: 'Your edits are safe' }}
    />
  )
  expect(host.querySelector('[role="alert"]')).toHaveTextContent('Your edits are safe')
  expect(mount.querySelector('[data-review-for="last"] [role="alert"]')).toBeNull()
  act(() => view.dispatch(view.state.tr.delete(1, 1 + doc.firstChild!.firstChild!.nodeSize)))
  expect(host.nextElementSibling?.getAttribute('data-id')).toBe('last')
  expect(host).toHaveTextContent('The original block was removed.')
  expect(host.querySelector('.dt-note-review-accept')).toBeDisabled()
  act(() => view.dispatch(view.state.tr.insert(1, doc.firstChild!.firstChild!)))
  expect(host.previousElementSibling?.getAttribute('data-id')).toBe('first')
  expect(host.querySelector('.dt-note-review-accept')).toBeEnabled()
  fireEvent.click(screen.getAllByRole('button', { name: 'Dismiss suggestion' })[0])
  expect(onReview).toHaveBeenLastCalledWith(suggestion, false)
  ui.rerender(<NoteInlineReviews {...props} suggestions={[]} />)
  expect(mount.querySelector('[data-review-for]')).toBeNull()
  ui.unmount()
  view.destroy()
  mount.remove()
})
