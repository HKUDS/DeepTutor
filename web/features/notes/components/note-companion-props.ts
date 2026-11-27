import type { NoteThreadView } from '../model/threads'
import type { OpenThread, ThreadSendOptions } from './useNoteThreads'

export interface NoteCompanionProps {
  pageId: string
  pageTitle?: string
  thread: OpenThread
  bound: boolean
  threads: NoteThreadView[]
  /** Plain text of a block, for naming where a conversation was held. */
  blockText: (blockId: string) => string | null
  /** A learning block's `learning:<kind>`, else the block type; null once gone. */
  blockKind: (blockId: string) => string | null
  /** Another block the learner clicked while this conversation is under way. */
  focus: string | null
  /** Ask about the clicked block, in a conversation of its own. */
  onAskFocus: (draft: string) => void
  onDismissFocus: () => void
  prefill: { id: number; text: string } | null
  onSend: (content: string, options?: ThreadSendOptions) => void
  /** Insert a learning block after the line and fill it from this thread;
   *  `again` fills the block the thread was opened to regenerate instead. */
  onMake: (kind: string, prompt: string, again?: boolean) => void
  onRegenerate: () => void
  onSelect: (sessionId: string) => void
  onNewHere: () => void
  onJump: () => void
  onSuggestions: () => void
  onClose: () => void
}
