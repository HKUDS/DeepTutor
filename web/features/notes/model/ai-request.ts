export interface NoteAIRequest {
  id: number
  prompt: string
  knowledgeRef?: string
  mode?: string
  blockId?: string
  instructions?: string
  autoSend?: boolean
  config?: Record<string, unknown>
}

/** Context is sent to the model, but stays out of restored chat bubbles. */
export function visibleNotePrompt(content: string): string {
  return content
    .split(
      /\n(?:\n)?(?:<note-generation-context>|<notebook-source>|Learning block kind:|Use note_read then note_suggest|Target block:)/
    )[0]
    .trim()
}
export function learningMode(kind: string): string {
  return (
    (
      {
        research: 'deep_research',
        quiz: 'deep_question',
        animation: 'visualize',
        audio: 'audio_overview',
      } as Record<string, string>
    )[kind] || 'chat'
  )
}

/** Keep animation blocks explicit even when their prompt only names a topic. */
export function learningConfig(
  kind: string,
  config?: Record<string, unknown>
): Record<string, unknown> | undefined {
  if (kind !== 'animation') return config
  const { output_mode, ...rest } = config || {}
  return {
    ...rest,
    render_mode: rest.render_mode || (output_mode === 'image' ? 'manim_image' : 'manim_video'),
  }
}
