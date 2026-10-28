import { afterEach, expect, it } from 'vitest'
import {
  BlockNoteEditor,
  BlockNoteSchema,
  createBlockSpec,
  defaultBlockSpecs,
} from '@blocknote/core'
import { insertNoteClips, noteClip, type NoteClipInput } from '@/features/notes/model/clip-editing'

const clip = createBlockSpec(
  {
    type: 'clip',
    content: 'none',
    propSchema: {
      title: { default: '' },
      markdown: { default: '' },
      sourceUrl: { default: '' },
      sourceId: { default: '' },
      favoriteType: { default: '' },
      summary: { default: '' },
      metadata: { default: '{}' },
      expanded: { default: false },
    },
  },
  { render: () => ({ dom: document.createElement('div') }) }
)
const schema = BlockNoteSchema.create({ blockSpecs: { ...defaultBlockSpecs, clip: clip() } })
const editors: (typeof schema.BlockNoteEditor)[] = []
afterEach(() => editors.splice(0).forEach(editor => editor._tiptapEditor.destroy()))
const saved = (id: string): NoteClipInput => ({
  title: id,
  markdown: `# ${id}\n\n**Original** $x^2$`,
  sourceId: id,
  sourceUrl: `/notebooks/old-collection?record=${id}`,
  favorite: {
    type: 'video_learning',
    summary: 'Saved excerpt',
    metadata: { video_url: '/video.mp4' },
  },
})

it('preserves nested batch order, complete snapshots and stable IDs through undo/redo and serialization', () => {
  const editor = BlockNoteEditor.create({
    schema,
    initialContent: [
      {
        id: 'parent',
        type: 'toggleListItem',
        content: 'Group',
        children: [{ id: 'anchor', type: 'paragraph', content: 'Start' }],
      },
      { id: 'end', type: 'paragraph', content: 'Keep this' },
    ],
  })
  editors.push(editor)
  editor.mount(document.createElement('div'))
  editor.setTextCursorPosition('anchor', 'end')
  // A nearby text edit must remain separate from a batch insertion.
  editor.insertInlineContent(' typed')
  const before = structuredClone(editor.document)
  insertNoteClips(editor, [saved('a'), saved('b')])
  const batch = structuredClone(editor.document)
  const children = batch[0].children
  expect(children.map(b => b.type)).toEqual(['paragraph', 'clip', 'clip'])
  expect(children.slice(1).map(b => b.props)).toEqual([
    noteClip(saved('a')).props,
    noteClip(saved('b')).props,
  ])
  expect(editor.getTextCursorPosition().block.id).toBe(children[2].id)
  // A second insertion after the selected atomic block must not jump back to the old text cursor.
  insertNoteClips(editor, [saved('c')])
  expect(
    editor.document[0].children.map(b => (b.type === 'clip' ? b.props.sourceId : b.id))
  ).toEqual(['anchor', 'a', 'b', 'c'])
  expect(editor.undo()).toBe(true)
  expect(editor.document).toEqual(batch)
  expect(editor.undo()).toBe(true)
  expect(editor.document).toEqual(before)
  expect(editor.redo()).toBe(true)
  expect(editor.document).toEqual(batch)
  const reopened = BlockNoteEditor.create({
    schema,
    initialContent: JSON.parse(JSON.stringify(editor.document)),
  })
  editors.push(reopened)
  expect(reopened.document).toEqual(batch)
})
