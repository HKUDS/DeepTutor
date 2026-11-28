import type { PendingAttachment } from '@/features/chat/controllers/pending-attachments'

/**
 * An answer the learner attached to their next message from an inline answer
 * card. It travels as an ordinary attachment (`type: "answer"`, JSON in
 * `base64`) so the message store, retries and request snapshots carry it with
 * no new wire field. The turn reads the JSON back and appends the answers to
 * the model prompt; the transcript renders the same payload as a chip.
 */
export const ANSWER_ATTACHMENT_TYPE = 'answer'

export type AnswerAttachmentPayload = {
  question_id: string
  question: string
  answer: string
  source_message_id?: number
}

export interface AnswerPendingAttachment extends PendingAttachment {
  type: typeof ANSWER_ATTACHMENT_TYPE
  questionId: string
  question: string
  answer: string
  sourceMessageId?: number
}

function utf8ToBase64(text: string): string {
  const bytes = new TextEncoder().encode(text)
  let binary = ''
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000))
  }
  return btoa(binary)
}

function base64ToUtf8(value: string): string {
  try {
    const binary = atob(value)
    const bytes = Uint8Array.from(binary, char => char.charCodeAt(0))
    return new TextDecoder().decode(bytes)
  } catch {
    return ''
  }
}

export function answerAttachment(payload: AnswerAttachmentPayload): AnswerPendingAttachment {
  return {
    type: ANSWER_ATTACHMENT_TYPE,
    filename: `answer-${payload.question_id}.json`,
    base64: utf8ToBase64(JSON.stringify(payload)),
    mimeType: 'application/json',
    questionId: payload.question_id,
    question: payload.question,
    answer: payload.answer,
    sourceMessageId: payload.source_message_id,
  }
}

export function isAnswerAttachment(
  attachment: { type?: string } | null | undefined
): attachment is AnswerPendingAttachment {
  return attachment?.type === ANSWER_ATTACHMENT_TYPE
}

/**
 * Read an answer from either side of the wire. The server keeps a JSON mirror
 * in `extracted_text`; the composer's pending attachment carries `base64`.
 */
export function readAnswerAttachment(
  attachment:
    | {
        type?: string
        base64?: string
        extracted_text?: string
        questionId?: string
        question?: string
        answer?: string
        sourceMessageId?: number
      }
    | null
    | undefined
): AnswerAttachmentPayload | null {
  if (!attachment || attachment.type !== ANSWER_ATTACHMENT_TYPE) return null

  const decode = (value: string | undefined): AnswerAttachmentPayload | null => {
    if (!value) return null
    try {
      const parsed = JSON.parse(value) as Partial<AnswerAttachmentPayload>
      if (typeof parsed.question_id !== 'string' || typeof parsed.answer !== 'string') {
        return null
      }
      return {
        question_id: parsed.question_id,
        question: typeof parsed.question === 'string' ? parsed.question : '',
        answer: parsed.answer,
        source_message_id:
          typeof parsed.source_message_id === 'number' ? parsed.source_message_id : undefined,
      }
    } catch {
      return null
    }
  }

  const mirrored = attachment.extracted_text?.trim().startsWith('{')
    ? decode(attachment.extracted_text)
    : null
  if (mirrored) return mirrored

  const decoded = attachment.base64 ? decode(base64ToUtf8(attachment.base64)) : null
  if (decoded) return decoded

  if (attachment.questionId && attachment.answer) {
    return {
      question_id: attachment.questionId,
      question: attachment.question ?? '',
      answer: attachment.answer,
      source_message_id: attachment.sourceMessageId,
    }
  }
  return null
}

export function answerSnippet(answer: string, max = 64): string {
  const compact = answer.replace(/\s+/g, ' ').trim()
  return compact.length > max ? `${compact.slice(0, max).trimEnd()}…` : compact
}
