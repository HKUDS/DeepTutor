import type { NoteSuggestion } from '@/lib/notes-api'
import type { OutlineItem } from '@/lib/research-types'
export function researchOutline(
  suggestion: NoteSuggestion
): { topic: string; sub_topics: OutlineItem[]; research_config: Record<string, unknown> } | null {
  try {
    const data = JSON.parse(String(suggestion.blocks?.[0]?.props.data || '{}'))
    return data.outline_preview && Array.isArray(data.sub_topics) && data.sub_topics.length
      ? data
      : null
  } catch {
    return null
  }
}
export function noteGenerationConfig(mode: string, config?: Record<string, unknown>) {
  return mode === 'deep_research' ? { mode: 'notes', depth: 'quick', ...config } : config
}
