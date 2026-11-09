'use client'
import { useTranslation } from 'react-i18next'
import { OverviewRow, Status, matches } from './NavigationPrimitives'
import { RecordGroups, RecordHeader, RecordTime, useRecordView } from './RecordList'
import { useLayoutEffect, useState, type ReactNode } from 'react'
import Link from 'next/link'
import { usePathname, useSearchParams } from 'next/navigation'
import { ChevronRight, ClipboardList, LayoutGrid, MessageCircle, Plus } from 'lucide-react'
import { learningSurface } from '@/components/learning/surfaces'
import { allLearningActivity, fileLearningSessions, type LearningActivity } from '@/lib/learning-dashboard'
import { isNavigationTargetActive } from '@/lib/navigation'
import { useLearningIndex } from '@/hooks/useLearningIndex'
import { useSidebarDrawer } from '@/components/layout/AppShell'
import { browserStorage } from '@/shared/storage'
import { displaySessionTitle } from '@/lib/session-title'
import type { SessionSummary } from '@/lib/session-api'

const OPEN_KEY = 'deeptutor.navigation.learning.open'

/** The learning conversations of this workspace, and how to draw a few of them. */
export interface LearningSessions {
  rows: readonly SessionSummary[]
  activeSessionId: string | null
  /** The shell's own conversation rows, actions included. */
  render: (rows: SessionSummary[]) => ReactNode
}

type Row =
  | { kind: 'record'; key: string; record: LearningActivity; sessions: SessionSummary[]; time: number }
  | { kind: 'session'; key: string; session: SessionSummary; time: number }

function readOpen(): Record<string, boolean> {
  try {
    return JSON.parse(browserStorage.readRaw('local', OPEN_KEY) ?? '{}') as Record<string, boolean>
  } catch {
    return {}
  }
}

/**
 * Learning records with their conversations underneath: a path, a collection
 * or a book is one entry, and what was said while studying it is filed inside
 * it rather than in a second list beside it.
 */
export function LearningNavigation({
  sessions,
  active = true,
}: {
  sessions?: LearningSessions
  active?: boolean
}) {
  const { t } = useTranslation()
  const { sources, loading, failed, retry } = useLearningIndex(active)
  const view = useRecordView('deeptutor.navigation.learning.sort')
  const pathname = usePathname()
  const query = new URLSearchParams(useSearchParams().toString())
  // A collapsed practice set opens on the question being practised, the same
  // fallback that opens a record on the conversation being read — unless the
  // learner stored a collapse preference for it.
  const practicing = (record: LearningActivity) =>
    (record.children ?? []).some(child => isNavigationTargetActive(child.href, pathname, query))
  const [open, setOpen] = useState<Record<string, boolean>>({})
  useLayoutEffect(() => {
    // Restore which records were left open before paint, without a mismatch.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setOpen(readOpen())
  }, [])
  const { sort } = view
  const at = (session: SessionSummary) => (sort === 'createdAt' ? session.created_at : session.updated_at)
  const placeholder = t('New chat')
  const titleOf = (session: SessionSummary) => displaySessionTitle(session.title, placeholder)
  const records = allLearningActivity(sources)
  const filed = fileLearningSessions(records, sessions?.rows ?? [])
  const rows: Row[] = [
    ...records.map(record => {
      const children = filed.children.get(record.key) ?? []
      // A record is as recent as the latest conversation held in it.
      const time = sort === 'createdAt' ? record.createdAt : Math.max(record.updatedAt, ...children.map(at))
      return { kind: 'record' as const, key: record.key, record, sessions: children, time }
    }),
    ...filed.loose.map(session => ({ kind: 'session' as const, key: session.session_id, session, time: at(session) })),
  ]
    .filter(row =>
      row.kind === 'session'
        ? matches(titleOf(row.session), view.query)
        : matches(`${row.record.title} ${t(learningSurface(row.record.kind).title)}`, view.query) ||
          row.sessions.some(session => matches(titleOf(session), view.query)) ||
          (row.record.children ?? []).some(child => matches(child.title, view.query))
    )
    .sort((a, b) => b.time - a.time || a.key.localeCompare(b.key))
  const toggle = (key: string, next: boolean) =>
    setOpen(previous => {
      const value = { ...previous, [key]: next }
      browserStorage.writeRaw('local', OPEN_KEY, JSON.stringify(value))
      return value
    })
  return (
    <div className="dt-learning-navigation">
      <OverviewRow href="/learning/new" label={t('navigation.createLearning')} icon={Plus} />
      <OverviewRow
        href="/learning"
        label={t('navigation.allLearning')}
        icon={LayoutGrid}
      />
      <RecordHeader
        title={t('navigation.learningRecords')}
        count={rows.length}
        view={view}
        searchLabel={t('navigation.searchLearning')}
      />
      <div
        className="dt-learning-record-list"
        role="region"
        aria-label={t('navigation.learningRecords')}
        tabIndex={0}
      >
        <Status loading={loading} error={failed.length > 0} retry={retry} />
        <RecordGroups
          rows={rows}
          view={view}
          time={row => row.time}
          renderRow={row =>
            row.kind === 'session' ? (
              <div key={row.key} className="dt-record-loose">{sessions?.render([row.session])}</div>
            ) : (
              <RecordNode
                key={row.key}
                record={row.record}
                time={row.time}
                sessions={row.sessions}
                render={sessions?.render}
                open={
                  (view.query.trim() !== '' &&
                    ((row.record.children ?? []).some(child => matches(child.title, view.query)) ||
                      row.sessions.some(session => matches(titleOf(session), view.query)))) ||
                  (open[row.key] ??
                    (row.sessions.some(session => session.session_id === sessions?.activeSessionId) ||
                      practicing(row.record)))
                }
                onToggle={next => toggle(row.key, next)}
              />
            )
          }
          empty={
            !loading &&
            !failed.length && (
              <p className="dt-navigation-empty">
                {t(view.query ? 'navigation.noResults' : 'navigation.noLearning')}
              </p>
            )
          }
        />
      </div>
    </div>
  )
}

/** One record; its icon turns into the disclosure for the conversations held in it. */
function RecordNode({
  record,
  time,
  sessions,
  render,
  open,
  onToggle,
}: {
  record: LearningActivity
  time: number
  sessions: SessionSummary[]
  render?: (rows: SessionSummary[]) => ReactNode
  open: boolean
  onToggle: (open: boolean) => void
}) {
  const { t } = useTranslation()
  const drawer = useSidebarDrawer()
  const pathname = usePathname()
  const search = useSearchParams()
  const selected = isNavigationTargetActive(record.href, pathname, new URLSearchParams(search.toString()))
  const Icon = learningSurface(record.kind).icon
  const questions = record.children ?? []
  const expandable = questions.length > 0 || (sessions.length > 0 && Boolean(render))
  const expanded = expandable && open
  const toggleLabel = questions.length
    ? t(expanded ? 'navigation.hidePracticeQuestions' : 'navigation.showPracticeQuestions', {
        count: questions.length,
      })
    : t(expanded ? 'navigation.hideRecordChats' : 'navigation.showRecordChats', {
        count: sessions.length,
      })
  return (
    <div className="dt-record-node">
      <div className={`dt-record-node-row ${selected ? 'is-active' : ''} ${expanded ? 'is-open' : ''}`}>
        {expandable ? (
          <button
            type="button"
            className="dt-record-toggle"
            aria-expanded={expanded}
            aria-label={toggleLabel}
            onClick={() => onToggle(!expanded)}
          >
            <Icon size={16} strokeWidth={1.6} className="dt-record-glyph" />
            <ChevronRight size={14} strokeWidth={2} className="dt-record-caret" />
          </button>
        ) : (
          <span className="dt-record-toggle is-static" aria-hidden>
            <Icon size={16} strokeWidth={1.6} className="dt-record-glyph" />
          </span>
        )}
        <Link
          href={record.href}
          prefetch={false}
          aria-current={selected ? 'page' : undefined}
          onClick={event => {
            if (!event.metaKey && !event.ctrlKey && !event.shiftKey) drawer?.close()
          }}
          className="dt-record-node-link"
        >
          <span className="min-w-0 flex-1 truncate">{record.title}</span>
          {questions.length > 0 && !expanded && (
            <span className="dt-record-chat-count" title={t('navigation.practiceQuestions', { count: questions.length })}>
              <ClipboardList size={11} strokeWidth={1.8} aria-hidden />
              {questions.length}
            </span>
          )}
          {expandable && !expanded && questions.length === 0 && (
            <span className="dt-record-chat-count" title={t('navigation.recordChats', { count: sessions.length })}>
              <MessageCircle size={11} strokeWidth={1.8} aria-hidden />
              {sessions.length}
            </span>
          )}
          <RecordTime seconds={time} />
        </Link>
      </div>
      {expanded && (
        <div className="dt-record-children">
          {questions.map(question => (
            <PracticeQuestionNode key={question.key} question={question} />
          ))}
          {render && sessions.length > 0 && render(sessions)}
        </div>
      )}
    </div>
  )
}

/** One question of a collapsed practice set, linking to its own practice turn. */
function PracticeQuestionNode({ question }: { question: LearningActivity }) {
  const drawer = useSidebarDrawer()
  const pathname = usePathname()
  const search = useSearchParams()
  const selected = isNavigationTargetActive(
    question.href,
    pathname,
    new URLSearchParams(search.toString())
  )
  return (
    <Link
      href={question.href}
      prefetch={false}
      aria-current={selected ? 'page' : undefined}
      onClick={event => {
        if (!event.metaKey && !event.ctrlKey && !event.shiftKey) drawer?.close()
      }}
      className={`dt-record-question ${selected ? 'is-active' : ''}`}
    >
      <span className="min-w-0 flex-1 truncate">{question.title}</span>
      <RecordTime seconds={question.updatedAt} />
    </Link>
  )
}
