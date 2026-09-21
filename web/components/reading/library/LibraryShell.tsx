'use client'

import { scopedUrl } from "@/lib/workspace-scope";
import { LearningShell } from '@/components/learning/LearningShell'

import { READING_HOME, READING_MATERIALS } from '@/lib/learning-routes'

import Link from 'next/link'
import { Plus } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { learningLibrary } from '@/lib/learning-library'

/**
 * Header shared by the two reading views. Immersive Reading has exactly two
 * places to be — the collections you read in, and the library of everything
 * you have uploaded — so they sit under one title as two tabs rather than
 * behind a second sidebar.
 */
export function LibraryShell({
  view,
  collectionCount,
  materialCount,
  actionLabel,
  onAction,
  scopeChip,
  children,
}: {
  view: 'collections' | 'materials'
  collectionCount?: number
  materialCount?: number
  actionLabel: string
  onAction: () => void
  /** Rendered beside the title when this visit belongs to one course. */
  scopeChip?: ReactNode
  children: ReactNode
}) {
  const { t } = useTranslation()
  // Each view knows its own count; the other one is fetched once so the tabs
  // never show a blank where a number belongs.
  const [otherCount, setOtherCount] = useState<number | null>(null)

  useEffect(() => {
    let alive = true
    const missing = view === 'collections' ? materialCount : collectionCount
    if (missing !== undefined) return
    void (async () => {
      try {
        const value =
          view === 'collections'
            ? (await learningLibrary('materials')).items.length
            : (await learningLibrary('reading')).items.length
        if (alive) setOtherCount(value)
      } catch {
        // A missing tab count is not worth an error state; the tab still works.
      }
    })()
    return () => {
      alive = false
    }
  }, [collectionCount, materialCount, view])

  const collections =
    collectionCount ?? (view === 'materials' ? (otherCount ?? undefined) : undefined)
  const materials =
    materialCount ?? (view === 'collections' ? (otherCount ?? undefined) : undefined)

  return (
    <LearningShell
      className="reading-v2"
      title={t('Immersive Reading')}
      subtitle={t(
        'Put PDFs, web pages and lectures into one collection and read them with an AI companion that can always point back to the source.'
      )}
      scopeChip={scopeChip}
      action={
        <button
          type="button"
          onClick={onAction}
          className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3 text-[12px] font-semibold text-[var(--primary-foreground)] transition hover:opacity-90"
        >
          <Plus size={14} />
          {actionLabel}
        </button>
      }
      tabs={
        <nav className="mt-5 flex gap-1 border-b border-[var(--border)]">
          <ViewTab
            href={scopedUrl(READING_HOME)}
            label={t('Collections')}
            count={collections}
            active={view === 'collections'}
          />
          <ViewTab
            href={scopedUrl(READING_MATERIALS)}
            label={t('Material library')}
            count={materials}
            active={view === 'materials'}
          />
        </nav>
      }
    >
      {children}
    </LearningShell>
  )
}

function ViewTab({
  href,
  label,
  count,
  active,
}: {
  href: string
  label: string
  count?: number
  active: boolean
}) {
  return (
    <Link
      href={href}
      aria-current={active ? 'page' : undefined}
      className={`-mb-px flex items-center gap-1.5 border-b-2 px-3 pb-2.5 pt-2 text-[12.5px] transition ${
        active
          ? 'border-[var(--primary)] font-semibold text-[var(--foreground)]'
          : 'border-transparent text-[var(--muted-foreground)] hover:text-[var(--foreground)]'
      }`}
    >
      {label}
      {typeof count === 'number' && (
        <span className="text-[10.5px] tabular-nums text-[var(--muted-foreground)]">{count}</span>
      )}
    </Link>
  )
}
