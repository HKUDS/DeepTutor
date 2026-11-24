import AsyncStorage from '@react-native-async-storage/async-storage';

/**
 * The minimum needed to ask the server what happened to an in-flight turn.
 *
 * Nothing here is a credential: no cookie, password or model key is ever
 * written, and the record is scoped by server, account and workspace so one
 * account's run can never be resumed under another.
 */
export interface RecoveryRecord {
  version: 1;
  sessionId: string;
  turnId: string;
  /** The id the client submitted, reused to recognise a duplicate submit. */
  clientSubmissionId: string;
  /** Last event sequence the app applied before it lost the connection. */
  lastSeq: number;
  status:
    | 'submitting'
    | 'running'
    | 'waiting_for_input'
    | 'cancelling'
    | 'recovering';
  updatedAt: number;
}

export interface RecoveryScope {
  origin: string;
  /** Stable account identity from `/api/auth/status`; `local-admin` when open. */
  account: string;
  /** "" is the built-in general workspace, matching the chat socket's scope. */
  workspace: string;
}

const PREFIX = 'deeptutor:turn-recovery:v1';
/** Prune records old enough that no answer is worth chasing. */
const MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;

function keyFor(scope: RecoveryScope): string {
  // Each scope part is encoded so a delimiter inside an origin or account id
  // cannot make one namespace collide with another. The prefix stays literal —
  // `clearServer` matches on it.
  const parts = [scope.origin, scope.account, scope.workspace].map(part =>
    encodeURIComponent(part),
  );
  return [PREFIX, ...parts].join(':');
}

function recordOf(value: unknown): RecoveryRecord | null {
  if (!value || typeof value !== 'object') return null;
  const raw = value as Record<string, unknown>;
  if (raw.version !== 1) return null;
  const sessionId = typeof raw.sessionId === 'string' ? raw.sessionId : '';
  const turnId = typeof raw.turnId === 'string' ? raw.turnId : '';
  const clientSubmissionId =
    typeof raw.clientSubmissionId === 'string' ? raw.clientSubmissionId : '';
  const status = raw.status;
  const lastSeq = raw.lastSeq;
  const updatedAt = raw.updatedAt;
  if (!sessionId || !turnId || !clientSubmissionId) return null;
  if (
    status !== 'submitting' &&
    status !== 'running' &&
    status !== 'waiting_for_input' &&
    status !== 'cancelling' &&
    status !== 'recovering'
  )
    return null;
  if (typeof lastSeq !== 'number' || !Number.isFinite(lastSeq) || lastSeq < 0)
    return null;
  if (typeof updatedAt !== 'number' || !Number.isFinite(updatedAt)) return null;
  if (Date.now() - updatedAt > MAX_AGE_MS) return null;
  return {
    version: 1,
    sessionId,
    turnId,
    clientSubmissionId,
    lastSeq: Math.trunc(lastSeq),
    status,
    updatedAt,
  };
}

export interface TurnRecoveryStore {
  read(scope: RecoveryScope): Promise<RecoveryRecord | null>;
  write(scope: RecoveryScope, record: RecoveryRecord): Promise<void>;
  clear(scope: RecoveryScope): Promise<void>;
  /** Drop every record for a server — used when signing out of it. */
  clearServer(origin: string): Promise<void>;
}

export const turnRecoveryStorage: TurnRecoveryStore = {
  async read(scope) {
    const raw = await AsyncStorage.getItem(keyFor(scope));
    if (!raw) return null;
    try {
      return recordOf(JSON.parse(raw));
    } catch {
      return null;
    }
  },

  write(scope, record) {
    return AsyncStorage.setItem(keyFor(scope), JSON.stringify(record));
  },

  clear(scope) {
    return AsyncStorage.removeItem(keyFor(scope));
  },

  async clearServer(origin) {
    const keys = await AsyncStorage.getAllKeys();
    const prefix = `${PREFIX}:${encodeURIComponent(origin)}:`;
    const stale = keys.filter(key => key.startsWith(prefix));
    if (stale.length) await AsyncStorage.multiRemove(stale);
  },
};
