'use client'

import Link from 'next/link'
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { ProgressRing } from '@/components/space/learning/ProgressRing'
import { formatRelativeTime } from '@/lib/relative-time'

interface LearningCardContentProps {
  title: string
  subtitle?: ReactNode
  icon: ReactNode
  updatedAt?: number
  progress?: number
}

/** Shared identity row, also used inside libraries with their own menus or video thumbnails. */
export function LearningCardContent({
  title,
  subtitle,
  icon,
  updatedAt,
  progress,
}: LearningCardContentProps) {
  const { i18n } = useTranslation()
  return (
    <>
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[var(--muted)] text-[var(--muted-foreground)]">
        {icon}
      </span>
      <div className="min-w-0 flex-1">
        <h3 className="truncate text-sm font-medium">{title}</h3>
        {subtitle && (
          <div className="mt-1 line-clamp-2 text-xs text-[var(--muted-foreground)]">{subtitle}</div>
        )}
      </div>
      <div className="flex shrink-0 flex-col items-end gap-2">
        {progress !== undefined && <ProgressRing value={progress} />}
        {updatedAt !== undefined && Number.isFinite(updatedAt) && (
          <time
            dateTime={new Date(updatedAt * 1000).toISOString()}
            className="text-[11px] text-[var(--muted-foreground)]"
          >
            {formatRelativeTime(updatedAt, i18n.language)}
          </time>
        )}
      </div>
    </>
  )
}

/** User-authored titles are rendered verbatim; callers translate only product copy. */
export function LearningCard({
  href,
  onClick,
  ...content
}: LearningCardContentProps & { href: string; onClick?: () => void }) {
  return (
    <Link
      href={href}
      onClick={onClick}
      className="group flex min-w-0 items-center gap-3 rounded-xl bg-muted/45 p-4 transition hover:bg-muted/80 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
    >
      <LearningCardContent {...content} />
    </Link>
  )
}
