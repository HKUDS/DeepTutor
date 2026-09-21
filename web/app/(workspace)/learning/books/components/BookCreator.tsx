'use client'

import { useEffect, useRef, useState } from 'react'
import { ChevronUp, Database, Loader2, Pencil, Sparkles } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useAppShell } from '@/context/AppShellContext'
import type { Book, BookDepth, BookProposal } from '@/lib/book-types'
import type { TopicSourceInput } from '@/lib/learning-api'
import {
  useTopicSourceLibrary,
  hydrateTopicSource,
  toggleSourceSelection,
} from '@/hooks/useTopicSourceLibrary'
import { SourcesStep } from '@/components/space/learning/TopicWizardSteps'

/**
 * Languages a book can be written in, plus the request-driven default.
 *
 * Mirrors `_LANGUAGE_LABELS` in `deeptutor/services/prompt/language.py`, which
 * has always handled all of these — the picker offered only English and
 * Chinese, so everyone else got a book in a language they didn't ask for
 * (issue #471). Labels are endonyms: someone looking for their own language
 * scans for the word they'd write it in.
 */
const BOOK_LANGUAGES: Array<{ code: string; label: string }> = [
  { code: 'auto', label: 'Auto' },
  { code: 'en', label: 'English' },
  { code: 'zh', label: '简体中文' },
  { code: 'zh-tw', label: '繁體中文' },
  { code: 'ja', label: '日本語' },
  { code: 'ko', label: '한국어' },
  { code: 'es', label: 'Español' },
  { code: 'fr', label: 'Français' },
  { code: 'de', label: 'Deutsch' },
  { code: 'ru', label: 'Русский' },
  { code: 'pt', label: 'Português' },
  { code: 'it', label: 'Italiano' },
]

const DEPTH_OPTIONS: Array<{ value: BookDepth; label: string; hint: string }> = [
  {
    value: 'brief',
    label: 'Brief',
    hint: 'Roughly half the prose per chapter — a fast orientation.',
  },
  {
    value: 'standard',
    label: 'Standard',
    hint: 'The default balance of explanation, examples and practice.',
  },
  {
    value: 'deep',
    label: 'Deep',
    hint: 'Longer treatments with more worked detail. Takes noticeably longer.',
  },
]

export interface BookCreatorProps {
  onCreate: (payload: {
    source_refs: TopicSourceInput[]
    user_intent: string
    chat_session_id: string
    chat_selections: Array<{ session_id: string; message_ids: number[] }>
    knowledge_bases: string[]
    notebook_refs: Array<Record<string, unknown>>
    question_categories: number[]
    question_entries: number[]
    language: string
    fallback_language: string
    depth: BookDepth
  }) => void | Promise<void>
  loading?: boolean
  /** The draft being edited, when one was reopened from the library. */
  book?: Book | null
  proposal?: BookProposal | null
  onConfirmProposal?: (edited: BookProposal) => void | Promise<void>
  confirmLoading?: boolean
}

export default function BookCreator({
  onCreate,
  loading = false,
  book = null,
  proposal = null,
  onConfirmProposal,
  confirmLoading = false,
}: BookCreatorProps) {
  const { t } = useTranslation()
  const { language: appLanguage } = useAppShell()
  const [intent, setIntent] = useState('')
  const [language, setLanguage] = useState<string>('auto')
  const [depth, setDepth] = useState<BookDepth>('standard')
  const {
    library,
    loading: libraryLoading,
    candidates,
    childLists,
    loadChildren,
  } = useTopicSourceLibrary(t)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [sourceError, setSourceError] = useState('')
  const [preparing, setPreparing] = useState(false)
  const selectedKbs = new Set(
    candidates
      .filter(item => selected.has(item.key) && item.kind === 'knowledge_base')
      .map(item => item.sourceId)
  )
  const [editProposal, setEditProposal] = useState<BookProposal | null>(null)
  const [formCollapsed, setFormCollapsed] = useState(false)
  const lastSeenProposalIdRef = useRef<string | null>(null)

  // Auto-collapse the form once the proposal first arrives (never overwrites
  // a manual expand later because we only fire on identity change).
  useEffect(() => {
    const id = proposal ? proposal.title || '_proposal_' : null
    if (id && id !== lastSeenProposalIdRef.current) {
      setFormCollapsed(true)
      // A new proposal replaces the old one outright. Keeping the previous
      // edits would show text belonging to a proposal that no longer exists —
      // and confirming would submit it.
      setEditProposal(null)
    }
    lastSeenProposalIdRef.current = id
  }, [proposal])

  const handleCreate = async () => {
    if (!intent.trim() || preparing) return
    setPreparing(true)
    setSourceError('')
    try {
      const source_refs = await Promise.all(
        candidates.filter(item => selected.has(item.key)).map(hydrateTopicSource)
      )
      await onCreate({
        user_intent: intent,
        source_refs,
        depth,
        chat_session_id: '',
        chat_selections: [],
        knowledge_bases: Array.from(selectedKbs),
        notebook_refs: [],
        question_categories: [],
        question_entries: [],
        language,
        fallback_language: appLanguage,
      })
    } catch (err) {
      setSourceError(err instanceof Error ? err.message : String(err))
    } finally {
      setPreparing(false)
    }
  }
  const currentProposal = editProposal || proposal
  const summaryChips = selected.size
    ? [{ icon: Database, label: t('{{count}} selected', { count: selected.size }) }]
    : []

  return (
    <div className="mx-auto w-full max-w-4xl space-y-5 p-6">
      <div className="space-y-1.5">
        <h1 className="font-serif text-2xl font-semibold text-[var(--foreground)]">
          {t('Create a new book')}
        </h1>
        <p className="text-sm text-[var(--muted-foreground)]">
          {t(
            'Describe what you want to learn, then pick the knowledge sources to fuse into a structured, interactive book.'
          )}
        </p>
      </div>

      <div className="rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-sm">
        <button
          type="button"
          onClick={() => setFormCollapsed(v => !v)}
          className="flex w-full items-center justify-between gap-3 rounded-t-2xl px-5 py-3 text-left hover:bg-[var(--muted)]/40"
        >
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-[var(--foreground)]">
                {formCollapsed ? t('Inputs') : t('Configure inputs')}
              </span>
              {formCollapsed && intent.trim() && (
                <span className="truncate text-xs text-[var(--muted-foreground)]">
                  · {clip(intent, 90)}
                </span>
              )}
            </div>
            {formCollapsed && (
              <div className="mt-1 flex flex-wrap items-center gap-1.5">
                {summaryChips.length === 0 ? (
                  <span className="text-[11px] text-[var(--muted-foreground)]">
                    {t('No knowledge sources selected')}
                  </span>
                ) : (
                  summaryChips.map((chip, i) => (
                    <span
                      key={i}
                      className="inline-flex items-center gap-1 rounded-full bg-[var(--primary)]/10 px-2 py-0.5 text-[11px] font-medium text-[var(--primary)]"
                    >
                      <chip.icon className="h-3 w-3" />
                      {chip.label}
                    </span>
                  ))
                )}
              </div>
            )}
          </div>
          <span className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-[var(--muted-foreground)]">
            {formCollapsed ? (
              <>
                <Pencil className="h-3 w-3" />
                {t('Edit')}
              </>
            ) : (
              <ChevronUp className="h-3.5 w-3.5" />
            )}
          </span>
        </button>

        {!formCollapsed && (
          <div className="space-y-4 px-5 pb-5">
            <label className="block">
              <span className="text-xs font-semibold uppercase tracking-[0.16em] text-[var(--muted-foreground)]">
                {t('Learning intent')}
              </span>
              <textarea
                value={intent}
                onChange={e => setIntent(e.target.value)}
                rows={5}
                placeholder={t(
                  'e.g. Build intuition for transformer attention with derivations and exercises.'
                )}
                className="mt-1.5 w-full resize-none rounded-xl border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm text-[var(--foreground)] outline-none focus:border-[var(--primary)]/50"
              />
            </label>

            <SourcesStep
              library={library}
              loading={libraryLoading}
              selected={selected}
              onToggle={key =>
                setSelected(previous => toggleSourceSelection(previous, key, candidates))
              }
              childLists={childLists}
              onExpand={loadChildren}
            />
            {sourceError && (
              <p role="alert" className="text-sm text-destructive">
                {sourceError}
              </p>
            )}

            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap items-center gap-4">
                <label className="text-xs text-[var(--muted-foreground)]">
                  {t('Language')}{' '}
                  <select
                    value={language}
                    onChange={e => {
                      setLanguage(e.target.value)
                    }}
                    className="ml-1 rounded-md border border-[var(--border)] bg-[var(--background)] px-1.5 py-0.5 text-xs text-[var(--foreground)]"
                  >
                    {BOOK_LANGUAGES.map(option => (
                      <option key={option.code} value={option.code}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>

                <div className="flex items-center gap-1.5 text-xs text-[var(--muted-foreground)]">
                  {t('Depth')}
                  <div className="inline-flex overflow-hidden rounded-md border border-[var(--border)] text-[11px]">
                    {DEPTH_OPTIONS.map(option => (
                      <button
                        key={option.value}
                        type="button"
                        onClick={() => setDepth(option.value)}
                        aria-pressed={depth === option.value}
                        title={t(option.hint)}
                        className={`px-2 py-0.5 font-medium transition-colors ${
                          depth === option.value
                            ? 'bg-[var(--primary)]/12 text-[var(--foreground)]'
                            : 'text-[var(--muted-foreground)] hover:bg-[var(--muted)]/40 hover:text-[var(--foreground)]'
                        }`}
                      >
                        {t(option.label)}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
              <button
                onClick={handleCreate}
                disabled={loading || preparing || !intent.trim()}
                className="inline-flex items-center gap-2 rounded-xl bg-[var(--primary)] px-4 py-2 text-sm font-medium text-[var(--primary-foreground)] hover:opacity-90 disabled:opacity-50"
              >
                {loading ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Sparkles className="h-4 w-4" />
                )}
                {t('Generate proposal')}
              </button>
            </div>
          </div>
        )}
      </div>

      {currentProposal && onConfirmProposal && (
        <div className="space-y-4 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 shadow-sm">
          <div>
            <h2 className="text-base font-semibold text-[var(--foreground)]">{t('Proposal')}</h2>
            <p className="text-xs text-[var(--muted-foreground)]">
              {t('Edit anything below, then confirm to generate the chapter spine.')}
            </p>
          </div>
          <ProposalForm
            proposal={currentProposal}
            onChange={setEditProposal}
            selectedKbs={Array.from(selectedKbs)}
            savedKbs={book?.knowledge_bases}
          />
          <div className="flex justify-end">
            <button
              onClick={() =>
                editProposal ? onConfirmProposal(editProposal) : onConfirmProposal(currentProposal)
              }
              disabled={confirmLoading}
              className="inline-flex items-center gap-2 rounded-xl bg-[var(--primary)] px-4 py-2 text-sm font-medium text-[var(--primary-foreground)] hover:opacity-90 disabled:opacity-50"
            >
              {confirmLoading && <Loader2 className="h-4 w-4 animate-spin" />}
              {t('Confirm proposal & build spine')}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── helpers ───────────────────────────────────────────────────────────

function clip(text: string, n: number): string {
  if (!text) return ''
  const t = text.replace(/\s+/g, ' ').trim()
  return t.length <= n ? t : t.slice(0, n) + '…'
}

function ProposalForm({
  proposal,
  onChange,
  selectedKbs,
  savedKbs,
}: {
  proposal: BookProposal
  onChange: (p: BookProposal) => void
  selectedKbs: string[]
  /** KBs already recorded on the book. Reopening a draft restores no local
   *  picker state, so without this the form claims the book has no sources. */
  savedKbs?: string[]
}) {
  const { t } = useTranslation()
  const effectiveKbs = selectedKbs.length > 0 ? selectedKbs : (savedKbs ?? [])
  const update = (patch: Partial<BookProposal>) => onChange({ ...proposal, ...patch })
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <label className="block sm:col-span-2">
        <span className="text-xs uppercase tracking-wider text-[var(--muted-foreground)]">
          {t('Title')}
        </span>
        <input
          value={proposal.title}
          onChange={e => update({ title: e.target.value })}
          className="mt-1 w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-2.5 py-1.5 text-sm text-[var(--foreground)]"
        />
      </label>
      <label className="block sm:col-span-2">
        <span className="text-xs uppercase tracking-wider text-[var(--muted-foreground)]">
          {t('Description')}
        </span>
        <textarea
          value={proposal.description}
          onChange={e => update({ description: e.target.value })}
          rows={3}
          className="mt-1 w-full resize-none rounded-md border border-[var(--border)] bg-[var(--background)] px-2.5 py-1.5 text-sm text-[var(--foreground)]"
        />
      </label>
      <label className="block">
        <span className="text-xs uppercase tracking-wider text-[var(--muted-foreground)]">
          {t('Scope')}
        </span>
        <input
          value={proposal.scope}
          onChange={e => update({ scope: e.target.value })}
          className="mt-1 w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-2.5 py-1.5 text-sm text-[var(--foreground)]"
        />
      </label>
      <label className="block">
        <span className="text-xs uppercase tracking-wider text-[var(--muted-foreground)]">
          {t('Target level')}
        </span>
        <input
          value={proposal.target_level}
          onChange={e => update({ target_level: e.target.value })}
          className="mt-1 w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-2.5 py-1.5 text-sm text-[var(--foreground)]"
        />
      </label>
      <label className="block">
        <span className="text-xs uppercase tracking-wider text-[var(--muted-foreground)]">
          {t('Estimated chapters')}
        </span>
        <input
          type="number"
          min={2}
          max={12}
          value={proposal.estimated_chapters}
          onChange={e => update({ estimated_chapters: Number(e.target.value) || 0 })}
          className="mt-1 w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-2.5 py-1.5 text-sm text-[var(--foreground)]"
        />
      </label>
      <div className="block sm:col-span-2">
        <span className="text-xs uppercase tracking-wider text-[var(--muted-foreground)]">
          {t('Knowledge bases used')}
        </span>
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {effectiveKbs.length === 0 ? (
            <span className="text-xs italic text-[var(--muted-foreground)]">
              {t('No knowledge bases selected. The book will rely on general knowledge.')}
            </span>
          ) : (
            effectiveKbs.map(kb => (
              <span
                key={kb}
                className="inline-flex items-center rounded-full border border-[var(--border)] bg-[var(--muted)]/40 px-2.5 py-0.5 text-[11px] text-[var(--foreground)]"
              >
                {kb}
              </span>
            ))
          )}
        </div>
      </div>
    </div>
  )
}
