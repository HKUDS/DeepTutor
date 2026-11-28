/**
 * A marker the assistant can put on its own line to ask for a written answer:
 *
 *     [[answer:q1]]
 *
 * The renderer swaps it for an answer card; the model keeps writing its normal
 * reply and never pauses. The marker carries no text of its own: the question
 * is the prose immediately above it.
 */
const MARKER_RE = /^[ \t]*\[\[answer:([A-Za-z0-9_-]+)\]\][ \t]*$/gm

export type AnswerMarkerPart = { type: 'text'; content: string } | { type: 'answer'; id: string }

export function hasAnswerMarker(content: string): boolean {
  return new RegExp(MARKER_RE.source, MARKER_RE.flags).test(content)
}

export function splitAnswerMarkers(content: string): AnswerMarkerPart[] {
  const parts: AnswerMarkerPart[] = []
  let cursor = 0
  for (const match of content.matchAll(MARKER_RE)) {
    const start = match.index ?? 0
    if (start > cursor) {
      parts.push({ type: 'text', content: content.slice(cursor, start) })
    }
    parts.push({ type: 'answer', id: match[1] })
    cursor = start + match[0].length
  }
  if (cursor < content.length) {
    parts.push({ type: 'text', content: content.slice(cursor) })
  }
  return parts.length ? parts : [{ type: 'text', content }]
}
