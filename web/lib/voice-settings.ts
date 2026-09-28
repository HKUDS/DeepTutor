import type { VoiceOptions, VoiceModelOption } from './model-catalog-types'

export function voiceModelOptions(
  options: VoiceOptions | undefined,
  model: string
): VoiceModelOption | undefined {
  return (
    options?.models
      .slice()
      .sort((a, b) => b.id.length - a.id.length)
      .find(item => item.id === model || model.startsWith(`${item.id}-`)) ?? options?.fallback
  )
}
