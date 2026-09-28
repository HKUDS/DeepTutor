'use client'

import {
  LearningShell,
  LearningEmptyState,
  LearningErrorState,
  LearningSkeleton,
} from '@/components/learning/LearningShell'

import Link from 'next/link'
import { useTranslation } from 'react-i18next'
import { ArrowRight, Compass, Plus, Sparkles } from 'lucide-react'

import type { MasteryTopic } from '@/lib/learning-api'
import {
  MASTERY_OPENING_SCOPE,
  masteryOpeningMessage,
  masterySessionRoute,
} from '@/lib/mastery-mode'
import { setPendingPrompt } from '@/lib/pending-prompt'

import { useLibraryFilter } from '@/components/learning/LibraryWorkspace'
import { libraryItemKey } from '@/lib/learning-library'
import { topicDisplayName } from './format'
import { TopicMapCard } from './TopicMapCard'

export function TopicAtlas({
  topics: allTopics,
  loading,
  error,
  onCreate,
  onRetry,
  scopeChip,
}: {
  topics: MasteryTopic[]
  loading: boolean
  error: string | null
  onCreate: (trigger: HTMLButtonElement) => void
  onRetry: () => void
  /** Rendered beside the eyebrow when this visit belongs to one course. */
  scopeChip?: React.ReactNode
}) {
  const { t } = useTranslation()
  const { rows: topics, control } = useLibraryFilter(allTopics)
  const activeTopics = topics.filter(topic => topic.metadata.status === 'active')
  const dueCount = activeTopics.reduce(
    (count, topic) => count + topic.reviews.filter(review => review.due).length,
    0
  )
  const dueTopics = activeTopics.filter(topic => topic.reviews.some(review => review.due))
  const firstDueTopic = dueTopics[0]

  return (
    <LearningShell
      className="mastery-shell"
      title={t('Mastery Path')}
      subtitle={t(
        "Work through each topic's knowledge points, then pick up any session where you left off."
      )}
      scopeChip={scopeChip}
      action={
        <button
          type="button"
          onClick={event => onCreate(event.currentTarget)}
          className="inline-flex h-9 shrink-0 items-center justify-center gap-2 rounded-xl bg-[var(--primary)] px-5 text-sm font-medium text-[var(--primary-foreground)]  transition hover:opacity-90 focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2"
        >
          <Plus className="h-4 w-4" />
          {t('New topic')}
        </button>
      }
    >
      <div className="mt-6 flex items-center justify-between border-b border-border pb-4">{control}</div>
      {dueCount > 0 && (
        <section className="mt-8 flex flex-col gap-3 rounded-lg border border-[var(--border)] bg-[var(--muted-foreground)]/[0.07] px-4 py-3.5 text-sm text-[var(--foreground)] sm:flex-row sm:items-center">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[var(--muted-foreground)]/15 text-[var(--muted-foreground)]">
            <Sparkles className="h-4 w-4" />
          </span>
          <div className="min-w-0 flex-1">
            <div className="font-medium">
              {t('{{beacons}} reviews are due across {{count}} topics', {
                beacons: dueCount,
                count: dueTopics.length,
              })}
            </div>
            <div className="mt-0.5 text-xs text-[var(--muted-foreground)]">
              {t('Open their maps for a short review without losing your main route.')}
            </div>
          </div>
          {firstDueTopic && (
            <Link
              // Straight into a review session: "start review" that lands on
              // a dashboard makes the learner find the door twice, and a
              // review sitting is a different kind of conversation from the
              // study one the dashboard's own button opens.
              onClick={() =>
                setPendingPrompt(
                  masteryOpeningMessage('review', t, {
                    dueTitles: firstDueTopic.reviews
                      .filter(review => review.due)
                      .slice(0, 5)
                      .map(review => review.knowledge_point_name),
                  }),
                  MASTERY_OPENING_SCOPE
                )
              }
              href={masterySessionRoute(firstDueTopic.path_id, 'review', '', firstDueTopic.content_workspace_id ?? '')}
              className="inline-flex h-9 shrink-0 items-center justify-center gap-1.5 rounded-xl bg-[var(--primary)] px-3.5 text-xs font-semibold text-white transition hover:opacity-90 focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)] focus-visible:ring-offset-2 "
            >
              {t('Start review')}: {topicDisplayName(firstDueTopic, t)}
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          )}
        </section>
      )}

      {error && <LearningErrorState message={error} onRetry={onRetry} />}
      {loading ? (
        <LearningSkeleton count={6} />
      ) : activeTopics.length > 0 ? (
        <section
          aria-label={t('Active learning topics')}
          className="mt-9 grid gap-6 md:grid-cols-2 xl:grid-cols-3"
        >
          {activeTopics.map(topic => (
            <TopicMapCard key={libraryItemKey(topic, topic.path_id)} topic={topic} />
          ))}
        </section>
      ) : !error ? (
        <LearningEmptyState
          icon={<Compass size={28} />}
          title={t('Your atlas is still uncharted')}
          description={t(
            'Tell DeepTutor what you want to learn, mix in your books, notes, and knowledge bases, and it will draft the first outline.'
          )}
          action={
            <button
              type="button"
              onClick={event => onCreate(event.currentTarget)}
              className="inline-flex h-9 items-center gap-2 rounded-lg bg-[var(--primary)] px-4 text-sm text-[var(--primary-foreground)]"
            >
              <Plus size={14} />
              {t('Chart the first map')}
            </button>
          }
        />
      ) : null}
    </LearningShell>
  )
}
