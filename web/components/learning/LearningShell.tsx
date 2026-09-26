'use client'

import Link from 'next/link'
import { ArrowLeft, AlertCircle, RefreshCw } from 'lucide-react'
import type { ReactNode, Ref, UIEventHandler } from 'react'
import { useTranslation } from 'react-i18next'
import { LEARNING_HUB } from '@/lib/learning-routes'

/** The same page rhythm for the hub and each library; readers keep their full-screen layouts. */
export function LearningShell({
  title,
  subtitle,
  action,
  scopeChip,
  tabs,
  children,
  back = true,
  className = '',
  scrollRef,
  onScroll,
}: {
  title: ReactNode
  subtitle: ReactNode
  action?: ReactNode
  scopeChip?: ReactNode
  tabs?: ReactNode
  children: ReactNode
  back?: boolean
  className?: string
  scrollRef?: Ref<HTMLElement>
  onScroll?: UIEventHandler<HTMLElement>
}) {
  const { t } = useTranslation()
  return (
    <section
      ref={scrollRef}
      onScroll={onScroll}
      className={`h-full min-h-0 w-full overflow-y-auto bg-[var(--background)] text-[var(--foreground)] ${className}`}
    >
      <div className="mx-auto w-full max-w-[1180px] px-6 py-7 md:px-9 lg:py-9">
        {back && (
          <Link
            href={LEARNING_HUB}
            className="mb-5 inline-flex items-center gap-1.5 text-xs text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
          >
            <ArrowLeft size={14} />
            {t('Personalized Learning')}
          </Link>
        )}
        <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2.5">
              <h1 className="font-serif text-[27px] font-semibold tracking-[-0.02em] md:text-[30px]">
                {title}
              </h1>
              {scopeChip}
            </div>
            <p className="mt-1.5 max-w-2xl text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
              {subtitle}
            </p>
          </div>
          {action && <div className="flex shrink-0 flex-wrap items-center gap-2">{action}</div>}
        </header>
        {tabs}
        <div className="mt-6">{children}</div>
      </div>
    </section>
  )
}

export function LearningEmptyState({
  title,
  description,
  action,
  icon,
}: {
  title: ReactNode
  description?: ReactNode
  action?: ReactNode
  icon?: ReactNode
}) {
  return (
    <div className="my-6 rounded-xl border border-dashed border-[var(--border)] px-6 py-12 text-center">
      {icon && (
        <div className="mb-4 flex justify-center text-[var(--muted-foreground)]">{icon}</div>
      )}
      <h2 className="font-serif text-lg font-semibold">{title}</h2>
      {description && (
        <p className="mx-auto mt-2 max-w-lg text-sm leading-relaxed text-[var(--muted-foreground)]">
          {description}
        </p>
      )}
      {action && <div className="mt-5">{action}</div>}
    </div>
  )
}

export function LearningErrorState({
  message,
  onRetry,
}: {
  message: ReactNode
  onRetry?: () => void
}) {
  const { t } = useTranslation()
  return (
    <div
      role="alert"
      className="my-4 flex flex-wrap items-center gap-3 rounded-xl border border-[var(--destructive)]/20 bg-[var(--destructive)]/5 p-4 text-sm"
    >
      <AlertCircle size={16} className="shrink-0 text-[var(--destructive)]" />
      <span className="min-w-0 flex-1">{message}</span>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="inline-flex items-center gap-1.5 font-medium hover:underline"
        >
          <RefreshCw size={14} />
          {t('Retry')}
        </button>
      )}
    </div>
  )
}

export function LearningSkeleton({ count = 3 }: { count?: number }) {
  const { t } = useTranslation()
  return (
    <div role="status" aria-label={t('Loading…')} className="my-6 grid gap-3" aria-busy="true">
      {Array.from({ length: count }, (_, index) => (
        <div
          key={index}
          className="h-20 animate-pulse rounded-xl border border-[var(--border)] bg-[var(--muted)]/60 motion-reduce:animate-none"
        />
      ))}
    </div>
  )
}
