'use client'
import dynamic from 'next/dynamic'
import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, ChevronDown, LoaderCircle, Sparkles } from 'lucide-react'
import { useMenuPopover } from '@/shared/ui/useMenuPopover'
import { upsertNotebookEntry } from '@/lib/notebook-api'
import NoteAudioOptions from './NoteAudioOptions'
import { noteConceptMap } from '../model/concept-map'
import { noteGenerationError } from '../model/generation-error'
import { generationPreview, subscribeGenerationPreviews } from '../model/generation-previews'
import {
  hasLearningContent,
  learningGenerationConfig,
  learningKind,
  LEARNING_KINDS,
} from '../model/learning-kinds'
import type { Block, QuizAttempt } from '@/lib/book-types'
const Geometry = dynamic(() => import('./NoteGeometry'), { ssr: false })
const Result = dynamic(() => import('./NoteResult'), { ssr: false })
const Timeline = dynamic(
  () => import('@/app/(workspace)/learning/books/components/blocks/TimelineBlock'),
  { ssr: false }
)
const Task = dynamic(() => import('./NoteTaskBlock'), { ssr: false })
const Markdown = dynamic(() => import('@/components/common/MarkdownRenderer'), { ssr: false })
const Quiz = dynamic(() => import('@/app/(workspace)/learning/books/components/blocks/QuizBlock'), {
  ssr: false,
})
const Flashcards = dynamic(
  () => import('@/app/(workspace)/learning/books/components/blocks/FlashCardsBlock'),
  { ssr: false }
)

export default function NoteLearningContent({
  id,
  kind,
  prompt,
  markdown,
  data,
  sourceUrl,
  onChange,
  readOnly = false,
}: {
  id: string
  readOnly?: boolean
  kind: string
  prompt: string
  markdown: string
  data: string
  sourceUrl: string
  onChange: (props: { prompt?: string; data?: string; kind?: string; markdown?: string }) => void
}) {
  const { t } = useTranslation()
  const root = useRef<HTMLDivElement>(null)
  const [visible, setVisible] = useState(false)
  const [error, setError] = useState('')
  const preview = useSyncExternalStore(
    subscribeGenerationPreviews,
    () => generationPreview(id),
    () => null
  )
  useEffect(() => {
    const observer = new IntersectionObserver(
      entries => {
        if (entries.some(entry => entry.isIntersecting)) {
          setVisible(true)
          observer.disconnect()
        }
      },
      { rootMargin: '400px' }
    )
    if (root.current) observer.observe(root.current)
    return () => observer.disconnect()
  }, [])
  let payload: Record<string, unknown> = {}
  try {
    payload = JSON.parse(data)
  } catch {
    /* Keep malformed generated content editable as Markdown. */
  }
  const generation = (payload.generation || {}) as Record<string, unknown>
  const block = {
    id,
    type: kind === 'flashcards' ? 'flash_cards' : 'quiz',
    status: 'ready',
    payload,
  } as Block
  const pending = Boolean(preview?.pending)
  const filled = hasLearningContent(kind, markdown, payload)
  // A generated block is only its material, part of the page like any other
  // block: no frame, no request. Another version is asked for from the
  // block's menu, in a conversation that starts from the old request.
  const formOpen = !readOnly && !pending && !filled
  const generate = () =>
    root.current?.dispatchEvent(
      new CustomEvent('note-generate', {
        bubbles: true,
        detail: { blockId: id, kind, prompt, config: learningGenerationConfig(kind, data) },
      })
    )
  const openThread = () =>
    preview?.sessionId &&
    root.current?.dispatchEvent(
      new CustomEvent('note-open-thread', {
        bubbles: true,
        detail: { sessionId: preview.sessionId },
      })
    )
  return (
    <div
      ref={root}
      className="dt-note-learning"
      data-state={pending ? 'pending' : filled ? 'filled' : 'empty'}
      contentEditable={false}
    >
      {(!filled || pending) && (
        <div className="dt-note-learning-head">
          <KindSwitcher
            kind={kind}
            disabled={readOnly || pending}
            onChange={next => {
              if (next === kind) return
              onChange({ kind: next, markdown: '', data: JSON.stringify({ generation }) })
            }}
          />
          {pending && prompt.trim() && <span className="dt-note-learning-prompt">{prompt}</span>}
          <span className="flex-1" />
          {pending && (
            <button className="dt-note-learning-status" onClick={openThread}>
              <LoaderCircle size={13} className="animate-spin" aria-hidden />
              {t('Generating…')}
            </button>
          )}
        </div>
      )}
      {formOpen && (
        <div className="dt-note-generation-form">
          <textarea
            rows={2}
            aria-label={t('Generation instructions')}
            placeholder={t(learningKind(kind).placeholder)}
            value={prompt}
            onChange={e => onChange({ prompt: e.target.value })}
            onKeyDown={e => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && kind !== 'task') {
                e.preventDefault()
                generate()
              }
            }}
          />
          {kind !== 'task' && (
            <div className="dt-note-generation-actions">
              <span className="dt-note-generation-hint">{t('⌘↵ to generate')}</span>
              <button className="dt-note-action is-primary" onClick={generate}>
                <Sparkles size={13} aria-hidden />
                {t('Generate')}
              </button>
            </div>
          )}
        </div>
      )}
      {formOpen && kind === 'audio' && (
        <NoteAudioOptions
          value={generation}
          disabled={pending}
          onChange={generation => onChange({ data: JSON.stringify({ ...payload, generation }) })}
        />
      )}
      {preview?.error && (
        <p role="alert" className="text-sm text-red-600">
          {t(noteGenerationError(preview.error))}
        </p>
      )}
      {pending && (
        <div className="dt-note-generation-preview" aria-live="polite">
          {preview?.content ? (
            <Markdown content={preview.content} />
          ) : (
            <div
              className="dt-note-generation-shimmer"
              aria-label={t('Preparing learning material…')}
            >
              <span />
              <span />
              <span />
            </div>
          )}
        </div>
      )}
      {!preview?.pending &&
        visible &&
        (kind === 'task' ? (
          <Task data={data} prompt={prompt} onChange={onChange} />
        ) : kind === 'quiz' && Array.isArray(payload.questions) ? (
          <Quiz
            block={block}
            attempts={Array.isArray(payload.attempts) ? (payload.attempts as QuizAttempt[]) : []}
            onAttempt={(_, args) => {
              const questions = payload.questions as Array<Record<string, unknown>>
              const index = questions.findIndex(
                (q, i) => (q.question_id || `${id}:${i + 1}`) === args.questionId
              )
              const question = questions[index]
              if (!question) return
              if (!readOnly) {
                const attempts = (
                  Array.isArray(payload.attempts) ? payload.attempts : []
                ) as QuizAttempt[]
                onChange({
                  data: JSON.stringify({
                    ...payload,
                    attempts: [
                      ...attempts.filter(a => a.question_id !== args.questionId),
                      {
                        block_id: id,
                        page_id: window.location.pathname,
                        question_id: args.questionId,
                        user_answer: args.userAnswer || '',
                        is_correct: args.isCorrect ?? null,
                        timestamp: Date.now() / 1000,
                      },
                    ],
                  }),
                })
              }
              if (readOnly) return
              void upsertNotebookEntry({
                origin_type: 'document_analysis',
                origin_ref: window.location.pathname + '#' + id,
                question_id: args.questionId || `${id}:${index + 1}`,
                question: String(question.question || ''),
                options: question.options as Record<string, string>,
                correct_answer: String(question.correct_answer || ''),
                explanation: String(question.explanation || ''),
                user_answer: args.userAnswer,
                is_correct: args.isCorrect,
                material_title: document.title,
              }).catch(e => setError(String(e)))
            }}
          />
        ) : kind === 'flashcards' && Array.isArray(payload.cards) ? (
          <Flashcards block={block} />
        ) : ['visualization', 'animation', 'media', 'audio', 'image'].includes(kind) &&
          (payload.renderer || payload.artifacts || payload.workspace_items) ? (
          <Result payload={payload} />
        ) : kind === 'research' && payload.outline_preview && Array.isArray(payload.sub_topics) ? (
          <ol className="space-y-3">
            {(payload.sub_topics as Array<{ title: string; overview: string }>).map((topic, i) => (
              <li key={i}>
                <strong>
                  {i + 1}. {topic.title}
                </strong>
                <p className="text-sm text-[var(--muted-foreground)]">{topic.overview}</p>
              </li>
            ))}
          </ol>
        ) : kind === 'geogebra' && Array.isArray(payload.commands) ? (
          <>
            <Geometry data={data} />
            {markdown && <Markdown content={markdown} />}
          </>
        ) : kind === 'timeline' && Array.isArray(payload.events) ? (
          // A timeline reads as part of the page, without the book's panel.
          <div className="dt-note-bare">
            <Timeline block={block} />
          </div>
        ) : kind === 'concept_map' && (Array.isArray(payload.nodes) || payload.graph) ? (
          <Markdown content={noteConceptMap(payload) || markdown} />
        ) : markdown ? (
          <Markdown content={markdown} />
        ) : null)}
      {error && (
        <p role="alert" className="text-sm text-red-600">
          {error}
        </p>
      )}
      {sourceUrl && (
        <a href={sourceUrl} className="text-xs text-[var(--primary)]">
          ↗ {t('Source')}
        </a>
      )}
    </div>
  )
}

/** The block's kind, as a menu: a block can become any other kind of material. */
function KindSwitcher({
  kind,
  disabled,
  onChange,
}: {
  kind: string
  disabled: boolean
  onChange: (kind: string) => void
}) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const menu = useMenuPopover<HTMLDivElement>(open, setOpen)
  const current = learningKind(kind)
  return (
    <div ref={menu} className="relative">
      <button
        className="dt-note-kind"
        aria-haspopup="menu"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => setOpen(!open)}
      >
        <current.Icon size={14} strokeWidth={1.8} aria-hidden />
        {t(current.label)}
        {!disabled && <ChevronDown size={12} className="opacity-60" aria-hidden />}
      </button>
      {open && (
        <div className="dt-popover dt-note-kind-menu" role="menu">
          {LEARNING_KINDS.map(option => (
            <button
              key={option.kind}
              role="menuitemradio"
              aria-checked={option.kind === kind}
              className="dt-menu-item"
              onClick={() => {
                setOpen(false)
                onChange(option.kind)
              }}
            >
              <option.Icon size={14} strokeWidth={1.8} />
              <span className="flex-1">{t(option.label)}</span>
              {option.kind === kind && <Check size={13} />}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
