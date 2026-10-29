/**
 * What a learning block shows while Dito fills it.
 *
 * The page decides (it knows which conversation is generating which block);
 * the block only reads. A store rather than DOM events because blocks render
 * lazily: one that mounts after a generation started must still see it.
 */
export interface GenerationPreview {
  content: string
  pending: boolean
  error?: string
  /** The conversation filling the block, so the block can open it. */
  sessionId?: string
}

const previews = new Map<string, GenerationPreview>()
const listeners = new Set<() => void>()

export function setGenerationPreview(blockId: string, preview: GenerationPreview | null) {
  const current = previews.get(blockId)
  if (!preview) {
    if (!current) return
    previews.delete(blockId)
  } else {
    if (
      current &&
      current.content === preview.content &&
      current.pending === preview.pending &&
      current.error === preview.error &&
      current.sessionId === preview.sessionId
    )
      return
    previews.set(blockId, preview)
  }
  listeners.forEach(listener => listener())
}

export function generationPreview(blockId: string): GenerationPreview | null {
  return previews.get(blockId) ?? null
}

export function subscribeGenerationPreviews(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}
