export type SearchableTranscriptCue = { text: string }

/** Return source cue indexes so filtered rows retain stable identity. */
export function transcriptMatchIndexes(
  cues: readonly SearchableTranscriptCue[],
  query: string
): number[] {
  const needle = query.trim().toLocaleLowerCase()
  if (!needle) return []
  const matches: number[] = []
  cues.forEach((cue, index) => {
    if (cue.text.toLocaleLowerCase().includes(needle)) matches.push(index)
  })
  return matches
}

/** Move through a filtered match list, wrapping at either end. */
export function stepTranscriptMatch(
  current: number,
  matchCount: number,
  direction: 1 | -1
): number {
  if (matchCount <= 0) return -1
  if (current < 0 || current >= matchCount) {
    return direction === 1 ? 0 : matchCount - 1
  }
  return (current + direction + matchCount) % matchCount
}
