'use client'

import { useEffect, useRef, useState } from 'react'
import { FlaskConical, Loader2, Square } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import {
  useSettings,
  type CatalogModel,
  type CatalogProfile,
} from '@/features/settings/store/SettingsStore'
import { apiFetch, apiUrl } from '@/lib/api'
import { modelTestFingerprint } from '@/lib/model-settings'
import { inputClass, subPanelClass } from './shared'
import { registryButton, registryPrimary } from './RegistryControls'

type Service = 'search' | 'stt' | 'imagegen' | 'videogen'
type Result = {
  kind: 'search' | 'transcript' | 'image' | 'video'
  text?: string
  results?: { title: string; url: string; snippet: string }[]
  url?: string
}
type Props = { service: Service; profile: CatalogProfile; model?: CatalogModel | null }
const audioTypes: Record<string, string> = {
  wav: 'audio/wav',
  mp3: 'audio/mpeg',
  m4a: 'audio/mp4',
  webm: 'audio/webm',
  ogg: 'audio/ogg',
  flac: 'audio/flac',
}
function safeLink(value: string) {
  try {
    const u = new URL(value)
    return ['https:', 'http:'].includes(u.protocol) ? u.href : undefined
  } catch {
    return undefined
  }
}

/** Replacing the edited connection/model aborts its request and releases media. */
export function ServicePreviewPanel(props: Props) {
  const { draft } = useSettings()
  return (
    <Preview
      key={modelTestFingerprint(draft, props.service, props.profile.id, props.model?.id)}
      {...props}
    />
  )
}

function Preview({ service, profile, model }: Props) {
  const { t } = useTranslation()
  const { draft } = useSettings()
  const [text, setText] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [audioUrl, setAudioUrl] = useState('')
  const [result, setResult] = useState<Result | null>(null)
  const [state, setState] = useState('idle')
  const [phase, setPhase] = useState('requesting')
  const request = useRef<AbortController | null>(null)
  const mediaUrl = useRef('')
  const running = state === 'running'
  useEffect(
    () => () => {
      request.current?.abort()
      if (mediaUrl.current) URL.revokeObjectURL(mediaUrl.current)
    },
    []
  )
  useEffect(() => {
    if (!file) {
      setAudioUrl('')
      return
    }
    const url = URL.createObjectURL(file)
    setAudioUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [file])
  function clearResult() {
    setResult(null)
    setState('idle')
    if (mediaUrl.current) URL.revokeObjectURL(mediaUrl.current)
    mediaUrl.current = ''
  }
  async function run() {
    clearResult()
    const controller = new AbortController()
    request.current = controller
    setState('running')
    setPhase('requesting')
    const timeout = setTimeout(
      () => {
        controller.abort()
        setState('timeout')
      },
      service === 'videogen' ? 610000 : 130000
    )
    try {
      let audio = ''
      let contentType = ''
      if (service === 'stt' && file) {
        contentType = audioTypes[file.name.split('.').pop()?.toLowerCase() || ''] || file.type
        audio = await new Promise<string>((resolve, reject) => {
          const reader = new FileReader()
          reader.onload = () => resolve(String(reader.result).split(',')[1])
          reader.onerror = () => reject(new Error('audio'))
          reader.readAsDataURL(file)
        })
      }
      if (controller.signal.aborted) return
      const response = await apiFetch(apiUrl(`/api/settings/services/${service}/preview`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: controller.signal,
        body: JSON.stringify({
          catalog: draft,
          profile_id: profile.id,
          model_id: model?.id,
          text: text.trim(),
          audio,
          content_type: contentType,
        }),
      })
      if (!response.ok || !response.body) throw new Error('request')
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let completed = false
      try {
        while (!completed) {
          const chunk = await reader.read()
          buffer += decoder.decode(chunk.value, { stream: !chunk.done })
          if (buffer.length > 60 * 1024 * 1024) throw new Error('size')
          let newline: number
          while ((newline = buffer.indexOf('\n')) !== -1) {
            const line = buffer.slice(0, newline)
            buffer = buffer.slice(newline + 1)
            if (!line.trim()) continue
            const event = JSON.parse(line)
            if (controller.signal.aborted) return
            if (event.type === 'progress')
              setPhase(event.phase === 'rendering' ? 'rendering' : 'requesting')
            if (event.type === 'error') {
              setState(event.code === 'timeout' ? 'timeout' : 'failed')
              completed = true
            }
            if (event.type === 'result') {
              const next: Result = { kind: event.kind, text: event.text, results: event.results }
              if (event.kind === 'image' || event.kind === 'video') {
                const raw = atob(event.data)
                const bytes = Uint8Array.from(raw, char => char.charCodeAt(0))
                mediaUrl.current = URL.createObjectURL(
                  new Blob([bytes], { type: event.content_type })
                )
                next.url = mediaUrl.current
              }
              setResult(next)
              setState('success')
              completed = true
            }
          }
          if (chunk.done) {
            if (!completed) throw new Error('incomplete')
            break
          }
        }
      } finally {
        await reader.cancel().catch(() => {})
        reader.releaseLock()
      }
    } catch {
      if (!controller.signal.aborted) setState('failed')
    } finally {
      clearTimeout(timeout)
      if (request.current === controller) request.current = null
    }
  }
  const empty =
    result &&
    (result.kind === 'search'
      ? !result.text && !result.results?.length
      : result.kind === 'transcript' && !result.text?.trim())
  const message =
    state === 'success' ? (empty ? 'empty' : 'success') : state === 'running' ? phase : state
  return (
    <section
      aria-label={t(`settings.servicePreview.title.${service}`)}
      className={`space-y-4 p-4 ${subPanelClass}`}
    >
      <div>
        <h4 className="text-sm font-medium">{t(`settings.servicePreview.title.${service}`)}</h4>
        <p className="mt-1 text-xs leading-relaxed text-[var(--muted-foreground)]">
          {t(`settings.servicePreview.description.${service}`)}
        </p>
      </div>
      {service === 'stt' ? (
        <div className="space-y-3">
          <label className="block space-y-2 text-xs font-medium">
            <span>{t('settings.servicePreview.audio')}</span>
            <input
              type="file"
              accept=".wav,.mp3,.m4a,.webm,.ogg,.flac,audio/*"
              disabled={running}
              className={`${inputClass} file:mr-3 file:rounded-md file:border-0 file:px-3 file:py-1.5 file:text-xs`}
              onChange={e => {
                clearResult()
                const next = e.target.files?.[0] || null
                if (
                  next &&
                  (!next.size ||
                    next.size > 8 * 1024 * 1024 ||
                    !audioTypes[next.name.split('.').pop()?.toLowerCase() || ''])
                ) {
                  setFile(null)
                  setState('invalidAudio')
                  e.target.value = ''
                  return
                }
                setFile(next)
              }}
            />
          </label>
          {audioUrl && (
            <audio
              controls
              src={audioUrl}
              className="h-10 w-full"
              aria-label={t('settings.servicePreview.audio')}
            />
          )}
        </div>
      ) : (
        <label className="block space-y-2 text-xs font-medium">
          <span>
            {t(
              service === 'search'
                ? 'settings.servicePreview.query'
                : 'settings.servicePreview.prompt'
            )}
          </span>
          <textarea
            className={inputClass}
            rows={2}
            maxLength={2000}
            value={text}
            disabled={running}
            placeholder={t(`settings.servicePreview.placeholder.${service}`)}
            onChange={e => {
              clearResult()
              setText(e.target.value)
            }}
          />
        </label>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          className={registryPrimary}
          disabled={
            running ||
            (service === 'stt' ? !file : !text.trim()) ||
            (service !== 'search' && !model?.model.trim())
          }
          onClick={() => void run()}
        >
          {running ? <Loader2 size={14} className="animate-spin" /> : <FlaskConical size={14} />}
          {t(`settings.servicePreview.action.${service}`)}
        </button>
        {running && (
          <button
            type="button"
            className={registryButton}
            onClick={() => {
              request.current?.abort()
              setState('cancelled')
            }}
          >
            <Square size={12} />
            {t('Cancel')}
          </button>
        )}
      </div>
      {state !== 'idle' && (
        <p
          role="status"
          aria-live="polite"
          className={`text-xs leading-relaxed ${['failed', 'timeout', 'invalidAudio'].includes(state) ? 'text-red-600 dark:text-red-400' : 'text-[var(--muted-foreground)]'}`}
        >
          {t(`settings.servicePreview.status.${message}`)}
        </p>
      )}
      {(running || state === 'cancelled' || state === 'timeout') && service === 'videogen' && (
        <p className="text-xs text-[var(--muted-foreground)]">
          {t('settings.servicePreview.remoteTask')}
        </p>
      )}
      {result && !empty && (
        <div className="space-y-3 rounded-lg bg-[var(--background)] p-3">
          {result.text && (
            <p className="whitespace-pre-wrap break-words text-sm leading-relaxed">{result.text}</p>
          )}
          {result.results?.map((row, index) => (
            <div key={index} className="space-y-1 text-xs">
              {safeLink(row.url) ? (
                <a
                  href={safeLink(row.url)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="break-words font-medium underline underline-offset-4"
                >
                  {row.title || row.url}
                </a>
              ) : (
                <p className="font-medium">{row.title}</p>
              )}
              <p className="break-words leading-relaxed text-[var(--muted-foreground)]">
                {row.snippet}
              </p>
            </div>
          ))}
          {/* Provider-generated images are temporary blob URLs, never optimized. */}
          {result.kind === 'image' && result.url && (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={result.url}
              alt={text}
              className="max-h-96 w-full rounded-lg object-contain"
            />
          )}
          {result.kind === 'video' && result.url && (
            <video
              controls
              preload="metadata"
              src={result.url}
              aria-label={text}
              className="max-h-96 w-full rounded-lg"
            />
          )}
          {result.url && (
            <a
              href={result.url}
              download={result.kind === 'image' ? 'deeptutor-preview' : 'deeptutor-preview-video'}
              className="inline-block text-xs underline underline-offset-4"
            >
              {t('Download')}
            </a>
          )}
        </div>
      )}
    </section>
  )
}
