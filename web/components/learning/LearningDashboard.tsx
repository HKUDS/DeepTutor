'use client'

import { pageGridClass } from '@/components/layout/FeaturePage'
import Link from 'next/link'
import { useState } from 'react'
import { BookOpen, Route } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useLearningIndex } from '@/hooks/useLearningIndex'
import { LearningCreateMenu } from './LearningCreateMenu'
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
  allLearningActivity,
  type LearningKind,
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
  const { sources, failed, loading, retry } = useLearningIndex()
  const [kind, setKind] = useState<LearningKind | 'all'>('all')
  const [query, setQuery] = useState('')
  const [limit, setLimit] = useState(24)

  const selectedSurface = LEARNING_SURFACES.find(surface => surface.kind === kind)
  const todos = learningTodos(sources)
  const all = allLearningActivity(sources)
  const recent = all.filter(item => (kind === 'all' || item.kind === kind || (kind === 'reading' && item.kind === 'watching')) && item.title.toLocaleLowerCase().includes(query.toLocaleLowerCase()))
  return (
    <LearningShell
      back={false}
      title={t('navigation.learning')}
      subtitle={t('navigation.learningDescription')}
      action={<LearningCreateMenu />}
    >
      <div className="mb-6 flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap gap-1" role="group" aria-label={t('navigation.learningFilter')}>
          {[{ kind: 'all', title: 'navigation.allLearning' }, ...LEARNING_SURFACES].map(surface => <button key={surface.kind} type="button" aria-pressed={kind === surface.kind} onClick={() => { setKind(surface.kind as LearningKind | 'all'); setLimit(24) }} className={`rounded-full px-3 py-1.5 text-xs transition-colors ${kind === surface.kind ? 'bg-muted text-foreground' : 'text-muted-foreground hover:bg-muted/60'}`}>{t(surface.title)}</button>)}
        </div>
        <input aria-label={t('navigation.searchLearning')} placeholder={t('navigation.searchLearning')} value={query} onChange={event => { setQuery(event.target.value); setLimit(24) }} className="ml-auto h-9 rounded-lg border border-border bg-transparent px-3 text-xs outline-none focus:border-ring" />
      </div>
      {selectedSurface && <Link href={scopedUrl(selectedSurface.href)} prefetch={false} className="mb-5 inline-flex items-center gap-2 text-sm text-muted-foreground transition-colors hover:text-foreground">{t('Open')} {t(selectedSurface.title)} <span aria-hidden>↗</span></Link>}
      {failed.length > 0 && (
        <LearningErrorState
          message={t('Some learning activity could not be loaded: {{sources}}.', {
            sources: LEARNING_SURFACES.filter(surface => failed.includes(surface.kind))
              .map(surface => t(surface.title))
              .join(t('source list separator')),
          })}
          onRetry={retry}
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
              <div className={pageGridClass(2)}>
                {todos.reviews.map(topic => (
                  <LearningCard
                    key={`${topic.content_workspace_id}:${topic.path_id}`}
                    href={scopedUrl(masterySessionRoute(topic.path_id, 'review', topic.content_workspace_id || ''), topic.content_workspace_id || '')}
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
                {t('navigation.learningRecords')}
              </h2>
              <div className={pageGridClass(2)}>
                {recent.slice(0, limit).map(item => {
                  const surface = learningSurface(item.kind)
                  return (
                    <LearningCard
                      key={item.key}
                      href={item.href}
                      title={item.title}
                      updatedAt={item.updatedAt}
                      progress={item.progress}
                      subtitle={t(surface.title)}
                      icon={<surface.icon size={19} />}
                    />
                  )
                })}
              </div>
            </section>
          )}
          {recent.length > limit && <button className="mt-5 rounded-lg border border-border px-4 py-2 text-sm" onClick={() => setLimit(value => value + 24)}>{t('Show more')}</button>}
          {!all.length && failed.length === 0 && <LearningWays />}
          {!recent.length && failed.length === 0 && (
            <LearningEmptyState
              title={t(all.length ? 'navigation.noResults' : 'Your next learning journey starts here')}
              description={t('Choose a book, a topic, a collection or a video to begin.')}
            />
          )}
        </>
      )}
    </LearningShell>
  )
}
