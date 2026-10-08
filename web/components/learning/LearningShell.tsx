'use client'

import Link from 'next/link'
import { ArrowLeft, AlertCircle, RefreshCw } from 'lucide-react'
import type { ReactNode, Ref, UIEventHandler } from 'react'
import { useTranslation } from 'react-i18next'
import { LEARNING_HUB } from '@/lib/learning-routes'
import { FeaturePage, PageHeader } from '@/components/layout/FeaturePage'

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
    <FeaturePage
      scrollRef={scrollRef}
      onScroll={onScroll}
      className={className}
    >
      {back && (
        <Link
          href={LEARNING_HUB}
          className="mb-5 inline-flex items-center gap-1.5 text-xs text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
        >
          <ArrowLeft size={14} />
          {t('Personalized Learning')}
        </Link>
      )}
      <PageHeader title={title} description={subtitle} action={action} meta={scopeChip} />
      {tabs}
      <div className={tabs ? 'mt-6' : ''}>{children}</div>
    </FeaturePage>
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
