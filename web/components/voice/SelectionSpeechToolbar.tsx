'use client'

import { useEffect, useState, type RefObject } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import { textFromDomSelection } from '@/lib/selection-text'
import { PlayAudioButton } from './SpeechButton'

type Passage = { text: string; left: number; top: number }

/** A speech-only action for learning transcripts that have no quote toolbar. */
export function SelectionSpeechToolbar({ rootRef }: { rootRef: RefObject<HTMLDivElement | null> }) {
  const { t } = useTranslation()
  const [passage, setPassage] = useState<Passage | null>(null)

  useEffect(() => {
    const root = rootRef.current
    if (!root) return
    const update = () => {
      const selection = window.getSelection()
      const focused = document.activeElement
      if (
        !selection ||
        selection.isCollapsed ||
        !selection.rangeCount ||
        focused?.matches('input,textarea,[contenteditable="true"]')
      ) {
        setPassage(null)
        return
      }
      const range = selection.getRangeAt(0)
      if (!root.contains(range.commonAncestorContainer)) {
        setPassage(null)
        return
      }
      const text = textFromDomSelection(selection).trim()
      const rects = range.getClientRects()
      const rect = rects.length ? rects[rects.length - 1] : range.getBoundingClientRect()
      if (
        !text ||
        !rect.width ||
        !rect.height ||
        rect.bottom < 0 ||
        rect.top > window.innerHeight
      ) {
        setPassage(null)
        return
      }
      const top = rect.top >= 60 ? rect.top - 48 : rect.bottom + 8
      setPassage({
        text,
        left: Math.max(12, Math.min(rect.right - 40, window.innerWidth - 52)),
        top: Math.max(12, Math.min(top, window.innerHeight - 52)),
      })
    }
    const clear = () => {
      const selection = window.getSelection()
      if (
        !selection ||
        selection.isCollapsed ||
        !selection.rangeCount ||
        !root.contains(selection.getRangeAt(0).commonAncestorContainer)
      )
        setPassage(null)
    }
    root.addEventListener('mouseup', update)
    root.addEventListener('keyup', update)
    root.addEventListener('pointerup', update)
    root.addEventListener('scroll', update)
    window.addEventListener('resize', update)
    document.addEventListener('selectionchange', clear)
    return () => {
      root.removeEventListener('mouseup', update)
      root.removeEventListener('keyup', update)
      root.removeEventListener('pointerup', update)
      root.removeEventListener('scroll', update)
      window.removeEventListener('resize', update)
      document.removeEventListener('selectionchange', clear)
    }
  }, [rootRef])

  useEffect(() => {
    if (!passage) return
    const escape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      event.stopPropagation()
      setPassage(null)
      window.getSelection()?.removeAllRanges()
    }
    document.addEventListener('keydown', escape, true)
    return () => document.removeEventListener('keydown', escape, true)
  }, [passage])

  if (!passage) return null
  return createPortal(
    <div
      role="toolbar"
      aria-label={t('Selected text')}
      onPointerDown={event => event.preventDefault()}
      className="fixed z-[70] size-10 rounded-xl bg-[var(--foreground)] text-[var(--background)] shadow-lg"
      style={{ left: passage.left, top: passage.top }}
    >
      <PlayAudioButton
        key={passage.text}
        content={passage.text}
        autoPlayFresh={false}
        selection
        className="inline-flex size-10 items-center justify-center rounded-xl transition hover:opacity-80 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--primary)]"
      />
    </div>,
    document.body
  )
}
