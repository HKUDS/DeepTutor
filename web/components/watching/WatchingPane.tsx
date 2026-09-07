'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  ChevronsDown,
  Check,
  Captions,
  Copy,
  ExternalLink,
  Loader2,
  Pencil,
  Play,
  RotateCcw,
  Search,
  StickyNote,
  Trash2,
  X,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { useWatching } from '@/context/WatchingContext'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import {
  DEFAULT_PLAYBACK_RATE,
  WATCHING_PLAYBACK_RATES,
  type PlayerController,
} from '@/lib/video-player-controller'
import {
  createVideoNote,
  deleteVideoNote,
  exportVideoNotes,
  listVideoNotes,
  saveVideoProgress,
  updateVideoNote,
  type VideoNote,
} from '@/lib/video-learning-api'
import { stepTranscriptMatch, transcriptMatchIndexes } from '@/lib/transcript-search'
import { videoTimeFromHref } from '@/lib/watching-citations'
import { WatchingPlayer } from './WatchingPlayer'

export const WATCHING_ASK_EVENT = 'dt:watching-ask'

type WatchTab = 'transcript' | 'notes'

export function WatchingPane({ onClose }: { onClose(): void }) {
  const { t } = useTranslation()
  const {
    material,
    loading,
    error,
    lastUrl,
    openUrl,
    refresh,
    refreshTranscript,
    close,
    reportTime,
    clearError,
    setActive,
  } = useWatching()
  const materialId = material?.material_id ?? null
  const [input, setInput] = useState('')
  const [playerError, setPlayerError] = useState<string | null>(null)
  const [tab, setTab] = useState<WatchTab>('transcript')
  const [time, setTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [notes, setNotes] = useState<VideoNote[]>([])
  const [notesLoading, setNotesLoading] = useState(false)
  const [notesError, setNotesError] = useState<string | null>(null)
  const [noteDraft, setNoteDraft] = useState('')
  const [editingNoteId, setEditingNoteId] = useState<string | null>(null)
  const [editingDraft, setEditingDraft] = useState('')
  const [noteBusy, setNoteBusy] = useState(false)
  const [notesExportBusy, setNotesExportBusy] = useState(false)
  const [notesCopied, setNotesCopied] = useState(false)
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null)
  const notesExportRequestRef = useRef(0)
  const [followTranscript, setFollowTranscript] = useState(true)
  const [transcriptQuery, setTranscriptQuery] = useState('')
  const [selectedTranscriptMatch, setSelectedTranscriptMatch] = useState(-1)
  const [playbackRate, setPlaybackRate] = useState(DEFAULT_PLAYBACK_RATE)
  const [controllerReady, setControllerReady] = useState(false)
  const controllerRef = useRef<PlayerController | null>(null)
  const playbackRateRef = useRef(DEFAULT_PLAYBACK_RATE)
  const transcriptListRef = useRef<HTMLDivElement | null>(null)
  const activeMaterialIdRef = useRef(materialId)
  const lastSavedRef = useRef(0)
  const stateRef = useRef({ time: 0, duration: 0 })
  activeMaterialIdRef.current = materialId

  useEffect(() => {
    setActive(true)
    return () => setActive(false)
  }, [setActive])

  const persist = useCallback(() => {
    if (!material) return
    const current = stateRef.current
    if (current.time <= 0) return
    void saveVideoProgress(material.material_id, current.time, current.duration).catch(
      () => undefined
    )
    lastSavedRef.current = current.time
  }, [material])

  const handleTime = useCallback(
    (nextTime: number, nextDuration: number) => {
      stateRef.current = { time: nextTime, duration: nextDuration }
      setTime(nextTime)
      setDuration(nextDuration)
      reportTime(nextTime)
      if (Math.abs(nextTime - lastSavedRef.current) >= 5) persist()
    },
    [persist, reportTime]
  )

  useEffect(() => {
    const onVisibility = () => {
      if (document.visibilityState === 'hidden') persist()
    }
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      document.removeEventListener('visibilitychange', onVisibility)
      persist()
    }
  }, [persist])

  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey)
        return
      const anchor = (event.target as HTMLElement | null)?.closest?.(
        'a[href]'
      ) as HTMLAnchorElement | null
      const seconds = videoTimeFromHref(anchor?.getAttribute('href'))
      if (seconds === null) return
      event.preventDefault()
      controllerRef.current?.seek(seconds)
    }
    document.addEventListener('click', onClick)
    return () => document.removeEventListener('click', onClick)
  }, [])

  const cue = useMemo(
    () => material?.transcript.cues.find(row => time >= row.start && time <= row.end),
    [material, time]
  )
  const normalizedTranscriptQuery = transcriptQuery.trim()
  const transcriptMatches = useMemo(
    () => transcriptMatchIndexes(material?.transcript.cues ?? [], normalizedTranscriptQuery),
    [material, normalizedTranscriptQuery]
  )

  useEffect(() => {
    setFollowTranscript(true)
    setTranscriptQuery('')
    setSelectedTranscriptMatch(-1)
  }, [materialId])

  useEffect(() => {
    if (!normalizedTranscriptQuery || transcriptMatches.length === 0) {
      setSelectedTranscriptMatch(-1)
      return
    }
    setSelectedTranscriptMatch(current =>
      current >= 0 && current < transcriptMatches.length ? current : -1
    )
  }, [normalizedTranscriptQuery, transcriptMatches.length])

  useEffect(() => {
    playbackRateRef.current = DEFAULT_PLAYBACK_RATE
    setPlaybackRate(DEFAULT_PLAYBACK_RATE)
    controllerRef.current?.setPlaybackRate(DEFAULT_PLAYBACK_RATE)
  }, [materialId])

  useEffect(() => {
    if (!followTranscript || tab !== 'transcript' || !cue) return
    const list = transcriptListRef.current
    const activeRow = list?.querySelector<HTMLButtonElement>('[data-active-cue="true"]')
    if (!list || !activeRow) return
    const rowTop =
      activeRow.getBoundingClientRect().top -
      list.getBoundingClientRect().top +
      list.scrollTop -
      list.clientHeight / 2 +
      activeRow.clientHeight / 2
    list.scrollTo({ top: Math.max(0, rowTop), behavior: 'smooth' })
  }, [cue, followTranscript, tab])

  const submit = async (providerOverride?: 'youtube') => {
    const url = (providerOverride ? lastUrl || input : input).trim()
    if (!url) return
    setPlayerError(null)
    try {
      await openUrl(url, '', providerOverride)
    } catch {
      // The context owns the user-facing error.
    }
  }

  const askHere = () => {
    if (!material || !cue) return
    window.dispatchEvent(
      new CustomEvent(WATCHING_ASK_EVENT, {
        detail: { timeSeconds: time, text: cue.text },
      })
    )
  }

  useEffect(() => {
    let cancelled = false
    setNotes([])
    setNotesError(null)
    setNoteDraft('')
    setEditingNoteId(null)
    setEditingDraft('')
    setPendingDeleteId(null)
    notesExportRequestRef.current += 1
    setNotesExportBusy(false)
    setNotesCopied(false)
    if (!materialId) {
      setNotesLoading(false)
      return () => {
        cancelled = true
      }
    }
    setNotesLoading(true)
    void (async () => {
      try {
        const loaded = await listVideoNotes(materialId)
        if (!cancelled) setNotes(loaded)
      } catch (caught) {
        if (!cancelled) {
          setNotesError(caught instanceof Error ? caught.message : t('Notes could not be loaded.'))
        }
      } finally {
        if (!cancelled) setNotesLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [materialId, t])

  const sortNotes = (rows: VideoNote[]) =>
    [...rows].sort(
      (left, right) =>
        left.time_seconds - right.time_seconds ||
        left.created_at - right.created_at ||
        left.note_id.localeCompare(right.note_id)
    )

  const addNote = async () => {
    if (!material || !noteDraft.trim() || noteBusy) return
    const requestedMaterialId = material.material_id
    setNoteBusy(true)
    setNotesError(null)
    try {
      const saved = await createVideoNote(requestedMaterialId, noteDraft.trim(), time)
      if (activeMaterialIdRef.current !== requestedMaterialId) return
      setNotes(current => sortNotes([...current, saved]))
      setNoteDraft('')
      setNotesCopied(false)
    } catch (caught) {
      if (activeMaterialIdRef.current !== requestedMaterialId) return
      setNotesError(caught instanceof Error ? caught.message : t('Note was not saved.'))
    } finally {
      setNoteBusy(false)
    }
  }

  const saveEditedNote = async () => {
    if (!material || !editingNoteId || !editingDraft.trim() || noteBusy) return
    const requestedMaterialId = material.material_id
    setNoteBusy(true)
    setNotesError(null)
    try {
      const saved = await updateVideoNote(requestedMaterialId, editingNoteId, editingDraft.trim())
      if (activeMaterialIdRef.current !== requestedMaterialId) return
      setNotes(current =>
        sortNotes(current.map(note => (note.note_id === saved.note_id ? saved : note)))
      )
      setEditingNoteId(null)
      setEditingDraft('')
      setNotesCopied(false)
    } catch (caught) {
      if (activeMaterialIdRef.current !== requestedMaterialId) return
      setNotesError(caught instanceof Error ? caught.message : t('Note was not saved.'))
    } finally {
      setNoteBusy(false)
    }
  }

  const confirmDelete = async () => {
    if (!material || !pendingDeleteId || noteBusy) return
    const requestedMaterialId = material.material_id
    setNoteBusy(true)
    setNotesError(null)
    try {
      await deleteVideoNote(requestedMaterialId, pendingDeleteId)
      if (activeMaterialIdRef.current !== requestedMaterialId) return
      setNotes(current => current.filter(note => note.note_id !== pendingDeleteId))
      if (editingNoteId === pendingDeleteId) {
        setEditingNoteId(null)
        setEditingDraft('')
      }
      setPendingDeleteId(null)
      setNotesCopied(false)
    } catch (caught) {
      if (activeMaterialIdRef.current !== requestedMaterialId) return
      setNotesError(caught instanceof Error ? caught.message : t('Note was not deleted.'))
    } finally {
      setNoteBusy(false)
    }
  }

  const copyNotes = async () => {
    if (!material || !notes.length || notesExportBusy) return
    const requestedMaterialId = material.material_id
    const requestId = ++notesExportRequestRef.current
    setNotesExportBusy(true)
    setNotesCopied(false)
    try {
      const markdown = await exportVideoNotes(requestedMaterialId)
      await navigator.clipboard.writeText(markdown)
      if (notesExportRequestRef.current !== requestId) return
      setNotesCopied(true)
    } catch (caught) {
      if (notesExportRequestRef.current !== requestId) return
      setNotesError(caught instanceof Error ? caught.message : t('Notes could not be copied.'))
    } finally {
      if (notesExportRequestRef.current === requestId) {
        setNotesExportBusy(false)
      }
    }
  }

  const closePane = () => {
    persist()
    close()
    onClose()
  }

  const effectiveError = error || playerError
  const openNativeYouTube = useCallback(async () => {
    if (!material) return
    setPlayerError(null)
    clearError()
    try {
      await openUrl(material.source.url, '', 'youtube')
    } catch {
      // The context owns the user-facing error.
    }
  }, [clearError, material, openUrl])

  const refreshProvider = useCallback(async () => {
    setPlayerError(null)
    await refresh()
  }, [refresh])

  const retryTranscript = useCallback(async () => {
    setPlayerError(null)
    await refreshTranscript()
  }, [refreshTranscript])

  const handleController = useCallback((controller: PlayerController | null) => {
    controllerRef.current = controller
    setControllerReady(Boolean(controller))
    controller?.setPlaybackRate(playbackRateRef.current)
  }, [])

  const selectPlaybackRate = useCallback((rate: number) => {
    playbackRateRef.current = rate
    setPlaybackRate(rate)
    controllerRef.current?.setPlaybackRate(rate)
  }, [])

  const moveTranscriptMatch = useCallback(
    (direction: 1 | -1) => {
      if (!material || transcriptMatches.length === 0) return
      const next = stepTranscriptMatch(selectedTranscriptMatch, transcriptMatches.length, direction)
      const cueIndex = transcriptMatches[next]
      const match = material.transcript.cues[cueIndex]
      if (!match) return
      setFollowTranscript(false)
      setSelectedTranscriptMatch(next)
      controllerRef.current?.seek(match.start)
      window.requestAnimationFrame(() => {
        transcriptListRef.current
          ?.querySelector<HTMLElement>(`[data-transcript-cue="${cueIndex}"]`)
          ?.scrollIntoView({ block: 'center' })
      })
    },
    [material, selectedTranscriptMatch, transcriptMatches]
  )
  return (
    <section className="flex h-full min-w-0 flex-col border-r border-[var(--border)] bg-[var(--background)]">
      <header className="flex items-center gap-2 border-b border-[var(--border)] px-4 py-3">
        <div className="min-w-0 flex-1">
          <h2 className="truncate font-semibold">{t('Immersive Watching')}</h2>
          <p className="truncate text-xs text-[var(--muted-foreground)]">
            {material?.metadata.title || t('Native YouTube learning')}
          </p>
        </div>
        <button
          type="button"
          onClick={() => void refreshProvider()}
          disabled={!material || loading}
          className="rounded-md p-2 hover:bg-[var(--muted)]"
          aria-label={t('Refresh provider')}
        >
          <RotateCcw className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={closePane}
          className="rounded-md p-2 hover:bg-[var(--muted)]"
          aria-label={t('Close video learning')}
        >
          <X className="h-4 w-4" />
        </button>
      </header>

      {!material && (
        <div className="flex flex-1 flex-col items-center justify-center gap-4 p-8 text-center">
          <Play className="h-10 w-10 text-red-500" />
          <div>
            <h3 className="font-medium">{t('Open a YouTube learning video')}</h3>
            <p className="mt-1 text-sm text-[var(--muted-foreground)]">
              {t('Paste a watch, Shorts, Live, Embed, or youtu.be link.')}
            </p>
          </div>
          <form
            className="flex w-full max-w-xl gap-2"
            onSubmit={event => {
              event.preventDefault()
              void submit()
            }}
          >
            <input
              value={input}
              onChange={event => setInput(event.target.value)}
              placeholder={t('YouTube URL')}
              className="min-w-0 flex-1 rounded-lg border border-[var(--border)] bg-transparent px-3 py-2"
            />
            <button
              type="submit"
              disabled={loading || !input.trim()}
              className="rounded-lg bg-red-600 px-4 py-2 text-white disabled:opacity-50"
            >
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : t('Open')}
            </button>
          </form>
          {effectiveError && (
            <div
              role="alert"
              className="w-full max-w-xl rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-left text-sm"
            >
              <div className="flex gap-2">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{effectiveError}</span>
              </div>
              {lastUrl && (
                <button
                  type="button"
                  onClick={() => {
                    clearError()
                    void submit('youtube')
                  }}
                  className="mt-3 rounded-md border border-[var(--border)] px-3 py-1.5 font-medium"
                >
                  {t('Use native YouTube for this video')}
                </button>
              )}
            </div>
          )}
        </div>
      )}

      {material && (
        <div className="flex min-h-0 flex-1 flex-col">
          <WatchingPlayer
            key={`${material.material_id}:${material.playback.provider}`}
            playback={material.playback}
            transcriptLanguage={material.transcript.language || 'en'}
            onController={handleController}
            onTime={handleTime}
            onPersist={persist}
            onError={setPlayerError}
          />
          {effectiveError && (
            <div
              role="alert"
              className="m-3 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm"
            >
              {effectiveError}
              {material.playback.provider === 'invidious' && (
                <button
                  type="button"
                  onClick={() => void openNativeYouTube()}
                  className="ml-3 rounded border border-[var(--border)] px-2 py-1"
                >
                  {t('Use native YouTube')}
                </button>
              )}
            </div>
          )}
          <div className="flex items-center gap-3 border-b border-[var(--border)] px-4 py-3 text-sm">
            <span className="tabular-nums">
              {formatTime(time)} / {formatTime(duration || material.metadata.duration_seconds)}
            </span>
            <span className="rounded-full bg-[var(--muted)] px-2 py-0.5 text-xs">
              {material.playback.provider === 'youtube' ? 'YouTube' : 'Invidious'}
            </span>
            <a
              href={`https://youtu.be/${material.source.video_id}?t=${Math.floor(time)}`}
              target="_blank"
              rel="noreferrer"
              className="ml-auto inline-flex items-center gap-1 text-xs text-blue-600"
            >
              {t('Open official')} <ExternalLink className="h-3 w-3" />
            </a>
          </div>
          <div className="flex flex-wrap items-center gap-2 border-b border-[var(--border)] px-4 py-2">
            <span className="mr-1 text-xs text-[var(--muted-foreground)]">
              {t('Playback speed')}
            </span>
            <div role="group" aria-label={t('Playback speed')} className="flex flex-wrap gap-1">
              {WATCHING_PLAYBACK_RATES.map(rate => {
                const label = `${rate}x`
                return (
                  <button
                    key={rate}
                    type="button"
                    disabled={!controllerReady}
                    aria-pressed={playbackRate === rate}
                    aria-label={t('Set playback speed to {{rate}}', { rate: label })}
                    onClick={() => selectPlaybackRate(rate)}
                    className={`rounded-md border px-2 py-1 text-xs tabular-nums transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
                      playbackRate === rate
                        ? 'border-[var(--primary)] bg-[var(--primary)]/10 text-[var(--primary)]'
                        : 'border-[var(--border)] text-[var(--muted-foreground)] hover:text-[var(--foreground)]'
                    }`}
                  >
                    {label}
                  </button>
                )
              })}
            </div>
          </div>
          <div
            ref={transcriptListRef}
            data-testid="video-transcript-list"
            className="min-h-0 flex-1 overflow-y-auto p-4"
            onWheel={event => {
              if (tab !== 'transcript') return
              setFollowTranscript(false)
            }}
            onTouchMove={() => {
              if (tab === 'transcript') setFollowTranscript(false)
            }}
            onPointerDown={event => {
              // Native scrollbar drags target the scroll container itself.
              // Pointer events from cue/control buttons bubble through here
              // and must keep their own click semantics.
              if (tab === 'transcript' && event.target === event.currentTarget) {
                setFollowTranscript(false)
              }
            }}
            onKeyDown={event => {
              if (
                tab === 'transcript' &&
                ['ArrowDown', 'ArrowUp', 'PageDown', 'PageUp', 'Home', 'End'].includes(event.key)
              ) {
                setFollowTranscript(false)
              }
            }}
          >
            <div
              className="mb-3 grid w-full max-w-56 grid-cols-2 rounded-lg bg-[var(--muted)] p-1"
              role="tablist"
              aria-label={t('Video learning panels')}
            >
              {(['transcript', 'notes'] as const).map(item => (
                <button
                  key={item}
                  type="button"
                  role="tab"
                  aria-selected={tab === item}
                  onClick={() => {
                    setTab(item)
                    setEditingNoteId(null)
                  }}
                  className={`flex items-center justify-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-medium ${tab === item ? 'bg-[var(--background)] shadow-sm' : 'text-[var(--muted-foreground)]'}`}
                >
                  {item === 'transcript' ? (
                    <>
                      <Captions className="h-3.5 w-3.5" />
                      {t('Transcript')}
                    </>
                  ) : (
                    <>
                      <StickyNote className="h-3.5 w-3.5" />
                      {t('Video notes')}
                    </>
                  )}
                </button>
              ))}
            </div>

            {tab === 'transcript' ? (
              material.transcript.status !== 'ready' ? (
                <div className="rounded-lg border border-[var(--border)] p-4 text-sm text-[var(--muted-foreground)]">
                  <p>
                    {t(
                      'Transcript learning is unavailable ({{reason}}). Playback still works, but Explain here is disabled.',
                      {
                        reason: material.transcript.reason || t('no captions'),
                      }
                    )}
                  </p>
                  {material.playback.provider === 'invidious' && (
                    <button
                      type="button"
                      onClick={() => void retryTranscript()}
                      disabled={loading}
                      className="mt-3 rounded border border-[var(--border)] px-2 py-1 font-medium text-[var(--foreground)] disabled:opacity-50"
                    >
                      {t('Retry captions')}
                    </button>
                  )}
                </div>
              ) : (
                <>
                  <div className="mb-3 flex flex-wrap items-center gap-2">
                    <label className="relative min-w-48 flex-1">
                      <span className="sr-only">{t('Search transcript')}</span>
                      <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--muted-foreground)]" />
                      <input
                        type="search"
                        value={transcriptQuery}
                        aria-label={t('Search transcript')}
                        placeholder={t('Search transcript')}
                        onChange={event => {
                          const next = event.target.value
                          setTranscriptQuery(next)
                          setSelectedTranscriptMatch(-1)
                          if (next.trim()) setFollowTranscript(false)
                        }}
                        onKeyDown={event => {
                          if (event.key === 'Escape') {
                            event.preventDefault()
                            setTranscriptQuery('')
                            setSelectedTranscriptMatch(-1)
                            return
                          }
                          if (event.key === 'Enter') {
                            event.preventDefault()
                            moveTranscriptMatch(event.shiftKey ? -1 : 1)
                          }
                        }}
                        className="w-full rounded-lg border border-[var(--border)] bg-transparent py-2 pl-9 pr-3 text-sm"
                      />
                    </label>
                    {normalizedTranscriptQuery && (
                      <span
                        aria-live="polite"
                        className="text-xs tabular-nums text-[var(--muted-foreground)]"
                      >
                        {t('{{count}} transcript matches', {
                          count: transcriptMatches.length,
                        })}
                      </span>
                    )}
                    <div className="flex gap-1">
                      <button
                        type="button"
                        disabled={!transcriptMatches.length}
                        aria-label={t('Previous transcript match')}
                        onClick={() => moveTranscriptMatch(-1)}
                        className="rounded-md border border-[var(--border)] p-2 disabled:opacity-40"
                      >
                        <ChevronUp className="h-4 w-4" />
                      </button>
                      <button
                        type="button"
                        disabled={!transcriptMatches.length}
                        aria-label={t('Next transcript match')}
                        onClick={() => moveTranscriptMatch(1)}
                        className="rounded-md border border-[var(--border)] p-2 disabled:opacity-40"
                      >
                        <ChevronDown className="h-4 w-4" />
                      </button>
                    </div>
                  </div>
                  <div className="mb-3 flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      onClick={askHere}
                      disabled={!cue}
                      className="rounded-lg bg-[var(--primary)] px-3 py-2 text-sm text-[var(--primary-foreground)] disabled:opacity-50"
                    >
                      {t('Explain here')}
                    </button>
                    <button
                      type="button"
                      onClick={() => setFollowTranscript(current => !current)}
                      disabled={Boolean(normalizedTranscriptQuery)}
                      aria-pressed={followTranscript}
                      className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-40 ${followTranscript ? 'border-[var(--primary)] text-[var(--primary)]' : 'border-[var(--border)] text-[var(--muted-foreground)]'}`}
                    >
                      <ChevronsDown className="h-4 w-4" />
                      {t('Follow playback')}
                    </button>
                  </div>
                  {normalizedTranscriptQuery && transcriptMatches.length === 0 ? (
                    <p className="rounded-lg border border-[var(--border)] p-4 text-sm text-[var(--muted-foreground)]">
                      {t('No transcript matches.')}
                    </p>
                  ) : material.transcript.cues.length === 0 ? (
                    <p className="rounded-lg border border-[var(--border)] p-4 text-sm text-[var(--muted-foreground)]">
                      {t('No transcript cues available.')}
                    </p>
                  ) : (
                    <div className="space-y-1">
                      {(normalizedTranscriptQuery
                        ? transcriptMatches
                        : material.transcript.cues.map((_, index) => index)
                      ).map(index => {
                        const row = material.transcript.cues[index]
                        const active = row === cue
                        const selectedMatch =
                          Boolean(normalizedTranscriptQuery) &&
                          transcriptMatches[selectedTranscriptMatch] === index
                        return (
                          <button
                            key={`${row.start}-${index}`}
                            type="button"
                            data-active-cue={active ? 'true' : undefined}
                            data-transcript-cue={index}
                            onClick={() => controllerRef.current?.seek(row.start)}
                            className={`flex w-full gap-3 rounded-md px-2 py-1.5 text-left text-sm ${
                              active
                                ? 'bg-blue-500/15 ring-1 ring-blue-500/30'
                                : selectedMatch
                                  ? 'bg-violet-500/10 ring-1 ring-violet-500/30'
                                  : 'hover:bg-[var(--muted)]'
                            }`}
                          >
                            <span className="shrink-0 tabular-nums text-blue-600">
                              {formatTime(row.start)}
                            </span>
                            <span>{row.text}</span>
                          </button>
                        )
                      })}
                    </div>
                  )}
                </>
              )
            ) : (
              <div className="space-y-3">
                <form
                  className="space-y-2"
                  onSubmit={event => {
                    event.preventDefault()
                    void addNote()
                  }}
                >
                  <textarea
                    value={noteDraft}
                    onChange={event => setNoteDraft(event.target.value)}
                    placeholder={t('Note at {{time}}', {
                      time: formatTime(time),
                    })}
                    className="min-h-20 w-full resize-y rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-sm"
                  />
                  <button
                    type="submit"
                    disabled={noteBusy || !noteDraft.trim()}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3 py-2 text-sm text-[var(--primary-foreground)] disabled:opacity-50"
                  >
                    {noteBusy ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Check className="h-4 w-4" />
                    )}
                    {t('Add video note')}
                  </button>
                  <button
                    type="button"
                    onClick={() => void copyNotes()}
                    disabled={notesExportBusy || !notes.length}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-2 text-sm disabled:opacity-50"
                  >
                    {notesExportBusy ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : notesCopied ? (
                      <Check className="h-4 w-4" />
                    ) : (
                      <Copy className="h-4 w-4" />
                    )}
                    {notesCopied ? t('Notes copied') : t('Copy notes')}
                  </button>
                </form>

                {notesError && (
                  <p
                    role="alert"
                    className="rounded-lg border border-[var(--border)] bg-[var(--muted)] px-3 py-2 text-sm text-[var(--destructive)]"
                  >
                    {notesError}
                  </p>
                )}

                {notesLoading ? (
                  <p className="flex items-center gap-2 text-sm text-[var(--muted-foreground)]">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    {t('Loading notes.')}
                  </p>
                ) : notes.length ? (
                  notes.map(note => (
                    <article
                      key={`${note.notebook_id}:${note.note_id}`}
                      className="rounded-lg border border-[var(--border)] p-3"
                    >
                      <div className="flex items-start gap-2">
                        <button
                          type="button"
                          onClick={() => controllerRef.current?.seek(note.time_seconds)}
                          className="shrink-0 rounded px-1.5 py-0.5 font-mono text-xs tabular-nums text-blue-600 hover:bg-blue-500/10"
                        >
                          {formatTime(note.time_seconds)}
                        </button>
                        <div className="min-w-0 flex-1">
                          {editingNoteId === note.note_id ? (
                            <textarea
                              value={editingDraft}
                              onChange={event => setEditingDraft(event.target.value)}
                              aria-label={t('Edit note at {{time}}', {
                                time: formatTime(note.time_seconds),
                              })}
                              className="min-h-20 w-full resize-y rounded-lg border border-[var(--border)] bg-transparent px-2 py-1.5 text-sm"
                            />
                          ) : (
                            <p className="whitespace-pre-wrap text-sm">{note.body}</p>
                          )}
                          {note.quote && (
                            <blockquote className="mt-2 border-l-2 border-[var(--border)] pl-2 text-xs text-[var(--muted-foreground)]">
                              {note.quote}
                            </blockquote>
                          )}
                        </div>
                        <div className="flex shrink-0 items-center gap-1">
                          {editingNoteId === note.note_id ? (
                            <>
                              <button
                                type="button"
                                onClick={() => void saveEditedNote()}
                                disabled={noteBusy || !editingDraft.trim()}
                                className="rounded-md p-1.5 hover:bg-[var(--muted)] disabled:opacity-50"
                                aria-label={t('Save video note')}
                              >
                                <Check className="h-4 w-4" />
                              </button>
                              <button
                                type="button"
                                onClick={() => setEditingNoteId(null)}
                                disabled={noteBusy}
                                className="rounded-md p-1.5 hover:bg-[var(--muted)] disabled:opacity-50"
                                aria-label={t('Cancel')}
                              >
                                <X className="h-4 w-4" />
                              </button>
                            </>
                          ) : (
                            <button
                              type="button"
                              onClick={() => {
                                setEditingNoteId(note.note_id)
                                setEditingDraft(note.body)
                              }}
                              disabled={noteBusy}
                              className="rounded-md p-1.5 hover:bg-[var(--muted)] disabled:opacity-50"
                              aria-label={t('Edit note at {{time}}', {
                                time: formatTime(note.time_seconds),
                              })}
                            >
                              <Pencil className="h-4 w-4" />
                            </button>
                          )}
                          <button
                            type="button"
                            onClick={() => setPendingDeleteId(note.note_id)}
                            disabled={noteBusy}
                            className="rounded-md p-1.5 text-[var(--destructive)] hover:bg-[var(--destructive)]/10 disabled:opacity-50"
                            aria-label={t('Delete note at {{time}}', {
                              time: formatTime(note.time_seconds),
                            })}
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </div>
                      </div>
                    </article>
                  ))
                ) : (
                  !notesError && <p className="text-sm">{t('No notes yet.')}</p>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      <ConfirmDialog
        open={Boolean(pendingDeleteId)}
        title={t('Delete this note?')}
        confirmLabel={t('Delete')}
        tone="danger"
        busy={noteBusy}
        onConfirm={() => void confirmDelete()}
        onCancel={() => setPendingDeleteId(null)}
      >
        {t('This note will be removed from Video Learning.')}
      </ConfirmDialog>
    </section>
  )
}

function formatTime(value: number): string {
  const total = Math.max(0, Math.floor(Number(value) || 0))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = total % 60
  return hours
    ? `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
    : `${minutes}:${String(seconds).padStart(2, '0')}`
}
