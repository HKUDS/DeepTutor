'use client'

import { useState } from 'react'
import { Link2, MessageSquare } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { answerSnippet } from './answer-attachment'
import {
  answerAnchorId,
  inlineAnswerKey,
  questionAnchorId,
  scrollToAnchor,
  useInlineAnswers,
} from './context'

/**
 * The answer field the assistant can place in its own reply with
 * `[[answer:q1]]`. It is a card, not a chat composer: "Attach" puts the answer
 * on the learner's next message, and the card collapses to a link to that
 * answer. The model never pauses.
 */
export function AnswerCard({
  messageId,
  questionId,
  disabled = false,
}: {
  messageId?: number
  questionId: string
  disabled?: boolean
}) {
  const { t } = useTranslation()
  const inline = useInlineAnswers()
  const [text, setText] = useState('')
  if (!inline) return null

  const attached = inline.attached.get(inlineAnswerKey(questionId, messageId))
  const anchor = questionAnchorId(messageId, questionId)

  if (attached) {
    return (
      <div
        id={anchor}
        data-answer-question={questionId}
        className="my-2 max-w-[460px] scroll-mt-24"
      >
        <button
          type="button"
          onClick={() => scrollToAnchor(answerAnchorId(attached.messageId, questionId))}
          className="group flex max-w-full items-center gap-2 rounded-lg border border-[var(--border)]/70 bg-[var(--card)] px-2.5 py-1.5 text-left text-[12.5px] text-[var(--foreground)] shadow-sm transition-colors hover:border-[var(--foreground)]/25 hover:bg-[var(--secondary)]"
        >
          <Link2 size={13} strokeWidth={1.8} className="shrink-0 text-[var(--muted-foreground)]" />
          <span className="min-w-0 truncate">
            <span className="text-[var(--muted-foreground)]">{t('Answer')} · </span>
            {answerSnippet(attached.answer)}
          </span>
        </button>
      </div>
    )
  }

  return (
    <div
      id={anchor}
      data-answer-question={questionId}
      className="my-3 w-full max-w-[460px] scroll-mt-24 overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--card)] shadow-[0_10px_30px_-18px_rgba(0,0,0,0.35)]"
    >
      <div className="flex items-center gap-1.5 px-3 pt-2.5 text-[11px] font-medium tracking-wide text-[var(--muted-foreground)]">
        <MessageSquare size={12} strokeWidth={1.8} />
        {t('Answer')}
      </div>
      <textarea
        value={text}
        onChange={event => setText(event.target.value)}
        placeholder={t('Type your reply…')}
        aria-label={t('Your answer')}
        rows={2}
        disabled={disabled}
        className="min-h-[58px] w-full resize-y bg-transparent px-3 py-2 text-[13.5px] leading-snug text-[var(--foreground)] outline-none placeholder:text-[var(--muted-foreground)]/80 disabled:opacity-60"
      />
      <div className="flex justify-end border-t border-[var(--border)]/60 px-2.5 py-1.5">
        <button
          type="button"
          onClick={() => {
            const answer = text.trim()
            if (!answer || disabled) return
            inline.attach({
              question_id: questionId,
              question: '',
              answer,
              source_message_id: messageId,
            })
          }}
          disabled={disabled || !text.trim()}
          className="rounded-md bg-[var(--primary)] px-2.5 py-1 text-[12px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {t('Attach')}
        </button>
      </div>
    </div>
  )
}
