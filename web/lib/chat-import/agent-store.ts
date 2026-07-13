/**
 * Client-side registry of imported "agents". An agent is a *named, scoped*
 * slice of one source folder (a `.claude` or `.codex` home): the user can carve
 * several agents out of the same folder (e.g. "DeepTutor work" vs "research").
 * We keep each agent's `FileSystemDirectoryHandle` in IndexedDB — handles are
 * structured-cloneable but not JSON-serializable — so it can be re-synced later
 * without re-picking the folder (subject to a permission re-grant on a fresh
 * session).
 *
 * The conversations themselves live on the backend; this registry only adds the
 * folder handle, the user-chosen name, and the {@link AgentScope} that decides
 * what a refresh pulls in.
 */

import { SOURCE_LABEL } from "./shared";
import type { AgentScope, ImportSource } from "./types";

export interface ImportAgent {
  /** Stable client id; also written onto each imported session's preferences
   *  (`import.agent_id`) so the backend can group conversations by agent. */
  id: string;
  /** User-editable display name. */
  name: string;
  source: ImportSource;
  folderName: string;
  handle: FileSystemDirectoryHandle;
  /** Which projects/days this agent owns — drives scoped re-sync. */
  scope: AgentScope;
  /** epoch milliseconds. */
  createdAt: number;
  /** epoch milliseconds of the last successful sync. */
  lastSyncAt: number;
}

const DB_NAME = "deeptutor-chat-import";
const STORE = "agents";
// v2: the store key moved from `source` (one agent per source) to a generated
// `id` (many named, scoped agents per source). See `migrate` below.
const DB_VERSION = 2;

interface LegacyAgent {
  source: ImportSource;
  folderName: string;
  handle: FileSystemDirectoryHandle;
  lastSyncAt: number;
}

/** Carry a v1 (source-keyed) record forward as an unrestricted, named agent. */
function migrateLegacy(old: LegacyAgent): ImportAgent {
  return {
    id: `${old.source}-legacy`,
    name: SOURCE_LABEL[old.source] ?? old.source,
    source: old.source,
    folderName: old.folderName,
    handle: old.handle,
    scope: { kind: "all" },
    createdAt: old.lastSyncAt || 0,
    lastSyncAt: old.lastSyncAt || 0,
  };
}

function migrate(
  db: IDBDatabase,
  txn: IDBTransaction,
  oldVersion: number,
): void {
  if (!db.objectStoreNames.contains(STORE)) {
    db.createObjectStore(STORE, { keyPath: "id" });
    return;
  }
  if (oldVersion < 2) {
    // The v1 store was keyed by `source`; IndexedDB can't change a keyPath in
    // place, so read the legacy rows, drop the store, and recreate it keyed by
    // `id`. Reading via a cursor keeps the versionchange transaction alive
    // until we recreate + repopulate inside its final callback.
    const legacy: LegacyAgent[] = [];
    const cursorReq = txn.objectStore(STORE).openCursor();
    cursorReq.onsuccess = () => {
      const cursor = cursorReq.result;
      if (cursor) {
        legacy.push(cursor.value as LegacyAgent);
        cursor.continue();
        return;
      }
      db.deleteObjectStore(STORE);
      const next = db.createObjectStore(STORE, { keyPath: "id" });
      for (const old of legacy) next.put(migrateLegacy(old));
    };
  }
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = (event) => {
      migrate(request.result, request.transaction!, event.oldVersion);
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function tx<T>(
  mode: IDBTransactionMode,
  run: (store: IDBObjectStore) => IDBRequest<T>,
): Promise<T> {
  return openDb().then(
    (db) =>
      new Promise<T>((resolve, reject) => {
        const transaction = db.transaction(STORE, mode);
        const request = run(transaction.objectStore(STORE));
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
        transaction.oncomplete = () => db.close();
      }),
  );
}

/** A fresh, source-namespaced agent id. */
export function newAgentId(source: ImportSource): string {
  const rand =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : Math.random().toString(36).slice(2);
  return `${source}-${rand}`;
}

export async function saveAgent(agent: ImportAgent): Promise<void> {
  await tx("readwrite", (store) => store.put(agent));
}

export async function getAgents(): Promise<ImportAgent[]> {
  try {
    return (
      (await tx<ImportAgent[]>("readonly", (store) => store.getAll())) ?? []
    );
  } catch {
    return [];
  }
}

export async function getAgent(id: string): Promise<ImportAgent | undefined> {
  try {
    return await tx<ImportAgent | undefined>("readonly", (store) =>
      store.get(id),
    );
  } catch {
    return undefined;
  }
}

export async function deleteAgent(id: string): Promise<void> {
  await tx("readwrite", (store) => store.delete(id));
}

/**
 * Ensure read permission on a persisted handle, requesting it on a user gesture
 * if the grant has lapsed (e.g. a new browser session). Returns false if the
 * user declines or the handle is stale.
 */
export async function ensureReadPermission(
  handle: FileSystemDirectoryHandle,
): Promise<boolean> {
  const opts = { mode: "read" as const };
  try {
    if ((await handle.queryPermission?.(opts)) === "granted") return true;
    return (await handle.requestPermission?.(opts)) === "granted";
  } catch {
    return false;
  }
}
