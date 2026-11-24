import { ApiClient } from './apiClient';

/**
 * Conversation history is owned by the DeepTutor server. These parsers read the
 * payloads `deeptutor/api/routers/sessions.py` already returns; nothing here
 * invents a second store, and every field the app acts on is validated so an
 * unexpected shape fails loudly instead of rendering a half-loaded transcript.
 */

/** Turn statuses the server actually persists (`turns.status`). */
export type TurnStatus =
  | 'queued'
  | 'running'
  | 'waiting_input'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'rejected'
  | 'idle';

export interface FailedTurnInfo {
  turnId: string;
  error: string;
  retryable: boolean;
}

export interface SessionMessage {
  id: number;
  role: 'user' | 'assistant' | 'system';
  content: string;
  createdAt: number;
  /** Present on a saved user row whose turn failed before any reply existed. */
  failedTurn: FailedTurnInfo | null;
}

export interface SessionSummary {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  messageCount: number;
  lastMessage: string;
  status: TurnStatus;
  /** The turn still holding the session, or "" when the session is free. */
  activeTurnId: string;
}

export interface SessionTurn {
  id: string;
  status: TurnStatus;
  lastSeq: number;
  error: string;
  updatedAt: number;
  retryable: boolean;
}

export interface SessionDetail extends SessionSummary {
  messages: SessionMessage[];
  activeTurns: SessionTurn[];
}

export interface SessionPage {
  sessions: SessionSummary[];
  /** A full page means the caller may ask for the next offset. */
  hasMore: boolean;
}

const TURN_STATUSES: readonly TurnStatus[] = [
  'queued',
  'running',
  'waiting_input',
  'completed',
  'failed',
  'cancelled',
  'rejected',
  'idle',
];

const ACTIVE_STATUSES: readonly TurnStatus[] = ['queued', 'running', 'waiting_input'];

export function isActiveTurnStatus(status: TurnStatus): boolean {
  return ACTIVE_STATUSES.includes(status);
}

function record(value: unknown, what: string): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error(`Expected ${what}`);
  }
  return value as Record<string, unknown>;
}

function text(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback;
}

function count(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function turnStatus(value: unknown): TurnStatus {
  return TURN_STATUSES.find(status => status === value) ?? 'idle';
}

function parseFailedTurn(value: unknown): FailedTurnInfo | null {
  if (!value || typeof value !== 'object') return null;
  const raw = value as Record<string, unknown>;
  const turnId = text(raw.turn_id);
  if (!turnId) return null;
  return {
    turnId,
    error: text(raw.error),
    retryable: raw.retryable === true,
  };
}

function parseMessage(value: unknown): SessionMessage {
  const raw = record(value, 'a session message');
  const role = raw.role;
  if (role !== 'user' && role !== 'assistant' && role !== 'system') {
    throw new Error('Unknown message role');
  }
  const metadata = raw.metadata ? record(raw.metadata, 'message metadata') : {};
  return {
    id: count(raw.id),
    role,
    content: text(raw.content),
    createdAt: count(raw.created_at),
    failedTurn: parseFailedTurn(metadata.orphaned_failed_turn),
  };
}

function parseSummary(value: unknown): SessionSummary {
  const raw = record(value, 'a session');
  const id = text(raw.session_id) || text(raw.id);
  if (!id) throw new Error('Session is missing an id');
  return {
    id,
    title: text(raw.title),
    createdAt: count(raw.created_at),
    updatedAt: count(raw.updated_at),
    messageCount: count(raw.message_count),
    lastMessage: text(raw.last_message),
    status: turnStatus(raw.status),
    activeTurnId: text(raw.active_turn_id),
  };
}

function parseTurn(value: unknown): SessionTurn {
  const raw = record(value, 'a session turn');
  const id = text(raw.id) || text(raw.turn_id);
  if (!id) throw new Error('Turn is missing an id');
  return {
    id,
    status: turnStatus(raw.status),
    lastSeq: count(raw.last_seq),
    error: text(raw.error),
    updatedAt: count(raw.updated_at),
    retryable: raw.retryable === true,
  };
}

function parsePage(value: unknown): SessionSummary[] {
  const raw = record(value, 'a session page');
  if (!Array.isArray(raw.sessions)) throw new Error('Session page has no rows');
  return raw.sessions.map(parseSummary);
}

function parseDetail(value: unknown): SessionDetail {
  const raw = record(value, 'a session');
  if (!Array.isArray(raw.messages)) throw new Error('Session has no transcript');
  const summary = parseSummary(raw);
  const activeTurns = Array.isArray(raw.active_turns)
    ? raw.active_turns.map(parseTurn)
    : [];
  return {
    ...summary,
    messages: raw.messages.map(parseMessage),
    activeTurns,
  };
}

function parseDeleted(value: unknown): void {
  const raw = record(value, 'a deletion acknowledgement');
  if (raw.deleted !== true) throw new Error('The server did not delete the session');
}

const MAX_PAGE = 200;

export type SessionListQuery = {
  limit: number;
  offset: number;
  /**
   * Empty string pins the built-in "general" workspace, matching what the chat
   * socket already sends as `dt_workspace=`.
   */
  workspaceId?: string;
};

export class SessionApi {
  constructor(private readonly client: ApiClient) {}

  async list(query: SessionListQuery, signal?: AbortSignal): Promise<SessionPage> {
    const limit = Math.min(Math.max(1, Math.trunc(query.limit)), MAX_PAGE);
    const offset = Math.max(0, Math.trunc(query.offset));
    const search = new URLSearchParams({
      limit: String(limit),
      offset: String(offset),
    });
    if (query.workspaceId !== undefined) {
      search.set('workspace_id', query.workspaceId);
    }
    const sessions = await this.client.json(
      `/api/sessions?${search.toString()}`,
      parsePage,
      { signal },
    );
    // The list endpoint reports no total, so a short page is the only signal
    // that the caller has reached the end of the index.
    return { sessions, hasMore: sessions.length >= limit };
  }

  get(sessionId: string, signal?: AbortSignal): Promise<SessionDetail> {
    return this.client.json(
      `/api/sessions/${encodeURIComponent(sessionId)}`,
      parseDetail,
      { signal },
    );
  }

  async rename(sessionId: string, title: string): Promise<string> {
    const value = await this.client.json(
      `/api/sessions/${encodeURIComponent(sessionId)}`,
      payload => {
        const raw = record(payload, 'a rename acknowledgement');
        const session = parseSummary(raw.session);
        return session.title;
      },
      { method: 'PATCH', body: { title } },
    );
    return value;
  }

  remove(sessionId: string): Promise<void> {
    return this.client.json(
      `/api/sessions/${encodeURIComponent(sessionId)}`,
      parseDeleted,
      { method: 'DELETE' },
    );
  }
}
