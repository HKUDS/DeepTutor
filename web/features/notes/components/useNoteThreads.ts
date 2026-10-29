'use client'
/**
 * The page's conversations, run from the page.
 *
 * Every thread is an ordinary session in the shared chat runtime; what this
 * hook adds is the page's side of it: which line a thread is held at, which
 * one the side panel shows, sending into it even while the panel is closed,
 * and the learning blocks a thread is filling. It lives with the page rather
 * than the panel so closing the panel never drops a turn's consequences.
 */
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useChatStateAdapter, type MessageItem } from '@/features/chat/ChatStateAdapter'
import { anchorThread, deleteThread, listThreads, type NoteThread } from '@/lib/notes-api'
import { browserStorage } from '@/shared/storage'
import { learningConfig, learningMode } from '../model/ai-request'
import { noteGenerationConfig } from '../model/research'
import { noteGenerationError } from '../model/generation-error'
import { setGenerationPreview } from '../model/generation-previews'
import { learningKind } from '../model/learning-kinds'
import { threadViews } from '../model/threads'
import type { NoteAsk } from './NoteEditor'

export interface OpenThread {
  /** The runtime's key: a draft key until the first turn makes it a session. */
  key: string
  sessionId: string | null
  blockId: string
  quote: string
  origin: 'ask' | 'generate'
  /** A knowledge base to mount once the runtime shows this thread. */
  knowledgeRef?: string
  /** Opened to make another version of this learning block: the composer's
   *  first "make" fills the block again instead of adding one below. */
  regenerate?: { kind: string; config?: Record<string, unknown> }
}

export interface ThreadSendOptions {
  /** Fill a learning block of this kind with the reply, instead of chatting. */
  generate?: { blockId: string; kind: string; config?: Record<string, unknown> }
}

type Generation = {
  blockId: string
  key: string
  sessionId: string | null
  at: number
  started?: boolean
  /** Filled by the chat loop through a suggestion: its streamed text is
   *  narration, not the material, so the block shows progress only. */
  viaChat?: boolean
}
type PendingSend = { key: string; content: string; options: ThreadSendOptions }

function readJson<T>(key: string | null, fallback: T): T {
  if (!key) return fallback
  try {
    return (JSON.parse(browserStorage.readRaw('local', key) || 'null') as T) ?? fallback
  } catch {
    return fallback
  }
}

const quoted = (quote: string) => `> ${quote.replace(/\n+/g, '\n> ')}\n\n`

export function useNoteThreads({
  pageId,
  owner,
  embedded,
  flush,
  onSuggestions,
  onError,
}: {
  pageId: string
  owner: string | null
  embedded: boolean
  flush: () => Promise<void>
  onSuggestions: () => void
  onError: (message: string) => void
}) {
  const { t } = useTranslation()
  const runtime = useChatStateAdapter()
  const {
    state,
    sessionStatuses,
    newSession,
    loadSession,
    showCachedSession,
    configureSession,
    sendMessage,
    regenerateLastMessage,
    setKBs,
  } = runtime
  const [threads, setThreads] = useState<NoteThread[]>([])
  const [loaded, setLoaded] = useState(false)
  const [opened, setOpen] = useState<OpenThread | null>(null)
  const [prefill, setPrefill] = useState<{ id: number; text: string } | null>(null)
  const seenKey = owner ? `deeptutor.notes.seen:${owner}:${pageId}` : null
  const generationsKey = owner ? `deeptutor.notes.generations:${owner}:${pageId}` : null
  const [seen, setSeen] = useState<Record<string, number>>({})
  const [seenFrom, setSeenFrom] = useState<string | null>(null)
  if (seenKey !== seenFrom) {
    setSeenFrom(seenKey)
    setSeen(readJson(seenKey, {}))
  }
  // Blocks being filled, and which session each draft became. Bookkeeping the
  // effects below read and update; ``tick`` re-runs them after a change.
  const generations = useRef<Generation[] | null>(null)
  const boundKeys = useRef<Record<string, string>>({})
  const [tick, setTick] = useState(0)
  const pending = useRef<PendingSend | null>(null)
  const kbApplied = useRef(new Set<string>())
  const latest = useRef({ onSuggestions, onError, flush })
  useLayoutEffect(() => {
    latest.current = { onSuggestions, onError, flush }
  })
  const loadGenerations = useCallback(() => {
    if (generations.current === null) generations.current = readJson(generationsKey, [])
    return generations.current
  }, [generationsKey])
  const saveGenerations = useCallback(
    (update: (current: Generation[]) => Generation[]) => {
      generations.current = update(loadGenerations())
      if (generationsKey)
        browserStorage.writeRaw('local', generationsKey, JSON.stringify(generations.current))
    },
    [generationsKey, loadGenerations]
  )
  const markSeen = useCallback(
    (sessionId: string | null) => {
      if (!sessionId || !seenKey) return
      setSeen(current => {
        const next = { ...current, [sessionId]: Date.now() / 1000 }
        browserStorage.writeRaw('local', seenKey, JSON.stringify(next))
        return next
      })
    },
    [seenKey]
  )

  const refresh = useCallback(
    () =>
      listThreads(pageId)
        .then(result => {
          setThreads(result.threads)
          setLoaded(true)
        })
        .catch(() => setLoaded(true)),
    [pageId]
  )
  useEffect(() => {
    void refresh()
  }, [refresh])

  /* ── Which conversations are live in this tab ─────────────────────── */
  const bound =
    !!opened &&
    (state.sessionKey === opened.key ||
      state.boundFromKey === opened.key ||
      (!!opened.sessionId && state.sessionId === opened.sessionId))
  // A draft is a thread from its first turn on: the runtime names its session.
  const open = useMemo(
    () =>
      opened && !opened.sessionId && bound && state.sessionId
        ? { ...opened, sessionId: state.sessionId }
        : opened,
    [bound, opened, state.sessionId]
  )
  const running = useMemo(() => {
    const ids = new Set(Object.keys(sessionStatuses))
    if (state.isStreaming && state.sessionId) ids.add(state.sessionId)
    return ids
  }, [sessionStatuses, state.isStreaming, state.sessionId])
  const runningKey = [...running].sort().join(',')
  const firstRun = useRef(true)
  useEffect(() => {
    // A turn starting or ending changes a thread's orb and may have filed
    // suggestions on the page.
    if (firstRun.current) {
      firstRun.current = false
      return
    }
    void refresh()
    latest.current.onSuggestions()
  }, [refresh, runningKey])
  // A turn running in another tab is only known from the server.
  const remoteRunning = threads.some(t => t.status === 'running' && !running.has(t.session_id))
  useEffect(() => {
    if (!remoteRunning) return
    const timer = setInterval(() => void refresh(), 4000)
    return () => clearInterval(timer)
  }, [refresh, remoteRunning])

  /* ── A draft becomes a thread on its first turn ───────────────────── */
  const anchoring = useRef(new Set<string>())
  useEffect(() => {
    if (!opened || opened.sessionId || !open?.sessionId) return
    const sessionId = open.sessionId
    boundKeys.current[opened.key] = sessionId
    if (anchoring.current.has(sessionId)) return
    anchoring.current.add(sessionId)
    void anchorThread(pageId, {
      session_id: sessionId,
      block_id: opened.blockId,
      quote: opened.quote,
      origin: opened.origin,
    })
      .then(() => refresh())
      .catch(e => latest.current.onError(String(e)))
  }, [open?.sessionId, opened, pageId, refresh])

  useEffect(() => {
    if (!opened?.knowledgeRef || !bound || kbApplied.current.has(opened.key)) return
    kbApplied.current.add(opened.key)
    setKBs([opened.knowledgeRef])
  }, [bound, opened, setKBs])

  /* ── Sending ──────────────────────────────────────────────────────── */
  const dispatchSend = useCallback(
    async (content: string, options: ThreadSendOptions, target: OpenThread) => {
      try {
        await latest.current.flush()
        const generate = options.generate
        if (generate) {
          saveGenerations(current => [
            ...current.filter(g => g.blockId !== generate.blockId),
            {
              blockId: generate.blockId,
              key: target.key,
              sessionId: target.sessionId,
              at: Date.now(),
              viaChat: learningMode(generate.kind) === 'chat',
            },
          ])
          setTick(n => n + 1)
          setGenerationPreview(generate.blockId, {
            content: '',
            pending: true,
            sessionId: target.sessionId ?? undefined,
          })
        }
        const mode = generate ? learningMode(generate.kind) : 'chat'
        const config = generate
          ? noteGenerationConfig(mode, learningConfig(generate.kind, generate.config))
          : undefined
        // The first message carries the passage it is about, as a quote the
        // learner sees in the conversation too.
        const text =
          target.quote && !state.messages.length ? quoted(target.quote) + content : content
        sendMessage(text, undefined, config, undefined, undefined, {
          ...(mode !== 'chat' ? { capability: mode } : {}),
          noteGeneration: generate ? { block_id: generate.blockId, kind: generate.kind } : null,
        })
      } catch (err) {
        const message = t(noteGenerationError(String(err instanceof Error ? err.message : err)))
        if (options.generate)
          setGenerationPreview(options.generate.blockId, {
            content: '',
            pending: false,
            error: message,
          })
        latest.current.onError(message)
      }
    },
    [saveGenerations, sendMessage, state.messages.length, t]
  )
  // A send queued while the thread was still being selected goes out once the
  // runtime shows it — the same tick for an open thread, a commit later for a
  // new or reloaded one.
  useEffect(() => {
    const queued = pending.current
    if (!queued || !open || queued.key !== open.key || !bound || state.isStreaming) return
    pending.current = null
    void dispatchSend(queued.content, queued.options, open)
  }, [bound, dispatchSend, open, state.isStreaming])

  const send = useCallback(
    (content: string, options: ThreadSendOptions = {}) => {
      if (!open || !content.trim()) return
      if (bound && !state.isStreaming) void dispatchSend(content, options, open)
      else pending.current = { key: open.key, content, options }
    },
    [bound, dispatchSend, open, state.isStreaming]
  )

  /* ── Opening ──────────────────────────────────────────────────────── */
  const openThread = useCallback(
    async (sessionId: string, then?: Omit<PendingSend, 'key'>) => {
      const thread = threads.find(t => t.session_id === sessionId)
      if (!thread) return
      const next: OpenThread = {
        key: sessionId,
        sessionId,
        blockId: thread.block_id,
        quote: thread.quote,
        origin: thread.origin,
      }
      setOpen(next)
      setPrefill(null)
      markSeen(sessionId)
      if (then) pending.current = { key: sessionId, ...then }
      try {
        if (!showCachedSession(sessionId)) await loadSession(sessionId)
        configureSession({ noteDocumentId: pageId, workspaceMode: null }, sessionId)
      } catch (err) {
        latest.current.onError(String(err instanceof Error ? err.message : err))
      }
    },
    [configureSession, loadSession, markSeen, pageId, showCachedSession, threads]
  )

  const startThread = useCallback(
    (
      ask: NoteAsk & {
        origin?: 'ask' | 'generate'
        send?: Omit<PendingSend, 'key'>
        regenerate?: OpenThread['regenerate']
      }
    ) => {
      // Asking again at the line of an open, still empty conversation reuses it.
      const reuse =
        open && !open.sessionId && bound && !state.messages.length && open.blockId === ask.blockId
      const key = reuse
        ? open.key
        : newSession({ noteDocumentId: pageId, capability: null, workspaceMode: null })
      setOpen({
        key,
        sessionId: null,
        blockId: ask.blockId,
        quote: (ask.quote || '').slice(0, 600),
        origin: ask.origin ?? 'ask',
        knowledgeRef: ask.knowledgeRef,
        regenerate: ask.regenerate,
      })
      if (ask.send) pending.current = { key, ...ask.send }
      else if (ask.prompt && ask.autoSend)
        pending.current = { key, content: ask.prompt, options: {} }
      setPrefill(
        ask.prompt && !ask.autoSend && !ask.send ? { id: Date.now(), text: ask.prompt } : null
      )
    },
    [bound, newSession, open, pageId, state.messages.length]
  )

  /** A conversation not begun yet follows the block the learner points at. */
  const retarget = useCallback(
    (blockId: string) => {
      if (!opened || opened.sessionId || opened.blockId === blockId) return false
      if (bound && state.messages.length) return false
      setOpen({ ...opened, blockId, quote: '' })
      return true
    },
    [bound, opened, state.messages.length]
  )

  /** A learning block's own "Generate": runs in that block's conversation. */
  const generateBlock = useCallback(
    (detail: {
      blockId: string
      kind: string
      prompt?: string
      config?: Record<string, unknown>
    }) => {
      const request = detail.prompt?.trim() || t('Generate this learning block from the page')
      const content = `${t(learningKind(detail.kind).label)} · ${request}`
      const send = {
        content,
        options: {
          generate: { blockId: detail.blockId, kind: detail.kind, config: detail.config },
        },
      }
      const existing = [...threads]
        .reverse()
        .find(thread => thread.block_id === detail.blockId && thread.origin === 'generate')
      if (open?.sessionId && existing?.session_id === open.sessionId) {
        if (bound && !state.isStreaming) void dispatchSend(send.content, send.options, open)
        else pending.current = { key: open.key, ...send }
        return
      }
      if (existing) void openThread(existing.session_id, send)
      else startThread({ blockId: detail.blockId, origin: 'generate', send })
    },
    [bound, dispatchSend, open, openThread, startThread, state.isStreaming, t, threads]
  )

  /** "Regenerate…" from a block's menu: a new conversation at the block, its
   *  old request in the composer to edit before anything is sent. */
  const regenerateBlock = useCallback(
    (detail: {
      blockId: string
      kind: string
      prompt?: string
      config?: Record<string, unknown>
    }) =>
      startThread({
        blockId: detail.blockId,
        origin: 'generate',
        prompt: detail.prompt?.trim() || undefined,
        regenerate: { kind: detail.kind, config: detail.config },
      }),
    [startThread]
  )

  const regenerate = useCallback(() => {
    if (!bound || state.isStreaming || !open) return
    const lastUser = [...state.messages].reverse().find(m => m.role === 'user')
    const target = lastUser?.requestSnapshot?.noteGeneration
    if (target?.block_id) {
      saveGenerations(current => [
        ...current.filter(g => g.blockId !== target.block_id),
        {
          blockId: target.block_id,
          key: open.key,
          sessionId: open.sessionId,
          at: Date.now(),
          viaChat: learningMode(target.kind || '') === 'chat',
        },
      ])
      setTick(n => n + 1)
      setGenerationPreview(target.block_id, {
        content: '',
        pending: true,
        sessionId: open.sessionId ?? undefined,
      })
    }
    regenerateLastMessage()
  }, [bound, open, regenerateLastMessage, saveGenerations, state.isStreaming, state.messages])

  const removeThread = useCallback(
    async (sessionId: string) => {
      try {
        await deleteThread(pageId, sessionId)
        if (open?.sessionId === sessionId) setOpen(null)
        await refresh()
      } catch (err) {
        latest.current.onError(String(err instanceof Error ? err.message : err))
      }
    },
    [open, pageId, refresh]
  )

  const close = useCallback(() => {
    if (open?.sessionId) markSeen(open.sessionId)
    pending.current = null
    setOpen(null)
    setPrefill(null)
  }, [markSeen, open])

  /* ── Learning blocks being filled ─────────────────────────────────── */
  const lastAssistant = (messages: MessageItem[]) =>
    [...messages].reverse().find(m => m.role === 'assistant')
  useEffect(() => {
    const list = loadGenerations()
    if (!list.length) return
    const finished: string[] = []
    const started: string[] = []
    for (const g of list) {
      const sessionId = g.sessionId ?? boundKeys.current[g.key] ?? null
      const active =
        state.sessionKey === g.key ||
        state.boundFromKey === g.key ||
        (!!sessionId && state.sessionId === sessionId)
      const thread = sessionId ? threads.find(t => t.session_id === sessionId) : undefined
      const isPending = active
        ? state.isStreaming
        : (!!sessionId && running.has(sessionId)) || thread?.status === 'running'
      if (isPending) {
        if (!g.started) started.push(g.blockId)
        setGenerationPreview(g.blockId, {
          content: active && !g.viaChat ? lastAssistant(state.messages)?.content || '' : '',
          pending: true,
          sessionId: sessionId ?? state.sessionId ?? undefined,
        })
        continue
      }
      // Not yet seen running: a queued send, or a reload that has not heard back.
      if (
        !g.started &&
        Date.now() - g.at < 20_000 &&
        !(loaded && thread && thread.status !== 'running')
      )
        continue
      finished.push(g.blockId)
      const failure = active
        ? [...(lastAssistant(state.messages)?.events || [])].reverse().find(e => e.type === 'error')
            ?.content || (state.lastTurnFailed ? 'failed' : '')
        : thread?.status === 'failed'
          ? 'failed'
          : ''
      setGenerationPreview(
        g.blockId,
        failure
          ? {
              content: '',
              pending: false,
              error:
                failure === 'failed'
                  ? t('Generation failed. Open the conversation to see why.')
                  : failure,
              sessionId: sessionId ?? undefined,
            }
          : null
      )
    }
    if (started.length || finished.length) {
      saveGenerations(current =>
        current
          .filter(g => !finished.includes(g.blockId))
          .map(g => ({
            ...g,
            sessionId: g.sessionId ?? boundKeys.current[g.key] ?? null,
            started: g.started || started.includes(g.blockId),
          }))
      )
      if (finished.length) latest.current.onSuggestions()
    }
  }, [loadGenerations, loaded, running, saveGenerations, state, t, threads, tick])

  /* ── A sidebar link (`?chat=`) opens its thread ───────────────────── */
  const linked = useRef(false)
  useEffect(() => {
    if (!loaded || linked.current || embedded) return
    linked.current = true
    const sessionId = new URLSearchParams(window.location.search).get('chat')
    // A one-time handoff from the URL, not state derived from it.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (sessionId && threads.some(t => t.session_id === sessionId)) void openThread(sessionId)
  }, [embedded, loaded, openThread, threads])

  const views = useMemo(
    () =>
      threadViews(threads, {
        running,
        seen,
        openSessionId: open?.sessionId ?? null,
        untitled: t('New conversation'),
      }),
    [open?.sessionId, running, seen, t, threads]
  )

  return {
    threads: views,
    open,
    bound,
    hasMessages: bound && state.messages.length > 0,
    prefill,
    send,
    openThread,
    startThread,
    retarget,
    generateBlock,
    regenerateBlock,
    regenerate,
    removeThread,
    close,
  }
}
