'use client'

import { createContext, useContext, type ReactNode } from 'react'
import type { AnswerAttachmentPayload } from './answer-attachment'

/**
 * An answer that is currently attached to a draft or to a sent user message.
 * `messageId` is the user message it belongs to once sent; while it is still
 * in the composer it is undefined and its chip lives in the draft.
 */
export type InlineAnswer = AnswerAttachmentPayload & {
  messageId?: number
}

export type InlineAnswersValue = {
  /** Keyed by assistant message + question id, so repeated `q1` ids do not collide. */
  attached: ReadonlyMap<string, InlineAnswer>
  /** Attach an answer to the next user message. */
  attach: (payload: AnswerAttachmentPayload) => void
}

const InlineAnswersContext = createContext<InlineAnswersValue | null>(null)

export function InlineAnswersProvider({
  value,
  children,
}: {
  value: InlineAnswersValue
  children: ReactNode
}) {
  return <InlineAnswersContext.Provider value={value}>{children}</InlineAnswersContext.Provider>
}

export function useInlineAnswers(): InlineAnswersValue | null {
  return useContext(InlineAnswersContext)
}

export function inlineAnswerKey(questionId: string, sourceMessageId?: number): string {
  return `${sourceMessageId ?? 'stream'}:${questionId}`
}

export function questionAnchorId(messageId: number | undefined, questionId: string): string {
  return `question-${messageId ?? 'stream'}-${questionId}`
}

export function answerAnchorId(messageId: number | undefined, questionId: string): string {
  return `answer-${messageId ?? 'draft'}-${questionId}`
}

/** Scroll to a question/answer anchor and flash it briefly. */
export function scrollToAnchor(id: string): void {
  if (typeof document === 'undefined') return
  const element = document.getElementById(id)
  if (!element) return
  element.scrollIntoView({ behavior: 'smooth', block: 'center' })
  element.classList.add('inline-answer-flash')
  window.setTimeout(() => element.classList.remove('inline-answer-flash'), 1400)
}
