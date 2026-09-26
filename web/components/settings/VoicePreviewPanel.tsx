'use client'

import { useEffect, useId, useRef, useState } from 'react'
import { Loader2, Volume2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useSettings } from '@/features/settings/store/SettingsStore'
import { apiFetch, apiUrl } from '@/lib/api'
import { modelTestFingerprint } from '@/lib/model-settings'
import { inputClass, subPanelClass } from './shared'
import { registryButton } from './RegistryControls'

export function VoicePreviewPanel({
  profileId,
  modelId,
  maxChars = 500,
}: {
  profileId: string
  modelId: string
  maxChars?: number
}) {
  const { draft } = useSettings()
  // A different model, voice, language, parameter or credential invalidates the
  // clip and aborts any request, including late completions from old selections.
  return (
    <PreviewRequest
      key={modelTestFingerprint(draft, 'tts', profileId, modelId)}
      maxChars={maxChars}
      profileId={profileId}
      modelId={modelId}
    />
  )
}
function PreviewRequest({
  profileId,
  modelId,
  maxChars,
}: {
  profileId: string
  modelId: string
  maxChars: number
}) {
  const { t, i18n } = useTranslation()
  const { draft } = useSettings()
  const [text, setText] = useState(() =>
    i18n?.language?.startsWith('zh')
      ? '你好，我是你的学习伙伴。让我们一起探索新的知识。'
      : 'Hello, I am your learning companion. Let us explore something new together.'
  )
  const [pending, setPending] = useState(false)
  const [url, setUrl] = useState<string | null>(null)
  const [error, setError] = useState('')
  const controller = useRef<AbortController | null>(null)
  const textId = useId()
  useEffect(() => () => controller.current?.abort(), [])
  useEffect(
    () => () => {
      if (url) URL.revokeObjectURL(url)
    },
    [url]
  )
  const clear = () => {
    controller.current?.abort()
    setPending(false)
    setUrl(null)
    setError('')
  }
  const preview = async () => {
    clear()
    const request = new AbortController()
    controller.current = request
    setPending(true)
    const timeout = setTimeout(() => request.abort(), 65000)
    try {
      const response = await apiFetch(apiUrl('/api/settings/voice/preview'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: request.signal,
        body: JSON.stringify({ catalog: draft, profile_id: profileId, model_id: modelId, text }),
      })
      if (!response.ok) {
        const payload = await response.json()
        throw new Error(
          typeof payload.detail === 'string' ? payload.detail : 'Voice preview failed.'
        )
      }
      const audio = await response.blob()
      if (request.signal.aborted) return
      if (!audio.size || !audio.type.startsWith('audio/'))
        throw new Error('The provider returned no playable audio.')
      setUrl(URL.createObjectURL(audio))
    } catch (err) {
      if (!request.signal.aborted)
        setError(err instanceof Error ? err.message : 'Voice preview failed.')
      else if (controller.current === request) setError('Voice preview was cancelled or timed out.')
    } finally {
      clearTimeout(timeout)
      if (controller.current === request) setPending(false)
    }
  }
  return (
    <section aria-label={t('Voice preview')} className={`space-y-3 p-4 ${subPanelClass}`}>
      <div className="flex items-center justify-between gap-3">
        <h4 className="text-sm font-medium">{t('Voice preview')}</h4>
        <button
          type="button"
          className={registryButton}
          onClick={() => void preview()}
          disabled={pending || !text.trim() || text.length > maxChars}
        >
          {pending ? <Loader2 size={15} className="animate-spin" /> : <Volume2 size={15} />}
          {t(pending ? 'Generating preview…' : 'Preview voice')}
        </button>
      </div>
      <label htmlFor={textId} className="block text-xs font-medium">
        {t('Preview text')}
      </label>
      <textarea
        id={textId}
        className={inputClass}
        value={text}
        rows={3}
        maxLength={maxChars}
        onChange={e => {
          clear()
          controller.current = null
          setText(e.target.value)
        }}
      />
      <p className="text-xs leading-relaxed text-[var(--muted-foreground)]">
        {t(
          "Uses the current form without saving. Choose text in the voice's language. The provider may charge for this synthesis."
        )}
      </p>
      {pending && (
        <button
          type="button"
          className={registryButton}
          onClick={() => {
            clear()
            controller.current = null
          }}
        >
          {t('Cancel')}
        </button>
      )}
      {error && (
        <p role="alert" className="text-xs text-red-600">
          {t(error)}
        </p>
      )}
      {url && (
        <audio
          aria-label={t('Generated voice preview')}
          src={url}
          controls
          autoPlay
          className="w-full"
        />
      )}
    </section>
  )
}
