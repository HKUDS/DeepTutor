'use client'

import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { ChevronDown, Database, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { UsageSummary } from './usage-summary'

export function UsageFooter({ turn, session }: { turn: UsageSummary; session: UsageSummary }) {
  const { t, i18n } = useTranslation()
  const [open, setOpen] = useState(false)
  const [scope, setScope] = useState<'turn' | 'session'>('turn')
  const anchor = useRef<HTMLButtonElement>(null)
  const panel = useRef<HTMLDivElement>(null)
  const id = useId()
  const [position, setPosition] = useState({ top: 0, left: 0 })
  const summary = scope === 'turn' ? turn : session
  const shown = summary
  const number = (n?: number | null) => (n == null ? '—' : n.toLocaleString(i18n.language))
  const rate = (n?: number | null) => (n == null ? '—' : `${(n * 100).toFixed(1)}%`)
  const compact = new Intl.NumberFormat(i18n.language, {
    notation: 'compact',
    maximumFractionDigits: 1,
  })
  const seconds = (n?: number | null) =>
    n == null ? '—' : t('{{value}} s', { value: n.toFixed(2) })
  const cacheKnown = Boolean(summary.cache_reported_calls)
  const uncached = cacheKnown
    ? Math.max(
        0,
        (summary.cache_input_tokens ?? 0) -
          (shown.cache_read_input_tokens ?? 0) -
          (shown.cache_creation_input_tokens ?? 0)
      )
    : null

  useLayoutEffect(() => {
    if (!open) return
    const place = () => {
      const rect = anchor.current?.getBoundingClientRect()
      const box = panel.current?.getBoundingClientRect()
      if (!rect || !box) return
      const above = rect.top - box.height - 8
      setPosition({
        left: Math.max(12, Math.min(rect.right - box.width, window.innerWidth - box.width - 12)),
        top: Math.max(
          12,
          above >= 12 ? above : Math.min(rect.bottom + 8, window.innerHeight - box.height - 12)
        ),
      })
    }
    place()
    window.addEventListener('resize', place)
    window.addEventListener('scroll', place, true)
    return () => {
      window.removeEventListener('resize', place)
      window.removeEventListener('scroll', place, true)
    }
  }, [open, scope])

  useEffect(() => {
    if (!open) return
    const dismiss = (e: PointerEvent) => {
      if (!panel.current?.contains(e.target as Node) && !anchor.current?.contains(e.target as Node))
        setOpen(false)
    }
    const escape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false)
        anchor.current?.focus()
      }
    }
    document.addEventListener('pointerdown', dismiss)
    document.addEventListener('keydown', escape)
    panel.current?.focus()
    return () => {
      document.removeEventListener('pointerdown', dismiss)
      document.removeEventListener('keydown', escape)
    }
  }, [open])

  const rows = [
    [t('Input tokens'), number(shown.prompt_tokens)],
    [t('Uncached input'), number(uncached)],
    [t('Cache read'), cacheKnown ? number(shown.cache_read_input_tokens) : '—'],
    [
      t('Cache write'),
      number(summary.cache_write_reported_calls ? summary.cache_creation_input_tokens : null),
    ],
    [t('Output tokens'), number(shown.completion_tokens)],
    [t('Reasoning tokens'), number(shown.reasoning_tokens)],
    [t('Cache hit rate'), rate(shown.cache_hit_rate)],
    [t('Model time'), seconds(shown.duration_seconds)],
    [t('TTFT'), seconds(shown.ttft_seconds)],
    [
      t('TPS'),
      shown.tokens_per_second == null
        ? '—'
        : t('{{value}} tok/s', { value: shown.tokens_per_second.toFixed(1) }),
    ],
  ]
  return (
    <>
      <button
        ref={anchor}
        type="button"
        aria-expanded={open}
        aria-controls={id}
        aria-haspopup="dialog"
        onClick={() => setOpen(!open)}
        className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--primary)]"
      >
        <Database size={12} aria-hidden="true" />
        <span>
          {compact.format(turn.total_tokens ?? 0)} {t('tokens')}
        </span>
        <span aria-hidden="true">·</span>
        <span>
          {t('Cache hit rate')} {rate(turn.cache_hit_rate)}
        </span>
        <ChevronDown size={12} aria-hidden="true" className={open ? 'rotate-180' : ''} />
      </button>
      {open &&
        createPortal(
          <div
            ref={panel}
            id={id}
            role="dialog"
            aria-label={t('Token usage and performance')}
            tabIndex={-1}
            style={position}
            className="fixed z-[100] w-[272px] max-w-[calc(100vw-24px)] max-h-[calc(100dvh-24px)] overflow-y-auto rounded-xl border border-[var(--border)] bg-[var(--background)] p-3 text-xs text-[var(--foreground)] shadow-lg outline-none"
          >
            <div
              className="mb-3 flex items-center gap-1"
              role="group"
              aria-label={t('Statistics scope')}
            >
              {(['turn', 'session'] as const).map(value => (
                <button
                  key={value}
                  type="button"
                  aria-pressed={scope === value}
                  onClick={() => {
                    setScope(value)
                  }}
                  className={`flex-1 rounded-md px-2 py-1 text-[11px] transition-colors ${scope === value ? 'bg-[var(--muted)] font-medium' : 'text-[var(--muted-foreground)] hover:bg-[var(--muted)]/50'}`}
                >
                  {value === 'turn' ? t('This turn') : t('This session')}
                </button>
              ))}
              <button
                type="button"
                aria-label={t('Close')}
                onClick={() => {
                  setOpen(false)
                  anchor.current?.focus()
                }}
                className="ml-1 rounded p-1 text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
              >
                <X size={13} />
              </button>
            </div>
            <div className="mb-2 flex items-baseline justify-between border-b border-[var(--border)] pb-2">
              <span className="font-medium">{t('Total tokens')}</span>
              <span className="text-base font-semibold tabular-nums">
                {number(shown.total_tokens)}
              </span>
            </div>
            <dl className="space-y-1.5">
              {rows.map(([label, value]) => (
                <div key={label} className="flex items-baseline justify-between gap-4">
                  <dt className="text-[11px] leading-4 text-[var(--muted-foreground)]">{label}</dt>
                  <dd className="shrink-0 text-[11px] leading-4 font-medium tabular-nums">
                    {value}
                  </dd>
                </div>
              ))}
            </dl>
          </div>,
          document.body
        )}
    </>
  )
}
