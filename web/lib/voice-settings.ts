import type { CatalogModel, VoiceOptions, VoiceModelOption } from './model-catalog-types'

export const DEFAULT_SPEECH_REQUEST_TIMEOUT = 60
export const MIN_SPEECH_REQUEST_TIMEOUT = 5
export const MAX_SPEECH_REQUEST_TIMEOUT = 600
export const SPEECH_TIMEOUT_MESSAGE =
  'Speech synthesis timed out. Increase Request timeout (seconds) in the speech model settings or try shorter text.'
export const SPEECH_PLAYBACK_FAILURE_MESSAGE =
  'Speech playback failed. Check the speech model settings and provider connection.'

export function speechRequestTimeout(model: CatalogModel | undefined): number {
  const seconds = Number(model?.request_timeout)
  return Number.isInteger(seconds) && seconds >= MIN_SPEECH_REQUEST_TIMEOUT && seconds <= MAX_SPEECH_REQUEST_TIMEOUT
    ? seconds
    : DEFAULT_SPEECH_REQUEST_TIMEOUT
}

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
