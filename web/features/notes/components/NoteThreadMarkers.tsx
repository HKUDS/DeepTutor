'use client'
/**
 * The page's conversations, folded onto the lines they were held at.
 *
 * Each thread is an orb in the right gutter beside the first line of its
 * block; a line with several holds them as a stack that fans out under the
 * pointer. The orb says what the conversation is doing — idle, still running,
 * failed, or answered since it was last read — and hovering it previews the
 * conversation, with open and delete one click away.
 *
 * Positions are measurements of the editor's DOM, recomputed when the
 * document, the layout or the thread list changes; nothing here is stored in
 * the page.
 */
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import { Sparkles, Trash2 } from 'lucide-react'
import type { NoteThreadView } from '../model/threads'
import { relativeTime } from '../model/threads'

type Placement = { blockId: string; top: number }

/** Where a block's first line sits, relative to the editor container. */
export function blockLineCenter(container: HTMLElement, blockId: string): number | null {
  const outer = container.querySelector<HTMLElement>(
    `.bn-block-outer[data-id="${CSS.escape(blockId)}"]`
  )
  const content = outer?.querySelector<HTMLElement>('.bn-block-content')
  if (!content) return null
  const inline = content.querySelector<HTMLElement>('.bn-inline-content')
  const base = container.getBoundingClientRect().top
  if (inline) {
    const style = getComputedStyle(inline)
    const line = parseFloat(style.lineHeight) || parseFloat(style.fontSize) * 1.5
    return inline.getBoundingClientRect().top - base + line / 2
  }
  // Cards (learning, files, embeds) have no text line: align with their header.
  return content.getBoundingClientRect().top - base + 22
}

export default function NoteThreadMarkers({
  editor,
  container,
  threads,
  activeSessionId,
  activeBlockId,
  interactive,
  onOpen,
  onDelete,
  onAsk,
}: {
  /** Anything that reports document changes; the measured layout follows them. */
  editor: { onChange: (callback: () => void) => (() => void) | void }
  container: HTMLDivElement | null
  threads: NoteThreadView[]
  /** The thread open in the side panel; its orb is drawn as the open one. */
  activeSessionId: string | null
  /** The line the open (maybe not yet saved) thread is about. */
  activeBlockId: string | null
  interactive: boolean
  onOpen: (sessionId: string) => void
  onDelete: (sessionId: string) => Promise<void>
  onAsk: (blockId: string) => void
}) {
  const [placements, setPlacements] = useState<Placement[]>([])
  const [hoverBlock, setHoverBlock] = useState<{ blockId: string; top: number } | null>(null)
  const frame = useRef(0)
  const blockIds = [...new Set(threads.map(t => t.block_id))]
  const key = blockIds.join('|')

  const measure = useCallback(() => {
    cancelAnimationFrame(frame.current)
    frame.current = requestAnimationFrame(() => {
      if (!container) return
      const next: Placement[] = []
      for (const blockId of key ? key.split('|') : []) {
        const top = blockLineCenter(container, blockId)
        if (top !== null) next.push({ blockId, top })
      }
      setPlacements(current =>
        current.length === next.length &&
        current.every(
          (p, i) => p.blockId === next[i].blockId && Math.abs(p.top - next[i].top) < 0.5
        )
          ? current
          : next
      )
    })
  }, [container, key])

  useLayoutEffect(() => {
    measure()
  }, [measure])
  useEffect(() => {
    if (!container) return
    const unsubscribe = editor.onChange(measure)
    const observer = new ResizeObserver(measure)
    observer.observe(container)
    window.addEventListener('resize', measure)
    void document.fonts?.ready.then(measure)
    return () => {
      unsubscribe?.()
      observer.disconnect()
      window.removeEventListener('resize', measure)
      cancelAnimationFrame(frame.current)
    }
  }, [container, editor, measure])

  // A faint "ask here" orb follows the pointer down lines with no thread yet.
  useEffect(() => {
    if (!container || !interactive) return
    const move = (event: PointerEvent) => {
      const target = event.target as HTMLElement
      if (target.closest('.dt-note-orbs, .dt-note-ask-orb')) return
      // The innermost block under the pointer is the line it means.
      const blockId = target.closest<HTMLElement>('.bn-block-outer')?.dataset.id
      if (!blockId) return
      const top = blockLineCenter(container, blockId)
      setHoverBlock(current =>
        top === null
          ? null
          : current?.blockId === blockId && current.top === top
            ? current
            : { blockId, top }
      )
    }
    const leave = () => setHoverBlock(null)
    container.addEventListener('pointermove', move)
    container.addEventListener('pointerleave', leave)
    return () => {
      container.removeEventListener('pointermove', move)
      container.removeEventListener('pointerleave', leave)
    }
  }, [container, interactive])

  if (!container) return null
  const byBlock = new Map<string, NoteThreadView[]>()
  for (const thread of threads) {
    const list = byBlock.get(thread.block_id) ?? []
    list.push(thread)
    byBlock.set(thread.block_id, list)
  }
  const showAsk =
    hoverBlock && !byBlock.has(hoverBlock.blockId) && hoverBlock.blockId !== activeBlockId
  return (
    <div className="dt-note-thread-layer" aria-hidden={!placements.length && !showAsk}>
      {placements.map(({ blockId, top }) => (
        <OrbStack
          key={blockId}
          top={top}
          threads={byBlock.get(blockId) ?? []}
          activeSessionId={activeSessionId}
          open={activeBlockId === blockId}
          interactive={interactive}
          onOpen={onOpen}
          onDelete={onDelete}
        />
      ))}
      {showAsk && interactive && (
        <AskOrb top={hoverBlock.top} onAsk={() => onAsk(hoverBlock.blockId)} />
      )}
    </div>
  )
}

function AskOrb({ top, onAsk }: { top: number; onAsk: () => void }) {
  const { t } = useTranslation()
  return (
    <button
      className="dt-note-ask-orb"
      style={{ top }}
      aria-label={t('Ask Dito about this line')}
      onMouseDown={e => e.preventDefault()}
      onClick={onAsk}
    >
      <Sparkles size={12} strokeWidth={1.9} />
    </button>
  )
}

function OrbStack({
  top,
  threads,
  activeSessionId,
  open,
  interactive,
  onOpen,
  onDelete,
}: {
  top: number
  threads: NoteThreadView[]
  activeSessionId: string | null
  open: boolean
  interactive: boolean
  onOpen: (sessionId: string) => void
  onDelete: (sessionId: string) => Promise<void>
}) {
  const { t } = useTranslation()
  const [anchor, setAnchor] = useState<HTMLDivElement | null>(null)
  const [hover, setHover] = useState(false)
  const leaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const shown = threads.slice(-4)
  const hidden = threads.length - shown.length
  const enter = () => {
    if (leaveTimer.current) clearTimeout(leaveTimer.current)
    setHover(true)
  }
  const leave = () => {
    if (leaveTimer.current) clearTimeout(leaveTimer.current)
    leaveTimer.current = setTimeout(() => setHover(false), 160)
  }
  useEffect(
    () => () => {
      if (leaveTimer.current) clearTimeout(leaveTimer.current)
    },
    []
  )
  const running = threads.some(thread => thread.state === 'running')
  return (
    <>
      <div
        ref={setAnchor}
        className="dt-note-orbs"
        style={{ top }}
        data-open={open || undefined}
        data-running={running || undefined}
        data-hover={hover || undefined}
        onPointerEnter={enter}
        onPointerLeave={leave}
      >
        {shown.map(thread => (
          <button
            key={thread.session_id}
            data-thread-orb={thread.session_id}
            className="dt-note-orb"
            data-state={thread.state}
            data-active={thread.session_id === activeSessionId || undefined}
            aria-label={`${t('Open conversation')}: ${thread.label}`}
            onMouseDown={e => e.preventDefault()}
            onClick={() => onOpen(thread.session_id)}
          />
        ))}
        {hidden > 0 && <span className="dt-note-orb-more">+{hidden}</span>}
      </div>
      {hover &&
        interactive &&
        anchor &&
        createPortal(
          <ThreadPreview
            anchor={anchor}
            threads={threads}
            onEnter={enter}
            onLeave={leave}
            onOpen={sessionId => {
              setHover(false)
              onOpen(sessionId)
            }}
            onDelete={onDelete}
          />,
          document.body
        )}
    </>
  )
}

function ThreadPreview({
  anchor,
  threads,
  onEnter,
  onLeave,
  onOpen,
  onDelete,
}: {
  anchor: HTMLElement
  threads: NoteThreadView[]
  onEnter: () => void
  onLeave: () => void
  onOpen: (sessionId: string) => void
  onDelete: (sessionId: string) => Promise<void>
}) {
  const { t, i18n } = useTranslation()
  const [confirming, setConfirming] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<string | null>(null)
  const rect = anchor.getBoundingClientRect()
  const width = 300
  // Below the line, right-aligned to the orbs; flipped up near the bottom.
  const left = Math.max(12, Math.min(rect.right - width + 10, window.innerWidth - width - 12))
  const below = rect.bottom + 8
  const flip = below + 220 > window.innerHeight
  return (
    <div
      className="dt-popover dt-note-thread-preview"
      role="dialog"
      aria-label={t('Conversations on this line')}
      style={{
        left,
        width,
        ...(flip ? { bottom: window.innerHeight - rect.top + 8 } : { top: below }),
      }}
      onPointerEnter={onEnter}
      onPointerLeave={onLeave}
    >
      {[...threads].reverse().map(thread => (
        <div key={thread.session_id} className="dt-note-thread-row" data-state={thread.state}>
          <button className="dt-note-thread-row-main" onClick={() => onOpen(thread.session_id)}>
            <span className="dt-note-thread-row-head">
              <span className="dt-note-orb is-static" data-state={thread.state} aria-hidden />
              <strong>{thread.label}</strong>
              <time>{stateLabel(thread, t) || relativeTime(thread.updated_at, i18n.language)}</time>
            </span>
            {thread.last_message && (
              <span className="dt-note-thread-row-body">{thread.last_message}</span>
            )}
          </button>
          {confirming === thread.session_id ? (
            <span className="dt-note-thread-confirm">
              <button
                className="is-danger"
                disabled={deleting === thread.session_id}
                onClick={() => {
                  setDeleting(thread.session_id)
                  void onDelete(thread.session_id).finally(() => {
                    setDeleting(null)
                    setConfirming(null)
                  })
                }}
              >
                {t('Delete')}
              </button>
              <button onClick={() => setConfirming(null)}>{t('Cancel')}</button>
            </span>
          ) : (
            <button
              className="dt-note-thread-delete"
              aria-label={t('Delete conversation')}
              onClick={() => setConfirming(thread.session_id)}
            >
              <Trash2 size={13} strokeWidth={1.7} />
            </button>
          )}
        </div>
      ))}
    </div>
  )
}

export function stateLabel(thread: NoteThreadView, t: (key: string) => string) {
  if (thread.state === 'running') return t('Running…')
  if (thread.state === 'failed') return t('Failed')
  return ''
}
