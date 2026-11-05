'use client'

import { useCallback, useEffect, useState, useSyncExternalStore } from 'react'
import { createPortal } from 'react-dom'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'
import { Check, MessageSquare, Sparkles, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { NoteSuggestion } from '@/lib/notes-api'
import type { BlockNoteEditor } from '@blocknote/core'
import NoteSuggestionContent from './NoteSuggestionContent'
import { reviewPosition } from '../model/review-placement'
import { researchOutline } from '../model/research'

type Entry = { suggestion: NoteSuggestion; host: HTMLDivElement; position?: number }
const reviewKey = new PluginKey<Entry[]>('note-inline-reviews')
const keepsChildren = (suggestion: NoteSuggestion) => suggestion.preserve_children ?? (
  suggestion.operation === 'replace' && !!suggestion.original?.children?.length &&
  (!suggestion.blocks || (!!suggestion.blocks.length && !suggestion.blocks[0].children?.length))
)

export default function NoteInlineReviews({
  editor,
  suggestions,
  busy,
  errors = {},
  onReview,
  onDiscuss,
  onContinueResearch,
}: {
  editor: Pick<BlockNoteEditor, '_tiptapEditor'>
  suggestions: NoteSuggestion[]
  busy: boolean
  errors?: Record<string, string>
  onReview: (suggestion: NoteSuggestion, accept: boolean) => void
  onContinueResearch?: (suggestion: NoteSuggestion) => void
  onDiscuss: (suggestion: NoteSuggestion) => void
}) {
  const { t } = useTranslation()
  const tiptap = editor._tiptapEditor
  const subscribe = useCallback((notify: () => void) => {
    tiptap.on('transaction', notify)
    return () => { tiptap.off('transaction', notify) }
  }, [tiptap])
  const doc = useSyncExternalStore(subscribe, () => tiptap.state.doc, () => tiptap.state.doc)
  const [snapshot, setSnapshot] = useState(() => ({
    suggestions,
    entries: reviewEntries(suggestions, []),
  }))
  if (snapshot.suggestions !== suggestions)
    setSnapshot({ suggestions, entries: reviewEntries(suggestions, snapshot.entries) })
  const entries = snapshot.entries
  useEffect(() => {
    const tiptap = editor._tiptapEditor
    tiptap.registerPlugin(
      new Plugin<Entry[]>({
        key: reviewKey,
        state: {
          init: () => [],
          apply: (tr, previous) => {
            const entries: Entry[] = tr.getMeta(reviewKey) ?? previous
            return entries.map(entry => {
              const { target, position } = reviewPosition(tr.doc, entry.suggestion.block_id, entry.suggestion.anchors, keepsChildren(entry.suggestion))
              const old = previous.find(value => value.suggestion.id === entry.suggestion.id)
              let mapped = !target && old?.position !== undefined
                ? tr.mapping.map(old.position, -1) : position
              mapped = Math.max(1, Math.min(mapped, tr.doc.content.size - 1))
              // Joining/deleting text can map the old boundary inside a block.
              // Keep a block-level review outside editable inline content.
              const resolved = tr.doc.resolve(mapped)
              for (let depth = !target && resolved.parent.type.name !== 'blockGroup' ? resolved.depth : 0; depth > 0; depth--) {
                if (resolved.node(depth).type.name === 'blockContainer') {
                  mapped = resolved.after(depth)
                  break
                }
              }
              return { ...entry, position: mapped }
            })
          },
        },
        props: {
          decorations(state) {
            const decorations: Decoration[] = []
            for (const { suggestion, host, position: mapped } of reviewKey.getState(state) || []) {
              const { target, position } = reviewPosition(state.doc, suggestion.block_id, suggestion.anchors, keepsChildren(suggestion))
              if (target && suggestion.operation !== 'insert')
                decorations.push(
                  Decoration.node(target.from, target.to, { class: 'dt-note-review-original' })
                )
              decorations.push(
                Decoration.widget(target ? position : mapped ?? position, () => host, {
                  key: suggestion.id,
                  side: 1,
                  stopEvent: () => true,
                  ignoreSelection: true,
                })
              )
            }
            return DecorationSet.create(state.doc, decorations)
          },
        },
      })
    )
    return () => {
      tiptap.unregisterPlugin(reviewKey)
    }
  }, [editor])
  useEffect(() => {
    const tiptap = editor._tiptapEditor
    tiptap.view.dispatch(tiptap.state.tr.setMeta(reviewKey, entries).setMeta('addToHistory', false))
  }, [editor, entries])
  return entries.map(({ suggestion: s, host }) => {
    const missing = !!s.block_id && !reviewPosition(doc, s.block_id).target
    const keepChildren = keepsChildren(s)
    return createPortal(
      <article aria-label={t('Suggested edit')} tabIndex={-1} className="dt-note-review-card">
        <header>
          <span>
            <Sparkles size={15} />
            {t(
              {
                replace: 'Suggested replacement',
                insert: 'Suggested addition',
                delete: 'Suggested deletion',
                comment: 'Comment',
              }[s.operation]
            )}
          </span>
          <div>
            <button className="dt-note-button" disabled={busy} onClick={() => onReview(s, false)}>
              <X size={14} />
              {t('Dismiss suggestion')}
            </button>
            <button
              className="dt-note-button dt-note-review-accept"
              disabled={busy || missing}
              onClick={() => (researchOutline(s) ? onContinueResearch?.(s) : onReview(s, true))}
            >
              <Check size={14} />
              {t(
                researchOutline(s)
                  ? 'Research this outline'
                  : s.operation === 'comment'
                    ? 'Resolve'
                    : 'Accept'
              )}
            </button>
          </div>
        </header>
        {missing && (
          <p role="status" className="dt-note-review-error">
            {t('The original block was removed. Restore it to review this suggestion, or dismiss it.')}
          </p>
        )}
        {errors[s.id] && (
          <p role="alert" className="dt-note-review-error">
            {errors[s.id]}
          </p>
        )}
        {s.explanation && (
          <details className="dt-note-review-reason">
            <summary>{t('Why this change')}</summary>
            <p>{s.explanation}</p>
          </details>
        )}
        {s.operation === 'delete' ? (
          <p>{t('Accept to remove the highlighted block.')}</p>
        ) : (
          <div className="dt-note-review-content">
            <NoteSuggestionContent blocks={s.blocks} markdown={s.markdown} />
            {keepChildren && <p className="text-xs text-[var(--muted-foreground)]">{t('Nested blocks will be kept, including your latest edits.')}</p>}
          </div>
        )}
        <button className="dt-note-button" disabled={busy} onClick={() => onDiscuss(s)}>
          <MessageSquare size={14} />
          {t('Discuss')}
        </button>
      </article>,
      host,
      s.id
    )
  })
}

function reviewEntries(suggestions: NoteSuggestion[], previous: Entry[]): Entry[] {
  return suggestions.map(suggestion => {
    const existing = previous.find(entry => entry.suggestion.id === suggestion.id)
    if (existing) return { suggestion, host: existing.host }
    const host = document.createElement('div')
    host.className = 'dt-note-inline-review'
    host.contentEditable = 'false'
    host.dataset.reviewFor = suggestion.block_id
    return { suggestion, host }
  })
}
