'use client'

import Markdown from '@/components/common/MarkdownRenderer'
import { practiceMarkdown } from '@/lib/practice-content'
import { randomUuid } from '@/lib/random-uuid'
import { WorkspaceLabel } from '../LibraryWorkspace'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ArrowLeft, CheckCircle2, Loader2 } from 'lucide-react'
import {
  checkPracticeAnswer,
  getPracticeQuestion,
  PracticeRequestError,
  savePracticeReview,
  type PracticeQuestion,
  type PracticeRef,
  type PracticeRating,
} from '@/lib/practice-api'

const RATINGS: { value: PracticeRating; label: string; description: string }[] = [
  { value: 'again', label: 'Again', description: 'Practice again this round' },
  { value: 'hard', label: 'Hard', description: 'I needed a hint' },
  { value: 'good', label: 'Mastered', description: 'Review in a few days' },
  { value: 'easy', label: 'Easy', description: 'I knew it confidently' },
]

export function PracticeSession({
  ids,
  questions,
  onClose,
}: {
  ids?: number[]
  questions?: PracticeRef[]
  onClose: () => void
}) {
  const [queue, setQueue] = useState<PracticeRef[]>(
    () => questions ?? (ids ?? []).map(id => ({ id }))
  )
  const [total] = useState(queue.length)
  const [skipped, setSkipped] = useState(0)
  const { t } = useTranslation()
  const [index, setIndex] = useState(0)
  const [saved, setSaved] = useState(0)
  const [saving, setSaving] = useState(false)
  const [nextDue, setNextDue] = useState<number | null>(null)
  const dueDates = useRef(new Map<string, number>())
  const complete = index >= queue.length
  return (
    <section className="mx-auto max-w-3xl">
      <div className="mb-5 flex items-center justify-between gap-3">
        <button
          type="button"
          onClick={onClose}
          disabled={saving}
          className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft size={15} />
          {t('Back to practice')}
        </button>
        <p className="text-xs text-muted-foreground" aria-live="polite">
          {t('{{count}} remaining', { count: total - saved - skipped })}
        </p>
      </div>
      <progress
        max={total || 1}
        value={saved}
        aria-label={t('Practice progress')}
        className="mb-6 h-1.5 w-full accent-primary"
      />
      {complete ? (
        <div className="rounded-2xl border border-border bg-card px-6 py-12 text-center">
          <CheckCircle2 className="mx-auto mb-4 text-emerald-600" size={32} />
          <h2 className="font-serif text-2xl font-semibold">{t('Practice complete')}</h2>
          <p className="mt-3 text-sm text-muted-foreground">
            {t('{{count}} reviews saved. Your next review dates have been updated.', {
              count: saved,
            })}
          </p>
          {skipped > 0 && (
            <p className="mt-2 text-sm text-muted-foreground">
              {t('{{count}} skipped questions remain due.', { count: skipped })}
            </p>
          )}
          {nextDue && (
            <p className="mt-2 text-xs text-muted-foreground">
              {t('Next review: {{date}}', { date: new Date(nextDue * 1000).toLocaleDateString() })}
            </p>
          )}
          <button
            type="button"
            onClick={onClose}
            className="mt-6 rounded-xl bg-primary px-5 py-2.5 text-sm text-primary-foreground"
          >
            {t('Back to practice')}
          </button>
        </div>
      ) : (
        <PracticeTurn
          key={`${index}:${queue[index].content_workspace_id}:${queue[index].id}`}
          id={queue[index].id}
          workspaceId={queue[index].content_workspace_id}
          workspaceName={queue[index].content_workspace_name}
          onBusy={setSaving}
          onSaved={(due, rating) => {
            if (rating === 'again') setQueue(current => [...current, current[index]])
            else setSaved(value => value + 1)
            if (due !== null) {
              dueDates.current.set(
                JSON.stringify([queue[index].content_workspace_id, queue[index].id]),
                due
              )
              setNextDue(Math.min(...dueDates.current.values()))
            }
            setIndex(value => value + 1)
          }}
          onSkip={() => {
            setSkipped(value => value + 1)
            setIndex(value => value + 1)
          }}
        />
      )}
    </section>
  )
}

function PracticeTurn({
  id,
  workspaceId,
  workspaceName,
  onSaved,
  onSkip,
  onBusy,
}: {
  id: number
  workspaceId?: string
  workspaceName?: string
  onSaved: (due: number | null, rating: PracticeRating) => void
  onSkip: () => void
  onBusy: (busy: boolean) => void
}) {
  const { t } = useTranslation()
  const [question, setQuestion] = useState<PracticeQuestion | null>(null)
  const [answer, setAnswer] = useState('')
  const [revealed, setRevealed] = useState(false)
  const [correct, setCorrect] = useState<boolean | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [conflict, setConflict] = useState(false)
  const [reload, setReload] = useState(0)
  const pending = useRef(false)
  const submission = useRef<{
    request_id: string
    version: number
    rating: PracticeRating
    answer: string
    self_report?: boolean
  } | null>(null)
  useEffect(() => {
    let active = true
    void getPracticeQuestion(id, workspaceId)
      .then(result => {
        if (active) setQuestion(result)
      })
      .catch(err => {
        if (active) setError(String(err.message || err))
      })
    return () => {
      active = false
    }
  }, [id, reload, workspaceId])
  async function reveal() {
    if (pending.current || !question) return
    pending.current = true
    setBusy(true)
    onBusy(true)
    setError('')
    try {
      const verdict = await checkPracticeAnswer(id, answer, workspaceId)
      setCorrect(verdict.correct)
      setRevealed(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      pending.current = false
      setBusy(false)
      onBusy(false)
    }
  }
  async function rate(rating: PracticeRating, selfReport = false) {
    if (pending.current || !question || conflict) return
    pending.current = true
    setBusy(true)
    onBusy(true)
    setError('')
    // Retrying a lost response must reuse its ID and exact payload.
    submission.current ??= {
      request_id: randomUuid(),
      version: question.state.version,
      rating,
      answer,
      self_report: selfReport,
    }
    try {
      const result = await savePracticeReview(id, submission.current, workspaceId)
      onSaved(result.due_at, result.rating)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      if (err instanceof PracticeRequestError && err.status === 409) setConflict(true)
    } finally {
      pending.current = false
      setBusy(false)
      onBusy(false)
    }
  }
  function reset() {
    setQuestion(null)
    setAnswer('')
    setRevealed(false)
    setCorrect(null)
    setError('')
    setConflict(false)
    submission.current = null
    setReload(value => value + 1)
  }
  const entry = question?.entry
  const multi =
    entry?.question_type === 'multi_choice' || entry?.question_type === 'multiple_select'
  const choices = Object.entries(entry?.options || {})
  return (
    <div className="rounded-2xl border border-border bg-card p-5 sm:p-8">
      {error && (
        <div role="alert" className="mb-4 rounded-lg bg-destructive/5 p-3 text-sm text-destructive">
          <p>{error}</p>
          {(conflict || !entry) && (
            <button type="button" onClick={reset} className="mt-2 underline">
              {t('Reload question')}
            </button>
          )}
        </div>
      )}
      {!entry ? (
        <p role="status" className="py-8 text-sm text-muted-foreground">
          {t('Loading…')}
        </p>
      ) : (
        <>
          <div className="mb-4 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span>{entry.material_title || t('Practice')}</span>
            {workspaceId !== undefined && (
              <>
                <span aria-hidden="true">·</span>
                <WorkspaceLabel
                  row={{ content_workspace_id: workspaceId, content_workspace_name: workspaceName }}
                />
              </>
            )}
            {entry.categories?.map(tag => (
              <span key={tag.id} className="rounded-full bg-muted px-2 py-1">
                {tag.name}
              </span>
            ))}
          </div>
          <div className="text-base leading-relaxed">
            <Markdown
              content={practiceMarkdown(entry.question)}
              allowHtml={false}
              className="[overflow-wrap:anywhere] [&_pre]:max-w-full [&_pre]:overflow-x-auto"
            />
          </div>
          {multi && (
            <p className="mt-3 text-xs text-muted-foreground">{t('Select all correct answers')}</p>
          )}
          {choices.length > 0 ? (
            <fieldset disabled={revealed || busy} className="mt-6 grid gap-2">
              <legend className="sr-only">{t('Your answer')}</legend>
              {choices.map(([key, text]) => {
                const selected = multi ? answer.split(',').includes(key) : answer === key
                return (
                  <label
                    key={key}
                    className={`flex cursor-pointer items-start gap-3 rounded-xl border p-3 text-sm ${selected ? 'border-primary bg-primary/5' : 'border-border hover:bg-muted/40'}`}
                  >
                    <input
                      type={multi ? 'checkbox' : 'radio'}
                      name={`practice-${id}`}
                      checked={selected}
                      value={key}
                      onChange={() =>
                        setAnswer(
                          multi
                            ? (selected
                                ? answer.split(',').filter(value => value !== key)
                                : [...answer.split(',').filter(Boolean), key]
                              )
                                .sort()
                                .join(',')
                            : key
                        )
                      }
                      className="mt-1 accent-primary"
                    />
                    <span className="font-semibold">{key}</span>
                    <div className="min-w-0">
                      <Markdown content={practiceMarkdown(text)} allowHtml={false} />
                    </div>
                  </label>
                )
              })}
            </fieldset>
          ) : (
            <label className="mt-6 block text-sm font-medium">
              {t('Your answer')}
              <textarea
                value={answer}
                onChange={event => setAnswer(event.target.value)}
                disabled={revealed || busy}
                maxLength={20000}
                rows={5}
                placeholder={t('Try recalling the answer before revealing it.')}
                className="mt-2 block w-full resize-y rounded-xl border border-border bg-background p-3 font-normal outline-none focus:border-primary"
              />
            </label>
          )}
          {!revealed ? (
            <div className="mt-5 flex flex-wrap items-center gap-3">
              <button
                type="button"
                disabled={busy}
                onClick={() => void reveal()}
                className="rounded-xl bg-primary px-4 py-2.5 text-sm text-primary-foreground disabled:opacity-50"
              >
                {busy ? t('Checking…') : t('Check and reveal answer')}
              </button>
              <button
                type="button"
                disabled={busy || conflict}
                onClick={() => void rate('good', true)}
                className="rounded-xl border border-border px-4 py-2.5 text-sm hover:bg-muted"
              >
                {t('I have mastered this')}
              </button>
              <button
                type="button"
                onClick={onSkip}
                disabled={busy}
                className="text-sm text-muted-foreground hover:underline"
              >
                {t('Skip for now')}
              </button>
            </div>
          ) : (
            <div className="mt-6 space-y-5">
              <div className="rounded-xl bg-muted/50 p-4">
                <p className="mb-3 text-sm font-semibold">
                  {correct === null
                    ? t('Compare your answer with the reference')
                    : correct
                      ? t('Correct')
                      : t('Needs another try')}
                </p>
                <div className="text-sm">
                  <Markdown
                    content={
                      entry.correct_answer ||
                      t(
                        'No reference answer was saved. Use the original source to check your work.'
                      )
                    }
                  />
                  {entry.explanation && (
                    <div className="mt-3 border-t border-border pt-3">
                      <Markdown content={entry.explanation} />
                    </div>
                  )}
                </div>
              </div>
              {correct !== null ? (
                <div className="flex flex-wrap items-center justify-between gap-4">
                  <p className="text-xs text-muted-foreground">
                    {correct
                      ? t(
                          'Mastered questions leave this round and return when your next review is due.'
                        )
                      : t('Practice again this round')}
                  </p>
                  <button
                    type="button"
                    disabled={busy || conflict}
                    onClick={() => void rate(correct ? 'good' : 'again')}
                    className="rounded-xl bg-primary px-5 py-2.5 text-sm font-medium text-primary-foreground disabled:opacity-40"
                  >
                    {correct ? t('Mastered · Next question') : t('Practice again')}
                  </button>
                </div>
              ) : (
                <div>
                  <h3 className="text-sm font-medium">{t('How well did you remember?')}</h3>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {t(
                      'Mastered questions leave this round and return when your next review is due.'
                    )}
                  </p>
                  <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
                    {RATINGS.map(rating => (
                      <button
                        key={rating.value}
                        aria-label={`${t(rating.label)} ${t(rating.description)}`}
                        type="button"
                        disabled={
                          busy ||
                          conflict ||
                          (!!submission.current && submission.current.rating !== rating.value)
                        }
                        onClick={() => void rate(rating.value)}
                        className="rounded-xl border border-border p-3 text-left transition hover:border-primary hover:bg-primary/5 disabled:cursor-not-allowed disabled:opacity-35"
                      >
                        <span className="block text-sm font-semibold">{t(rating.label)}</span>
                        <span className="mt-1 block text-xs text-muted-foreground">
                          {t(rating.description)}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              )}
              {busy && (
                <p role="status" className="flex items-center gap-2 text-sm">
                  <Loader2 size={15} className="animate-spin" />
                  {t('Saving review…')}
                </p>
              )}
            </div>
          )}
        </>
      )}
    </div>
  )
}
