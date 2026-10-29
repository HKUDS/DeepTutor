import type { NoteBlock } from '@/lib/notes-api'

/** True when the page contains at least one Flash Cards learning block. */
export function pageHasFlashcards(blocks: NoteBlock[] | null | undefined): boolean {
  for (const block of blocks ?? []) {
    if (block.type === 'learning' && block.props?.kind === 'flashcards') return true
    if (pageHasFlashcards(block.children)) return true
  }
  return false
}
