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

/**
 * The conversation that was open last, so a relaunch lands where the learner
 * left off instead of on an empty chat. Holds no turn: an in-flight run uses
 * `RecoveryRecord` above.
 */
export interface LastSessionRecord {
  version: 1;
  sessionId: string;
  updatedAt: number;
}

const PREFIX = 'deeptutor:turn-recovery:v1';
const LAST_SESSION_PREFIX = 'deeptutor:last-session:v1';
/** Prune records old enough that no answer is worth chasing. */
const MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;
const generations = new Map<string, number>();
let storageTail: Promise<void> = Promise.resolve();

function enqueue<T>(operation: () => Promise<T>): Promise<T> {
  const result = storageTail.then(operation);
  storageTail = result.then(
    () => {},
    () => {},
  );
  return result;
}

function keyFor(prefix: string, scope: RecoveryScope): string {
  // Each scope part is encoded so a delimiter inside an origin or account id
  // cannot make one namespace collide with another. The prefix stays literal —
  // `clearServer` matches on it.
  const parts = [scope.origin, scope.account, scope.workspace].map(part =>
    encodeURIComponent(part),
  );
  return [prefix, ...parts].join(':');
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
    const raw = await AsyncStorage.getItem(keyFor(PREFIX, scope));
    if (!raw) return null;
    try {
      return recordOf(JSON.parse(raw));
    } catch {
      return null;
    }
  },

  write(scope, record) {
    return AsyncStorage.setItem(keyFor(PREFIX, scope), JSON.stringify(record));
  },

  clear(scope) {
    return AsyncStorage.removeItem(keyFor(PREFIX, scope));
  },

  clearServer(origin) {
    generations.set(origin, (generations.get(origin) ?? 0) + 1);
    return enqueue(async () => {
      const keys = await AsyncStorage.getAllKeys();
      const scoped = [PREFIX, LAST_SESSION_PREFIX].map(
        prefix => `${prefix}:${encodeURIComponent(origin)}:`,
      );
      const stale = keys.filter(key =>
        scoped.some(prefix => key.startsWith(prefix)),
      );
      if (stale.length) await AsyncStorage.multiRemove(stale);
    });
  },
};

/** Bind both pointers to one runtime lifetime and order them with sign-out. */
export function recoveryStoresFor(origin: string) {
  const generation = generations.get(origin) ?? 0;
  const whileCurrent = <T>(operation: () => Promise<T>, fallback: T) =>
    enqueue(() =>
      (generations.get(origin) ?? 0) === generation
        ? operation()
        : Promise.resolve(fallback),
    );
  const bind = <T>(store: {
    read(scope: RecoveryScope): Promise<T | null>;
    write(scope: RecoveryScope, record: T): Promise<void>;
    clear(scope: RecoveryScope): Promise<void>;
  }) => ({
    read: (scope: RecoveryScope) => whileCurrent(() => store.read(scope), null),
    write: (scope: RecoveryScope, record: T) =>
      whileCurrent(() => store.write(scope, record), undefined),
    clear: (scope: RecoveryScope) =>
      whileCurrent(() => store.clear(scope), undefined),
  });
  return {
    recovery: {
      ...bind(turnRecoveryStorage),
      clearServer: turnRecoveryStorage.clearServer,
    },
    lastSession: bind(lastSessionStorage),
  };
}

export interface LastSessionStore {
  read(scope: RecoveryScope): Promise<string | null>;
  write(scope: RecoveryScope, sessionId: string): Promise<void>;
  clear(scope: RecoveryScope): Promise<void>;
}

export const lastSessionStorage: LastSessionStore = {
  async read(scope) {
    const raw = await AsyncStorage.getItem(keyFor(LAST_SESSION_PREFIX, scope));
    if (!raw) return null;
    try {
      const value: unknown = JSON.parse(raw);
      if (!value || typeof value !== 'object') return null;
      const record = value as Partial<LastSessionRecord>;
      const sessionId =
        typeof record.sessionId === 'string' ? record.sessionId.trim() : '';
      const updatedAt =
        typeof record.updatedAt === 'number' ? record.updatedAt : 0;
      if (!sessionId || Date.now() - updatedAt > MAX_AGE_MS) return null;
      return sessionId;
    } catch {
      return null;
    }
  },

  write(scope, sessionId) {
    const record: LastSessionRecord = {
      version: 1,
      sessionId,
      updatedAt: Date.now(),
    };
    return AsyncStorage.setItem(
      keyFor(LAST_SESSION_PREFIX, scope),
      JSON.stringify(record),
    );
  },

  clear(scope) {
    return AsyncStorage.removeItem(keyFor(LAST_SESSION_PREFIX, scope));
  },
};
