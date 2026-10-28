import { closeHistory } from '@tiptap/pm/history'
import type { Transaction } from '@tiptap/pm/state'
import type { FavoriteSnapshot } from '@/lib/favorite-content'

export interface NoteClipInput {
  title: string
  markdown: string
  sourceUrl: string
  sourceId?: string
  favorite?: FavoriteSnapshot
}

export function noteClip(input: NoteClipInput) {
  return {
    type: 'clip' as const,
    props: {
      title: input.title,
      markdown: input.markdown,
      sourceUrl: input.sourceUrl,
      sourceId: input.sourceId || '',
      favoriteType: input.favorite?.type || '',
      summary: input.favorite?.summary || '',
      metadata: JSON.stringify(input.favorite?.metadata || {}),
      expanded: false,
    },
  }
}

interface ClipEditor {
  transact: <T>(callback: (tr: Transaction) => T) => T
  getTextCursorPosition: () => { block: { id: string } }
  insertBlocks: (
    blocks: ReturnType<typeof noteClip>[],
    id: string,
    side: 'after'
  ) => { id: string }[]
  setTextCursorPosition: (id: string, placement: 'end') => void
}

/** Preserve list order and nesting; a whole picker submission is one undo step. */
export function insertNoteClips(editor: ClipEditor, inputs: NoteClipInput[]) {
  if (!inputs.length) return
  const anchor = editor.getTextCursorPosition().block.id
  editor.transact(tr => {
    closeHistory(tr)
    const inserted = editor.insertBlocks(inputs.map(noteClip), anchor, 'after')
    const last = inserted.at(-1)
    if (last) editor.setTextCursorPosition(last.id, 'end')
  })
  editor.transact(tr => closeHistory(tr))
}
