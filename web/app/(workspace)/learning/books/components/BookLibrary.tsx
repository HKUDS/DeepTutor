'use client'

import { useLibraryFilter, WorkspaceLabel } from '@/components/learning/LibraryWorkspace'
import { libraryItemKey } from '@/lib/learning-library'
import { LearningCardContent } from '@/components/learning/LearningCard'

import {
  LearningShell,
  LearningEmptyState,
  LearningErrorState,
  LearningSkeleton,
} from '@/components/learning/LearningShell'

import { useMemo, useState } from 'react'
import {
  BookOpen,
  Clock3,
  FileText,
  GraduationCap,
  Layers,
  Loader2,
  Plus,
  Search,
  Sparkles,
  Trash2,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'

import type { Book, BookStatus } from '@/lib/book-types'
import { formatRelativeTime } from '@/lib/relative-time'

const STATUS_STYLES: Record<BookStatus, { label: string; className: string; dot: string }> = {
  draft: {
    label: 'Draft',
    className: 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300',
    dot: 'bg-amber-500',
  },
  spine_ready: {
    label: 'Outline',
    className: 'bg-sky-50 text-sky-700 dark:bg-sky-500/10 dark:text-sky-300',
    dot: 'bg-sky-500',
  },
  compiling: {
    label: 'Compiling',
    className: 'bg-violet-50 text-violet-700 dark:bg-violet-500/10 dark:text-violet-300',
    dot: 'bg-violet-500 animate-pulse',
  },
  paused: {
    label: 'Paused',
    className: 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300',
    dot: 'bg-amber-500',
  },
  ready: {
    label: 'Ready',
    className: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300',
    dot: 'bg-emerald-500',
  },
  error: {
    label: 'Error',
    className: 'bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300',
    dot: 'bg-rose-500',
  },
  archived: {
    label: 'Archived',
    className: 'bg-zinc-100 text-zinc-600 dark:bg-zinc-500/10 dark:text-zinc-400',
    dot: 'bg-zinc-400',
  },
}

export interface BookLibraryProps {
  books: Book[]
  loading: boolean
  error?: string | null
  onRetry?: () => void
  canCreate: boolean
  onNewBook: () => void
  onSelectBook: (id: string, workspaceId: string) => void
  onDeleteBook: (id: string, workspaceId: string) => void
}

export default function BookLibrary({
  books: allBooks,
  loading,
  error,
  onRetry,
  canCreate,
  onNewBook,
  onSelectBook,
  onDeleteBook,
}: BookLibraryProps) {
  const { t, i18n } = useTranslation()
  const { rows: books, control } = useLibraryFilter(allBooks)
  const [query, setQuery] = useState('')
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null)

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return books
    return books.filter(b => {
      const t = (b.title || '').toLowerCase()
      const d = (b.description || '').toLowerCase()
      return t.includes(q) || d.includes(q)
    })
  }, [books, query])

  const stats = useMemo(() => {
    const total = books.length
    const ready = books.filter(b => b.status === 'ready').length
    const inProgress = books.filter(
      b =>
        b.status === 'compiling' ||
        b.status === 'paused' ||
        b.status === 'spine_ready' ||
        b.status === 'draft'
    ).length
    const chapters = books.reduce((acc, b) => acc + (b.chapter_count || 0), 0)
    return { total, ready, inProgress, chapters }
  }, [books])

  return (
    <LearningShell
      title={t('Books')}
      subtitle={t('Generate, browse and study your AI-authored books.')}
      action={
        canCreate && (
          <button
            type="button"
            onClick={onNewBook}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3 text-xs font-semibold text-[var(--primary-foreground)]"
          >
            <Plus size={14} />
            {t('New book')}
          </button>
        )
      }
    >
      <div
        className="mb-6 flex flex-wrap items-center gap-x-5 gap-y-3"
        role="search"
        aria-label={t('Search books')}
      >
        {control}
        <div className="relative min-w-48 flex-1 sm:max-w-sm">
          <Search
            size={14}
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--muted-foreground)]"
          />
          <input
            aria-label={t('Search books')}
            value={query}
            onChange={event => setQuery(event.target.value)}
            placeholder={t('Search books')}
            className="h-9 w-full rounded-lg border border-[var(--border)] bg-[var(--background)] pl-9 pr-3 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
          />
        </div>
      </div>
      <div>
        {/* Stats row */}
        <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatCard icon={<BookOpen size={14} />} label={t('Total books')} value={stats.total} />
          <StatCard
            icon={<Sparkles size={14} />}
            label={t('Ready')}
            value={stats.ready}
            accent="text-emerald-600 dark:text-emerald-400"
          />
          <StatCard
            icon={<Loader2 size={14} />}
            label={t('In progress')}
            value={stats.inProgress}
            accent="text-violet-600 dark:text-violet-400"
          />
          <StatCard icon={<Layers size={14} />} label={t('Chapters')} value={stats.chapters} />
        </div>

        {/* Section heading */}
        <div className="mb-3 flex items-end justify-between">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--muted-foreground)]">
              {t('My library')}
            </div>
            <div className="text-xs text-[var(--muted-foreground)]/80">
              {t('{{shown}} of {{total}} books', {
                shown: filtered.length,
                total: books.length,
              })}
              {query ? ` · ${t('matching “{{query}}”', { query })}` : ''}
            </div>
          </div>
        </div>

        {error && <LearningErrorState message={error} onRetry={onRetry} />}
        {loading ? (
          <LearningSkeleton />
        ) : books.length === 0 ? (
          error ? null : (
            <EmptyState onNewBook={canCreate ? onNewBook : undefined} />
          )
        ) : filtered.length === 0 ? (
          <div className="rounded-xl border border-dashed border-[var(--border)] bg-[var(--secondary)]/30 px-6 py-12 text-center text-sm text-[var(--muted-foreground)]">
            {t('No books match “{{query}}”.', { query })}
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {filtered.map(book => {
              const isPendingDelete = pendingDeleteId === libraryItemKey(book, book.id)
              const status = STATUS_STYLES[book.status] || STATUS_STYLES.draft

              return (
                <div
                  key={libraryItemKey(book, book.id)}
                  role="button"
                  tabIndex={0}
                  onClick={() => onSelectBook(book.id, book.content_workspace_id ?? '')}
                  onKeyDown={event => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault()
                      onSelectBook(book.id, book.content_workspace_id ?? '')
                    }
                  }}
                  className="group relative flex cursor-pointer flex-col overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--card)]/70 transition-all hover:-translate-y-0.5 hover:border-[var(--primary)]/40 hover:shadow-md"
                >
                  {/* No cover art.
                      A 112px band of gradient, radial glow, fake book-spine
                      stripes and diagonal hatch, coloured by a hash of the
                      book id: it took the top third of every card and said
                      nothing about the book. What a library card owes the
                      reader is which book this is and where they are in it,
                      so the ornament is gone and its three working parts —
                      status, sharing, delete — moved down to the row that
                      already carries the facts. */}
                  {/* Reading progress, back on the card.
                      It went out with the cover art it happened to sit under
                      — a real loss, because it is the one thing on the card
                      that differs per book *and* per reader. A hairline at
                      the top edge for the shape of it, and the number itself
                      down in the facts row. */}
                  {(book.reading?.percent ?? 0) > 0 && (
                    <div
                      className="h-[3px] w-full overflow-hidden rounded-t-xl bg-[var(--muted)]"
                      aria-hidden
                    >
                      <div
                        className="h-full bg-[var(--primary)]"
                        style={{ width: `${book.reading?.percent ?? 0}%` }}
                      />
                    </div>
                  )}

                  {book.can_delete !== false && (
                    <button
                      type="button"
                      onClick={event => {
                        event.stopPropagation()
                        if (isPendingDelete) {
                          onDeleteBook(book.id, book.content_workspace_id ?? '')
                          setPendingDeleteId(null)
                        } else {
                          setPendingDeleteId(libraryItemKey(book, book.id))
                        }
                      }}
                      title={isPendingDelete ? t('Click again to confirm') : t('Delete book')}
                      // Permanently visible on touch, where there is no hover
                      // to reveal it — a control that only appears on hover
                      // does not exist on a phone.
                      className={`absolute right-2 top-2 z-10 rounded-md p-1.5 transition-colors ${
                        isPendingDelete
                          ? 'bg-rose-500/15 text-rose-600 dark:text-rose-400'
                          : 'text-[var(--muted-foreground)]/70 hover:bg-rose-500/10 hover:text-rose-600 sm:opacity-0 sm:group-hover:opacity-100 dark:hover:text-rose-400'
                      }`}
                    >
                      <Trash2 size={13} />
                    </button>
                  )}

                  {/* Body */}
                  <div className="flex flex-1 flex-col gap-2 p-4">
                    <WorkspaceLabel row={book} />
                    <div className="flex items-center gap-3 pr-3">
                      <LearningCardContent
                        title={book.title || t('Untitled book')}
                        subtitle={
                          book.description ||
                          t('No description yet. Open the book to view its outline.')
                        }
                        icon={<BookOpen size={19} />}
                        progress={(book.reading?.percent ?? 0) / 100}
                      />
                    </div>
                    <div className="mt-auto flex items-center justify-between text-[10px] text-[var(--muted-foreground)]/80">
                      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                        {/* Only the states worth acting on. A "Ready" pill on
                            every card in a library of ready books is a word
                            that never varies — and putting it above the title
                            pushed one card's title lower than its neighbours'.
                            Down here it joins the other facts and the grid
                            keeps one baseline. */}
                        {book.status !== 'ready' && (
                          <span
                            className={`inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-medium ${status.className}`}
                          >
                            <span className={`h-1.5 w-1.5 rounded-full ${status.dot}`} />
                            {t(status.label)}
                          </span>
                        )}
                        {book.source === 'shared' && (
                          <span className="rounded-full bg-[var(--muted)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--muted-foreground)]">
                            {book.can_edit ? t('Shared · edit') : t('Shared · read')}
                          </span>
                        )}
                        <span className="inline-flex items-center gap-1">
                          <Layers size={11} />
                          {t('{{count}} ch', {
                            count: book.chapter_count || 0,
                          })}
                        </span>
                        <span className="inline-flex items-center gap-1">
                          <FileText size={11} />
                          {t('{{count}} pages', {
                            count: book.page_count || 0,
                          })}
                        </span>
                        {(book.reading?.percent ?? 0) > 0 && (
                          <span
                            className="inline-flex items-center gap-1 text-[var(--primary)]"
                            title={t('{{visited}} of {{total}} chapters read', {
                              visited: book.reading?.visited_pages ?? 0,
                              total: book.reading?.total_pages ?? 0,
                            })}
                          >
                            <BookOpen size={11} />
                            {t('{{percent}}% read', {
                              percent: book.reading?.percent ?? 0,
                            })}
                          </span>
                        )}
                      </div>
                      <span className="inline-flex items-center gap-1">
                        <Clock3 size={11} />
                        {formatRelativeTime(book.updated_at, i18n.language) || '—'}
                      </span>
                    </div>
                    <button
                      type="button"
                      onClick={e => {
                        e.stopPropagation()
                        onSelectBook(book.id, book.content_workspace_id ?? '')
                      }}
                      className="mt-2 inline-flex items-center justify-center gap-1 rounded-md bg-[var(--primary)] px-3 py-1.5 text-xs font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90"
                    >
                      <GraduationCap size={13} />
                      {/* Reading position is persisted, so the card can say
                          what opening it will actually do. */}
                      {book.status === 'draft' || book.status === 'spine_ready'
                        ? t('Continue setup')
                        : (book.reading?.visited_pages ?? 0) > 0
                          ? t('Continue reading')
                          : t('Start reading')}
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </LearningShell>
  )
}

function StatCard({
  icon,
  label,
  value,
  accent,
}: {
  icon: React.ReactNode
  label: string
  value: number
  accent?: string
}) {
  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--secondary)]/40 px-4 py-3">
      <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-[var(--muted-foreground)]">
        <span className={accent || 'text-[var(--muted-foreground)]'}>{icon}</span>
        {label}
      </div>
      <div className={`mt-1 text-xl font-semibold ${accent || 'text-[var(--foreground)]'}`}>
        {value}
      </div>
    </div>
  )
}

function EmptyState({ onNewBook }: { onNewBook?: () => void }) {
  const { t } = useTranslation()
  return (
    <LearningEmptyState
      icon={<BookOpen size={28} />}
      title={t('No books yet')}
      description={t(
        'Create your first AI-generated book from a knowledge base, chat selections or simply a topic.'
      )}
      action={
        onNewBook && (
          <button
            type="button"
            onClick={onNewBook}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3 text-sm text-[var(--primary-foreground)]"
          >
            <Plus size={14} />
            {t('New book')}
          </button>
        )
      }
    />
  )
}
