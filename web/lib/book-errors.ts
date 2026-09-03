/**
 * Book API failures, in the reader's language.
 *
 * The server's `detail.message` is English prose written for whoever reads the
 * logs, and relaying it straight into a toast put an English sentence in the
 * middle of a Chinese UI — and, in the revision case, an actively misleading
 * one ("another collaborator" on a book with exactly one reader). The code is
 * the stable part of the contract, so the wording belongs here.
 */

import { BookApiError } from "@/lib/book-api";

type Translate = (key: string, options?: Record<string, unknown>) => string;

const CODE_MESSAGES: Record<string, string> = {
  book_revision_conflict:
    "This book changed while you were working on it. The latest version is loaded — try again.",
  book_revision_required: "Refresh this shared book before editing it.",
  book_paused: "Generation is paused. Continue generating, then try again.",
};

/** The message to show for a failed book operation. */
export function bookErrorMessage(error: unknown, t: Translate): string {
  if (error instanceof BookApiError && error.code) {
    const known = CODE_MESSAGES[error.code];
    if (known) return t(known);
  }
  return error instanceof Error ? error.message : String(error);
}

/** The codes this module has wording for — exported for the test to assert on. */
export const KNOWN_BOOK_ERROR_CODES = Object.keys(CODE_MESSAGES);
