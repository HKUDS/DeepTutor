'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { Loader2, Play, Square, Volume2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import Tooltip from '@/shared/ui/Tooltip'
import { apiFetch, apiUrl } from '@/lib/api'
import { notify } from '@/lib/notifications'
import { useVoiceAutoplay } from '@/hooks/useVoiceAutoplay'
import { SPEECH_PLAYBACK_FAILURE_MESSAGE, SPEECH_TIMEOUT_MESSAGE } from '@/lib/voice-settings'

// Speaker button: synthesizes this one reply and plays it. Auto-play of later
// replies is a Settings preference (`autoPlayFresh`), not a first-click prompt.
let activePlayback: { owner: object; stop: () => void } | null = null
// 50 ms of playable unsigned 8-bit PCM silence; an empty WAV cannot unlock playback.
const SILENT_UNLOCK_WAV =
  'data:audio/wav;base64,UklGRrQBAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YZABAACAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'

async function ttsErrorMessage(resp: Response): Promise<string> {
  try {
    const body = (await resp.json()) as { detail?: unknown }
    if (typeof body.detail === 'string' && body.detail.trim()) return body.detail
    if (Array.isArray(body.detail)) {
      const first = body.detail[0] as { msg?: string } | undefined
      if (typeof first?.msg === 'string' && first.msg.trim()) return first.msg
    }
  } catch {
    /* non-JSON error body */
  }
  return ''
}

type SpeechFrame =
  | { audio: string; content_type: string; final: boolean }
  | { detail: string }

async function* readSpeechFrames(response: Response): AsyncGenerator<SpeechFrame> {
  if (!response.body) throw new Error('Missing speech stream.')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let pending = ''
  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) throw new Error('Incomplete speech stream.')
      pending += decoder.decode(value, { stream: true })
      for (let newline = pending.indexOf('\n'); newline !== -1; newline = pending.indexOf('\n')) {
        const frame = JSON.parse(pending.slice(0, newline)) as SpeechFrame
        pending = pending.slice(newline + 1)
        yield frame
        if ('detail' in frame || frame.final) return
      }
    }
  } finally {
    await reader.cancel().catch(() => {})
    reader.releaseLock()
  }
}

export function PlayAudioButton({
  content,
  conversationKey,
  autoPlayFresh,
  selection = false,
  playbackRate = 1,
  className,
}: {
  content: string
  conversationKey?: string
  autoPlayFresh: boolean
  playbackRate?: number
  selection?: boolean
  className?: string
}) {
  const { t } = useTranslation()
  const { autoplayEnabled } = useVoiceAutoplay(conversationKey)
  const [state, setState] = useState<'idle' | 'loading' | 'playing'>('idle')
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const rateRef = useRef(playbackRate)
  useEffect(() => {
    rateRef.current = playbackRate
    if (audioRef.current) audioRef.current.playbackRate = playbackRate
  }, [playbackRate])
  const urlRef = useRef<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const genRef = useRef(0)
  const autoPlayedRef = useRef(false)
  const playbackOwnerRef = useRef<object>({})

  const cleanup = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current = null
    }
    if (urlRef.current) {
      URL.revokeObjectURL(urlRef.current)
      urlRef.current = null
    }
  }, [])

  const stop = useCallback(() => {
    genRef.current += 1
    cleanup()
    setState('idle')
    if (activePlayback?.owner === playbackOwnerRef.current) activePlayback = null
  }, [cleanup])

  const play = useCallback(async () => {
    activePlayback?.stop()
    const gen = ++genRef.current
    abortRef.current?.abort()
    const ac = new AbortController()
    abortRef.current = ac
    activePlayback = { owner: playbackOwnerRef.current, stop }
    setState('loading')

    // WebKit evaluates media playback eligibility when play() is called. Keep
    // this element unlocked in the click task, then replace its source after
    // synthesis completes rather than constructing a new audio element then.
    const audio = new Audio(SILENT_UNLOCK_WAV)
    audioRef.current = audio
    void Promise.resolve(audio.play()).catch(() => {
      /* Unlocking playback can fail on clients that already permit it. */
    })

    try {
      // Let the active provider apply the user's configured voice, format and
      // language. Provider-specific voice IDs are not portable across services.
      const resp = await apiFetch(apiUrl('/api/voice/tts'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: content, ...(!selection ? { stream: true } : {}) }),
        signal: ac.signal,
      })
      if (gen !== genRef.current) return
      if (!resp.ok) {
        const detail = await ttsErrorMessage(resp)
        if (gen !== genRef.current) return
        notify(
          t(
            detail ||
              (resp.status === 504 ? SPEECH_TIMEOUT_MESSAGE : SPEECH_PLAYBACK_FAILURE_MESSAGE)
          ),
          { tone: 'error' }
        )
        stop()
        return
      }
      const playClip = async (blob: Blob) => {
        if (!blob.size) throw new Error('Speech returned empty audio')
        if (gen !== genRef.current) return
        if (urlRef.current) URL.revokeObjectURL(urlRef.current)
        const url = URL.createObjectURL(blob)
        urlRef.current = url
        audio.src = url
        audio.load()
        audio.playbackRate = rateRef.current
        const finished = new Promise<void>(resolve => {
          const finish = () => {
            ac.signal.removeEventListener('abort', finish)
            audio.onended = null
            audio.onerror = null
            resolve()
          }
          audio.onended = finish
          audio.onerror = () => {
            if (gen === genRef.current) {
              notify(t(SPEECH_PLAYBACK_FAILURE_MESSAGE), { tone: 'error' })
              stop()
            }
            finish()
          }
          ac.signal.addEventListener('abort', finish, { once: true })
        })
        await audio.play()
        if (gen !== genRef.current) {
          audio.pause()
          return
        }
        setState('playing')
        await finished
      }

      if (!selection && resp.headers.get('content-type') === 'application/x-ndjson') {
        for await (const frame of readSpeechFrames(resp)) {
          if (gen !== genRef.current) return
          if ('detail' in frame) {
            notify(t(frame.detail || SPEECH_PLAYBACK_FAILURE_MESSAGE), { tone: 'error' })
            break
          }
          const bytes = Uint8Array.from(atob(frame.audio), char => char.charCodeAt(0))
          await playClip(new Blob([bytes], { type: frame.content_type }))
        }
      } else {
        await playClip(await resp.blob())
      }
      if (gen === genRef.current) stop()
    } catch (err) {
      if (gen !== genRef.current) return
      if (err instanceof Error && err.name === 'AbortError') return
      notify(t(SPEECH_PLAYBACK_FAILURE_MESSAGE), {
        tone: 'error',
      })
      stop()
    }
  }, [content, selection, stop, t])

  const handleClick = useCallback(() => {
    if (state === 'playing' || state === 'loading') {
      stop()
      return
    }
    void play()
  }, [play, state, stop])

  // Auto-play a freshly-generated reply when Settings auto-play is on.
  useEffect(() => {
    if (!autoPlayFresh || !autoplayEnabled) return
    if (autoPlayedRef.current) return
    if (!content.trim()) return
    autoPlayedRef.current = true
    const id = window.setTimeout(() => void play(), 0)
    return () => window.clearTimeout(id)
  }, [autoPlayFresh, autoplayEnabled, content, play])

  useEffect(
    () => () => {
      genRef.current += 1
      cleanup()
      if (activePlayback?.owner === playbackOwnerRef.current) activePlayback = null
    },
    [cleanup]
  )

  return (
    <div className={`relative inline-flex ${selection ? 'h-full' : ''}`}>
      <Tooltip
        label={state !== 'idle' ? t('Stop') : t(selection ? 'Read aloud' : 'Play aloud')}
        side="top"
      >
        <button
          type="button"
          onClick={handleClick}
          aria-label={state !== 'idle' ? t('Stop') : t(selection ? 'Read aloud' : 'Play aloud')}
          aria-busy={state === 'loading'}
          className={
            className ??
            `inline-flex items-center justify-center rounded-md p-1 transition-colors ${
              state === 'playing'
                ? 'text-[var(--primary)]'
                : 'text-[var(--muted-foreground)] hover:bg-[var(--muted)]/50 hover:text-[var(--foreground)]'
            }`
          }
        >
          {state === 'loading' ? (
            <Loader2 size={15} strokeWidth={1.8} className="animate-spin" />
          ) : state === 'playing' ? (
            <Square size={13} strokeWidth={1.8} className="fill-current" />
          ) : selection ? (
            <Play size={15} strokeWidth={1.8} className="fill-current" />
          ) : (
            <Volume2 size={15} strokeWidth={1.5} />
          )}
        </button>
      </Tooltip>
    </div>
  )
}
