import type { NoteThread } from '@/lib/notes-api'
import { formatRelativeTime } from '@/lib/relative-time'

/** What a page conversation's orb shows. */
export type NoteThreadState = 'idle' | 'running' | 'failed' | 'unread'

export interface NoteThreadView extends NoteThread {
  state: NoteThreadState
  /** Its title, or the passage it was about while it has none. */
  label: string
}

/**
 * The page's threads as the page draws them.
 *
 * The server's status is a snapshot from the last list; a turn this tab is
 * streaming is running whatever the snapshot says. A thread answered since
 * it was last read (its update is newer than when it was last seen) is
 * unread, so an orb that finished while folded says so.
 */
export function threadViews(
  threads: NoteThread[],
  {
    running,
    seen,
    openSessionId,
    untitled,
  }: {
    running: ReadonlySet<string>
    seen: Readonly<Record<string, number>>
    openSessionId: string | null
    untitled: string
  }
): NoteThreadView[] {
  return [...threads]
    .sort((a, b) => a.created_at - b.created_at)
    .map(thread => {
      const live = running.has(thread.session_id)
      const state: NoteThreadState =
        live || thread.status === 'running'
          ? 'running'
          : thread.status === 'failed'
            ? 'failed'
            : thread.session_id !== openSessionId &&
                (seen[thread.session_id] ?? thread.created_at) < thread.updated_at - 1
              ? 'unread'
              : 'idle'
      // The server's placeholder until a title is generated is not a title.
      // A title made from a first message that opened with the quoted passage
      // starts with the quote mark; it names the conversation without it.
      const raw = thread.title.trim().replace(/^(>\s*:?\s*)+/, '')
      const title = raw === 'New conversation' ? '' : raw
      return {
        ...thread,
        title,
        state,
        label: title || thread.quote.trim() || untitled,
      }
    })
}

export function relativeTime(seconds: number, language: string) {
  return seconds ? formatRelativeTime(seconds, language) : ''
}

/** Plain text of a block's inline content: what the anchor card quotes. */
export function inlineText(content: unknown): string {
  if (!Array.isArray(content)) return ''
  return content
    .map(item => {
      const node = item as {
        text?: string
        content?: unknown
        props?: { title?: string; formula?: string }
      }
      return node.text ?? node.props?.title ?? node.props?.formula ?? inlineText(node.content)
    })
    .join('')
}
