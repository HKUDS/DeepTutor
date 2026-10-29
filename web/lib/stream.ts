import type { StreamEvent } from '@/features/chat/model/protocol'

type ContentMeta = {
  call_id?: string
  call_kind?: string
  call_state?: string
  call_role?: string
  answer_visible?: boolean
  trace_kind?: string
}

function eventMeta(event: StreamEvent): ContentMeta {
  return (event.metadata ?? {}) as ContentMeta
}

export function shouldAppendEventContent(event: StreamEvent): boolean {
  if (event.type !== 'content') return false
  const meta = eventMeta(event)
  if (!meta.call_id) return true
  // The chat agent loop streams every round's text as `content`, and all of
  // it is the answer — the commentary a round wrote before calling a tool
  // included. Completion markers cannot retract published prose.
  return meta.call_kind === 'llm_final_response' || meta.call_kind === 'agent_loop_round'
}

/** Replay every published answer chunk in order. */
export function recomputeAnswerContent(events: StreamEvent[]): string {
  return events
    .filter(shouldAppendEventContent)
    .map(event => event.content)
    .join('')
}
