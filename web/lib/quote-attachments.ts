/**
 * A passage the learner lifted out of the transcript and attached to a
 * message — "add to composer" from a selection.
 *
 * It travels as an ordinary attachment (``type: "quote"``, UTF-8 Markdown in
 * ``base64``) so every surface that already carries attachments — the main
 * composer, side chats, retries, the stored request snapshot — carries a quote
 * with no new field. The backend reads it back as text and puts it in front
 * of the question instead of filing it as a document.
 */

export const QUOTE_ATTACHMENT_TYPE = "quote";
export const QUOTE_ATTACHMENT_FILENAME = "quote.md";
const QUOTE_MIME_TYPE = "text/markdown";
/** Same bound as the server's; a longer selection is clipped, not refused. */
export const MAX_QUOTE_LENGTH = 12_000;

interface QuoteLike {
  type?: string;
  text?: string;
  base64?: string;
  extracted_text?: string;
}

export interface QuotePendingAttachment {
  type: typeof QUOTE_ATTACHMENT_TYPE;
  filename: string;
  text: string;
  base64: string;
  mimeType: string;
}

export function isQuoteAttachment(
  attachment: { type?: string } | null | undefined,
): boolean {
  return attachment?.type === QUOTE_ATTACHMENT_TYPE;
}

function utf8ToBase64(text: string): string {
  const bytes = new TextEncoder().encode(text);
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return btoa(binary);
}

function base64ToUtf8(value: string): string {
  try {
    const binary = atob(value);
    const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
    return new TextDecoder().decode(bytes);
  } catch {
    return "";
  }
}

/** A composer attachment holding ``text``; null when there is nothing to quote. */
export function quoteAttachment(text: string): QuotePendingAttachment | null {
  const body = text.trim().slice(0, MAX_QUOTE_LENGTH);
  if (!body) return null;
  return {
    type: QUOTE_ATTACHMENT_TYPE,
    filename: QUOTE_ATTACHMENT_FILENAME,
    text: body,
    base64: utf8ToBase64(body),
    mimeType: QUOTE_MIME_TYPE,
  };
}

/** The quoted text, whichever side of the wire the attachment came from. */
export function quoteText(attachment: QuoteLike): string {
  if (attachment.text) return attachment.text;
  if (attachment.extracted_text) return attachment.extracted_text;
  return attachment.base64 ? base64ToUtf8(attachment.base64) : "";
}
