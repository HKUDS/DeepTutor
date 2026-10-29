'use client'
/**
 * The page's own outline, in the left margin.
 *
 * Folded, it is a rail of short marks — one per heading, longer for higher
 * levels, the one you are reading in ink — that opens into the titles under
 * the pointer. Open, the titles stay in the margin. H1 to H4, toggle headings
 * included. Built from the live blocks, so it follows typing.
 */
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { PanelLeftClose, TableOfContents } from 'lucide-react'
import Tooltip from '@/shared/ui/Tooltip'
import type { NoteBlock } from '@/lib/notes-api'
import { inlineText } from '../model/threads'

interface Heading {
  id: string
  level: number
  text: string
}

export function pageHeadings(blocks: NoteBlock[] | null | undefined): Heading[] {
  const result: Heading[] = []
  const walk = (items: NoteBlock[]) =>
    items.forEach(block => {
      if (block.type === 'heading' || block.type === 'toggleHeading') {
        const level = Number(block.props.level) || 1
        const text = inlineText(block.content).trim()
        if (level <= 4 && text) result.push({ id: block.id, level, text })
      }
      walk(block.children || [])
    })
  walk(blocks || [])
  return result
}

export default function NoteOutline({
  blocks,
  scroller,
  open,
  roomy,
  onToggle,
  onJump,
}: {
  blocks: NoteBlock[] | null | undefined
  /** The scrolling page column; the reading position is measured in it. */
  scroller: HTMLElement | null
  open: boolean
  /** Whether the margin is wide enough to hold the open outline beside the text. */
  roomy: boolean
  onToggle: () => void
  onJump: (id: string) => void
}) {
  const { t } = useTranslation()
  const headings = useMemo(() => pageHeadings(blocks), [blocks])
  const [current, setCurrent] = useState<string | null>(null)
  const [peek, setPeek] = useState(false)
  const minLevel = headings.reduce((min, h) => Math.min(min, h.level), 4)

  useEffect(() => {
    if (!scroller || !headings.length) return
    let frame = 0
    const update = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => {
        const top = scroller.getBoundingClientRect().top + 96
        let active: string | null = headings[0]?.id ?? null
        for (const heading of headings) {
          const el = scroller.querySelector(`.bn-block-outer[data-id="${CSS.escape(heading.id)}"]`)
          if (!el) continue
          if (el.getBoundingClientRect().top <= top) active = heading.id
          else break
        }
        setCurrent(active)
      })
    }
    update()
    scroller.addEventListener('scroll', update, { passive: true })
    return () => {
      cancelAnimationFrame(frame)
      scroller.removeEventListener('scroll', update)
    }
  }, [headings, scroller])

  if (!headings.length) return null
  const expanded = (open && roomy) || peek
  return (
    <div className="dt-note-outline-anchor">
      <nav
        className="dt-note-outline"
        data-expanded={expanded || undefined}
        data-pinned={(open && roomy) || undefined}
        aria-label={t('On this page')}
        onPointerEnter={() => (!open || !roomy ? setPeek(true) : undefined)}
        onPointerLeave={() => setPeek(false)}
      >
        <div className="dt-note-outline-head">
          <span>{t('On this page')}</span>
          {roomy && (
            <Tooltip label={t(open ? 'Fold the outline' : 'Keep the outline open')} side="right">
              <button
                className="dt-note-icon-button"
                aria-label={t(open ? 'Fold the outline' : 'Keep the outline open')}
                aria-pressed={open}
                onClick={() => {
                  setPeek(false)
                  onToggle()
                }}
              >
                {open ? (
                  <PanelLeftClose size={14} strokeWidth={1.7} />
                ) : (
                  <TableOfContents size={14} strokeWidth={1.7} />
                )}
              </button>
            </Tooltip>
          )}
        </div>
        <ol>
          {headings.map(heading => (
            <li key={heading.id} data-level={heading.level - minLevel + 1}>
              <button
                aria-current={heading.id === current ? 'location' : undefined}
                onClick={() => {
                  setPeek(false)
                  onJump(heading.id)
                }}
              >
                <span className="dt-note-outline-mark" aria-hidden />
                <span className="dt-note-outline-text">{heading.text}</span>
              </button>
            </li>
          ))}
        </ol>
      </nav>
    </div>
  )
}
