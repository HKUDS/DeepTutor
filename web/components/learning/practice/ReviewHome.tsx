'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { useTranslation } from 'react-i18next'
import { ArrowRight, Check, ChevronDown, FileUp, Loader2, Library } from 'lucide-react'
import {
  getPracticeQueue,
  getPracticeSummary,
  type PracticeRef,
  type PracticeSummary,
} from '@/lib/practice-api'
import { LearningShell, LearningErrorState } from '../LearningShell'
import { useCreateRequest } from '../create-request'
import { PracticeSession } from './PracticeSession'
import { PracticeImport } from './PracticeImport'
import { PracticeInsights } from './PracticeInsights'

export function ReviewHome() {
  const { t } = useTranslation()
  const [summary, setSummary] = useState<PracticeSummary | null>(null)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  const [session, setSession] = useState<PracticeRef[] | null>(null)
  const [starting, setStarting] = useState(false)
  const [importing, setImporting] = useState(false)
  const [notice, setNotice] = useState('')
  const sequence = useRef(0)
  useCreateRequest(() => setImporting(true))
  const refresh = useCallback(async () => {
    const request = ++sequence.current
    try {
      const next = await getPracticeSummary()
      if (request !== sequence.current) return
      setSummary(next)
      setError('')
    } catch (err) {
      if (request === sequence.current) setError(err instanceof Error ? err.message : String(err))
    }
  }, [])
  useEffect(() => {
    void refresh()
    const timer = window.setInterval(() => void refresh(), 60000)
    window.addEventListener('focus', refresh)
    return () => {
      // eslint-disable-next-line react-hooks/exhaustive-deps
      sequence.current++
      window.clearInterval(timer)
      window.removeEventListener('focus', refresh)
    }
  }, [refresh])
  const start = async () => {
    if (starting) return
    setStarting(true)
    try {
      const rows = await getPracticeQueue()
      if (rows.length)
        setSession(
          rows.map(row => ({
            id: row.entry.id,
            content_workspace_id: row.content_workspace_id,
          }))
        )
      else {
        setNotice(t('You are caught up. Come back when your next reviews are due.'))
        void refresh()
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setStarting(false)
    }
  }
  const completed = () => {
    setSession(null)
    setRevision(value => value + 1)
    void refresh()
  }
  return (
    <LearningShell
      title={t('Practice')}
      subtitle={t('A little recall today. Remember more tomorrow.')}
      action={
        !session && (
          <button
            type="button"
            onClick={() => setImporting(true)}
            className="inline-flex h-9 items-center gap-2 rounded-lg border border-border px-3 text-sm hover:bg-muted"
          >
            <FileUp size={15} />
            {t('Import questions')}
          </button>
        )
      }
    >
      {session ? (
        <div className="mt-8">
          <PracticeSession questions={session} onClose={completed} />
        </div>
      ) : (
        <div className="mt-7 space-y-6">
          {error && <LearningErrorState message={error} onRetry={() => void refresh()} />}
          {notice && (
            <p role="status" className="flex items-center gap-2 text-sm text-emerald-600">
              <Check size={16} />
              {notice}
            </p>
          )}
          {importing && (
            <PracticeImport
              initialTarget="bank"
              onClose={() => setImporting(false)}
              onImported={message => {
                setNotice(message)
                setImporting(false)
                setRevision(value => value + 1)
                void refresh()
              }}
            />
          )}
          <section
            className="overflow-hidden rounded-2xl border border-border bg-card"
            aria-labelledby="review-today"
          >
            <div className="flex flex-wrap items-center justify-between gap-4 border-b border-border px-6 py-4">
              <h2 id="review-today" className="text-sm font-semibold">
                {t("Today's review")}
              </h2>
            </div>
            <div className="flex flex-col justify-between gap-6 px-6 py-8 sm:flex-row sm:items-center sm:px-8">
              <div>
                <div className="flex items-baseline gap-3">
                  <span className="text-5xl font-semibold tracking-tight tabular-nums">
                    {summary?.due ?? '—'}
                  </span>
                  <span className="text-sm text-muted-foreground">{t('Ready to review')}</span>
                </div>
                <p className="mt-4 max-w-md text-sm leading-6 text-muted-foreground">
                  {t(
                    'Mastered questions leave this round and return when your next review is due.'
                  )}
                </p>
              </div>
              <button
                type="button"
                onClick={() => void start()}
                disabled={starting || !summary?.due}
                className="inline-flex h-11 shrink-0 items-center justify-center gap-2 rounded-xl bg-primary px-6 text-sm font-medium text-primary-foreground transition hover:opacity-90 disabled:opacity-40"
              >
                {starting ? (
                  <Loader2 size={16} className="animate-spin" />
                ) : (
                  <ArrowRight size={16} />
                )}
                {t("Start today's review")}
              </button>
            </div>
            <div className="grid grid-cols-3 divide-x divide-border border-t border-border bg-muted/20 px-2 py-4">
              {[
                ['Reviewed today', summary?.reviewed_today],
                ['Scheduled for later', summary ? summary.total - summary.due : undefined],
                ['Question Bank', summary?.total],
              ].map(([label, count]) => (
                <div key={String(label)} className="px-4 text-center">
                  <span className="block text-lg font-medium tabular-nums">{count ?? '—'}</span>
                  <span className="text-xs text-muted-foreground">{t(String(label))}</span>
                </div>
              ))}
            </div>
          </section>
          <div className="flex flex-wrap items-center justify-between gap-3 px-1 text-xs text-muted-foreground">
            <p>{t('Recall first, then check. Forgotten questions come back in this round.')}</p>
            <Link
              href="/space/questions"
              className="inline-flex items-center gap-1.5 text-foreground hover:underline"
            >
              <Library size={14} />
              {t('Manage question bank')}
              <ArrowRight size={13} />
            </Link>
          </div>
          <details className="group rounded-xl border border-border">
            <summary className="flex cursor-pointer list-none items-center justify-between px-5 py-4 text-sm font-medium">
              {t('Practice analytics')}
              <ChevronDown size={16} className="transition group-open:rotate-180" />
            </summary>
            <div className="px-4 pb-4">
              <PracticeInsights revision={revision} />
            </div>
          </details>
        </div>
      )}
    </LearningShell>
  )
}
