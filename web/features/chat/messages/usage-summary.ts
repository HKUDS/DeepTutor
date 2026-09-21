import type { StreamEvent } from '@/features/chat/model/protocol'

export interface UsageSummary {
  total_tokens?: number
  prompt_tokens?: number
  completion_tokens?: number
  cache_read_input_tokens?: number
  cache_creation_input_tokens?: number
  reasoning_tokens?: number
  total_calls?: number
  cache_write_reported_calls?: number
  cache_reported_calls?: number
  cache_input_tokens?: number
  cache_hit_rate?: number | null
  ttft_seconds?: number | null
  ttft_calls?: number
  duration_seconds?: number
  generation_seconds?: number | null
  timed_completion_tokens?: number
  tokens_per_second?: number | null
  estimated_calls?: number
  call_details?: CallUsage[]
}
export interface CallUsage extends UsageSummary {
  model?: string
  provider?: string
  estimated?: boolean
  status?: string
}

export function combineUsage(summaries: UsageSummary[]): UsageSummary {
  const sum = (key: keyof UsageSummary) =>
    summaries.reduce((n, s) => n + (typeof s[key] === 'number' ? (s[key] as number) : 0), 0)
  const cacheInput = sum('cache_input_tokens')
  const ttftCalls = sum('ttft_calls')
  const generation = sum('generation_seconds')
  return {
    total_tokens: sum('total_tokens'),
    prompt_tokens: sum('prompt_tokens'),
    completion_tokens: sum('completion_tokens'),
    total_calls: sum('total_calls'),
    cache_read_input_tokens: sum('cache_read_input_tokens'),
    cache_creation_input_tokens: sum('cache_creation_input_tokens'),
    reasoning_tokens: sum('reasoning_tokens'),
    cache_input_tokens: cacheInput,
    cache_reported_calls: sum('cache_reported_calls'),
    cache_write_reported_calls: summaries.reduce(
      (n, s) =>
        n +
        (s.cache_write_reported_calls ??
          s.call_details?.filter(c => c.cache_creation_input_tokens != null).length ??
          0),
      0
    ),
    cache_hit_rate: cacheInput ? sum('cache_read_input_tokens') / cacheInput : null,
    ttft_calls: ttftCalls,
    ttft_seconds: ttftCalls
      ? summaries.reduce((n, s) => n + (s.ttft_seconds ?? 0) * (s.ttft_calls ?? 0), 0) / ttftCalls
      : null,
    duration_seconds: sum('duration_seconds'),
    generation_seconds: generation,
    timed_completion_tokens: sum('timed_completion_tokens'),
    tokens_per_second: generation ? sum('timed_completion_tokens') / generation : null,
    estimated_calls: sum('estimated_calls'),
    call_details: summaries.flatMap(s => s.call_details ?? []),
  }
}

/** Results are snapshots; DONE supersedes them. Research bubbles may contain
 * multiple backend turns, each delimited by its own DONE. */
export function messageUsage(events?: StreamEvent[]): UsageSummary | null {
  const turns: UsageSummary[] = []
  let pending: UsageSummary | null = null
  for (const event of events ?? []) {
    const meta = event.metadata as Record<string, unknown> | undefined
    if (event.type === 'result') {
      const payload = meta?.metadata as Record<string, unknown> | undefined
      const value = payload?.usage_summary ?? payload?.cost_summary
      if (value && typeof value === 'object') pending = value as UsageSummary
    }
    if (event.type === 'done') {
      const value = meta?.usage_summary as UsageSummary | undefined
      if (value || pending) turns.push(value || pending!)
      pending = null
    }
  }
  if (pending) turns.push(pending)
  return turns.length ? combineUsage(turns) : null
}

/** Prefix totals on the visible branch, including this reply but never later replies. */
export function cumulativeMessageUsage(
  messages: { role: string; events?: StreamEvent[] }[]
): UsageSummary[] {
  let running: UsageSummary = {}
  return messages.map(message => {
    const usage = message.role === 'assistant' ? messageUsage(message.events) : null
    if (usage) running = { ...combineUsage([running, usage]), call_details: [] }
    return running
  })
}
