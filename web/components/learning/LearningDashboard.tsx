'use client'

import { useEffect, useState } from 'react'
import { BookOpen, Route } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { apiFetch, apiUrl } from '@/lib/api'
import { scopedUrl } from '@/lib/workspace-scope'
import { bookRoute } from '@/lib/learning-routes'
import {
  masterySessionRoute,
  masteryOpeningMessage,
  MASTERY_OPENING_SCOPE,
} from '@/lib/mastery-mode'
import { setPendingPrompt } from '@/lib/pending-prompt'
import {
  learningTodos,
  recentLearningActivity,
  type LearningKind,
  type LearningSources,
} from '@/lib/learning-dashboard'
import {
  LearningShell,
  LearningEmptyState,
  LearningErrorState,
  LearningSkeleton,
} from './LearningShell'
import { LearningCard } from './LearningCard'
import { LearningWays } from './LearningWays'
import { LEARNING_SURFACES, learningSurface } from './surfaces'

export function LearningDashboard() {
  const { t } = useTranslation()
  const [sources, setSources] = useState<LearningSources>({
    books: [],
    mastery: [],
    reading: [],
    watching: [],
  })
  const [failed, setFailed] = useState<LearningKind[]>([])
  const [loading, setLoading] = useState(true)
  const [reload, setReload] = useState(0)

  useEffect(() => {
    let alive = true
    let busy = false
    const refresh = async () => {
      if (busy || document.visibilityState === 'hidden') return
      busy = true
      let failures: LearningKind[] = []
      let result: LearningSources = { books: [], mastery: [], reading: [], watching: [] }
      try {
        const response = await apiFetch(apiUrl(scopedUrl('/api/dashboard/learning-index', '')), { signal: AbortSignal.timeout(20000) })
        if (!response.ok) throw new Error('Learning index unavailable')
        const payload = await response.json() as { sources: LearningSources; failed: LearningKind[] }
        result = payload.sources
        failures = payload.failed
      } catch { failures = ['books', 'mastery', 'reading', 'watching'] }
      const { books, mastery, reading, watching } = result
      if (alive) {
        // Preserve previously loaded content if a refresh fails.
        setSources(previous => ({
          books: failures.includes('books') && !books.length ? previous.books : books,
          mastery: failures.includes('mastery') && !mastery.length ? previous.mastery : mastery,
          reading: failures.includes('reading') && !reading.length ? previous.reading : reading,
          watching: failures.includes('watching') && !watching.length ? previous.watching : watching,
        }))
        setFailed(failures)
        setLoading(false)
      }
      busy = false
    }
    void refresh()
    window.addEventListener('focus', refresh)
    document.addEventListener('visibilitychange', refresh)
    const timer = window.setInterval(refresh, 30_000)
    return () => {
      alive = false
      window.clearInterval(timer)
      window.removeEventListener('focus', refresh)
      document.removeEventListener('visibilitychange', refresh)
    }
  }, [reload])

  const todos = learningTodos(sources)
  const recent = recentLearningActivity(sources)
  return (
    <LearningShell
      back={false}
      title={t('Personalized Learning')}
      subtitle={t('One tutor, your own way to learn.')}
    >
      {/* The ways in lead the page: everything below them assumes you already
          chose one. Each opens its own introduction before it commits you. */}
      <LearningWays />
      {failed.length > 0 && (
        <LearningErrorState
          message={t('Some learning activity could not be loaded: {{sources}}.', {
            sources: LEARNING_SURFACES.filter(surface => surface.kind !== "practice" && failed.includes(surface.kind))
              .map(surface => t(surface.title))
              .join(t('source list separator')),
          })}
          onRetry={() => setReload(value => value + 1)}
        />
      )}
      {loading ? (
        <LearningSkeleton count={4} />
      ) : (
        <>
          {(todos.reviews.length > 0 || todos.books.length > 0) && (
            <section aria-labelledby="learning-todos" className="mb-9">
              <h2 id="learning-todos" className="mb-3 text-[13.5px] font-semibold">
                {t('What needs your attention')}
              </h2>
              <div className="grid gap-3 md:grid-cols-2">
                {todos.reviews.map(topic => (
                  <LearningCard
                    key={`${topic.content_workspace_id}:${topic.path_id}`}
                    href={scopedUrl(masterySessionRoute(topic.path_id, 'review', '', topic.content_workspace_id || ''), topic.content_workspace_id || '')}
                    title={topic.name || topic.metadata.goal}
                    icon={<Route size={19} />}
                    subtitle={t('{{count}} reviews due', {
                      count: topic.reviews.filter(review => review.due).length,
                    })}
                    onClick={() =>
                      setPendingPrompt(
                        masteryOpeningMessage('review', t, {
                          dueTitles: topic.reviews
                            .filter(review => review.due)
                            .slice(0, 5)
                            .map(review => review.knowledge_point_name),
                        }),
                        MASTERY_OPENING_SCOPE
                      )
                    }
                  />
                ))}
                {todos.books.map(book => (
                  <LearningCard
                    key={`${book.content_workspace_id}:${book.id}`}
                    href={scopedUrl(bookRoute(book.id, null, ""), book.content_workspace_id || "")}
                    title={book.title}
                    icon={<BookOpen size={19} />}
                    subtitle={
                      <>
                        {book.status === 'paused' ? t('Paused') : t('Compiling')}
                        {book.status === 'paused' && book.metadata.pause_reason
                          ? ` · ${book.metadata.pause_reason}`
                          : ''}
                      </>
                    }
                  />
                ))}
              </div>
            </section>
          )}
          {recent.length > 0 && (
            <section aria-labelledby="learning-recent">
              <h2 id="learning-recent" className="mb-3 text-[13.5px] font-semibold">
                {t('Recent activity')}
              </h2>
              <div className="grid gap-3 md:grid-cols-2">
                {recent.map(item => {
                  const surface = learningSurface(item.kind)
                  return (
                    <LearningCard
                      key={item.key}
                      href={item.href}
                      title={item.title}
                      updatedAt={item.updatedAt}
                      progress={item.progress}
                      subtitle={<>{t(surface.title)}{item.workspaceName ? ` · ${item.workspaceName}` : ""}</>}
                      icon={<surface.icon size={19} />}
                    />
                  )
                })}
              </div>
            </section>
          )}
          {!recent.length && failed.length === 0 && (
            <LearningEmptyState
              title={t('Your next learning journey starts here')}
              description={t('Choose a book, a topic, a collection or a video to begin.')}
            />
          )}
        </>
      )}
    </LearningShell>
  )
}
