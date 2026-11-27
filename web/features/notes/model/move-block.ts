import type { NoteBlock } from '@/lib/notes-api'

const find = (items: NoteBlock[], id: string): NoteBlock | undefined => {
    for (const block of items) {
      if (block.id === id) return block
      const child = find(block.children || [], id)
      if (child) return child
    }
}

export function canMoveNoteBlock(blocks: NoteBlock[], sourceId: string, targetId: string) {
  const source = find(blocks, sourceId)
  return !!source && sourceId !== targetId && !find(source.children || [], targetId) && !!find(blocks, targetId)
}

/** Relocate a complete subtree without regenerating any of its stable IDs. */
export function moveNoteBlock(blocks: NoteBlock[], sourceId: string, targetId: string, side: 'before' | 'after') {
  if (!canMoveNoteBlock(blocks, sourceId, targetId)) return null
  const result = structuredClone(blocks)
  const source = find(result, sourceId)
  if (!source) return null
  const remove = (items: NoteBlock[]): boolean => {
    const index = items.findIndex(block => block.id === sourceId)
    if (index >= 0) { items.splice(index, 1); return true }
    return items.some(block => remove(block.children || []))
  }
  const insert = (items: NoteBlock[]): boolean => {
    const index = items.findIndex(block => block.id === targetId)
    if (index >= 0) { items.splice(index + Number(side === 'after'), 0, source); return true }
    return items.some(block => insert(block.children || []))
  }
  remove(result)
  insert(result)
  return result
}
