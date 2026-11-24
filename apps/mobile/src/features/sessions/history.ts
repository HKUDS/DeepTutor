import {
  isActiveTurnStatus,
  type SessionDetail,
  type SessionMessage,
  type SessionTurn,
  type TurnStatus,
} from '../../services/sessionApi';

/** One question and the reply it produced, as the transcript renders them. */
export interface ChatExchange {
  id: string;
  question: string;
  answer: string;
  /** Failure copy for a turn that saved the question but never replied. */
  failed: string | null;
  retryable: boolean;
}

const DEFAULT_FAILURE = 'This response did not finish.';

/**
 * A stable render key per row. The server normally supplies one; when it does
 * not, the position in the transcript is the only thing left, and a positional
 * key is still better than every row collapsing onto the same one.
 */
function keyOf(message: SessionMessage, index: number): string {
  return message.id ? `m${message.id}` : `m#${index}`;
}

export function toExchanges(messages: readonly SessionMessage[]): ChatExchange[] {
  const exchanges: ChatExchange[] = [];
  // The row a later assistant message may still attach to. Only the newest
  // user row can own a reply, so a stale cursor is never reused.
  let open: ChatExchange | null = null;
  let index = -1;

  for (const message of messages) {
    index += 1;
    if (message.role === 'system') continue;
    if (message.role === 'user') {
      const exchange: ChatExchange = {
        id: keyOf(message, index),
        question: message.content,
        answer: '',
        failed: message.failedTurn
          ? message.failedTurn.error || DEFAULT_FAILURE
          : null,
        retryable: message.failedTurn?.retryable === true,
      };
      exchanges.push(exchange);
      open = exchange;
      continue;
    }
    if (open && !open.answer && !open.failed) {
      open.answer = message.content;
      // A reply closes the pair; a second assistant row becomes its own entry.
      open = null;
      continue;
    }
    exchanges.push({
      id: keyOf(message, index),
      question: '',
      answer: message.content,
      failed: null,
      retryable: false,
    });
  }
  return exchanges;
}

/**
 * The turn the server still considers live for this session, newest first.
 * Absent when the transcript is settled — the app must then trust the saved
 * messages instead of replaying a finished turn.
 */
export function liveTurn(detail: SessionDetail): SessionTurn | null {
  const live = detail.activeTurns
    .filter(turn => isActiveTurnStatus(turn.status))
    .sort((left, right) => right.updatedAt - left.updatedAt);
  return live[0] ?? null;
}

export type RecoveredTurn =
  | { kind: 'live'; turn: SessionTurn }
  | { kind: 'settled'; status: TurnStatus }
  | { kind: 'missing' };

/**
 * Decide how to resume a persisted turn from the server's own record of it.
 *
 * The persisted snapshot is only a pointer: the server decides whether the run
 * is still going, already ended, or was deleted along with its conversation.
 */
export function resolveTurn(
  detail: SessionDetail | null,
  turnId: string,
): RecoveredTurn {
  if (!detail) return { kind: 'missing' };
  const tracked = detail.activeTurns.find(turn => turn.id === turnId);
  if (tracked) {
    return isActiveTurnStatus(tracked.status)
      ? { kind: 'live', turn: tracked }
      : { kind: 'settled', status: tracked.status };
  }
  const live = liveTurn(detail);
  if (live) return { kind: 'live', turn: live };
  // The turn is no longer in the active set: its outcome is whatever the
  // session's last turn recorded, or a plain end when nothing is left.
  return { kind: 'settled', status: detail.status };
}
