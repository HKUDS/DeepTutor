import type { NoteBlock } from '@/lib/notes-api'

export function resultLearningBlock(
  result: Record<string, unknown>,
  response = ''
): NoteBlock | undefined {
  let kind = ''
  let payload = result
  const summary = result.summary as
    { results?: { qa_pair?: Record<string, unknown> }[] } | undefined
  if (result.outline_preview && Array.isArray(result.sub_topics)) kind = 'research'
  else if (Array.isArray(summary?.results)) {
    kind = 'quiz'
    payload = { questions: summary.results.flatMap(row => (row.qa_pair ? [row.qa_pair] : [])) }
  } else if (result.renderer && result.payload) kind = 'visualization'
  else if (Array.isArray(result.artifacts) && result.artifacts.length) kind = 'animation'
  else if (Array.isArray(result.workspace_items) && result.workspace_items.length) kind = 'media'
  if (!kind) return undefined
  const questions = payload.questions as { question?: string; explanation?: string }[] | undefined
  const markdown = questions
    ? questions
        .map((q, i) => `${i + 1}. ${q.question || ''}\n\n${q.explanation || ''}`)
        .join('\n\n')
    : response || String(result.response || '')
  return {
    id: crypto.randomUUID(),
    type: 'learning',
    props: { kind, prompt: '', markdown, data: JSON.stringify(payload), sourceUrl: '' },
    children: [],
  }
}
