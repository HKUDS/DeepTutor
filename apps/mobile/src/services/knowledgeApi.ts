import { ApiClient, ApiError } from './apiClient';

/**
 * Knowledge bases are owned by the DeepTutor server. These parsers read what
 * `deeptutor/api/routers/knowledge.py` already returns; the app keeps no second
 * catalogue, so every screen re-reads the server's copy.
 *
 * Two identities travel over the wire. `id` is the resource handle the server
 * resolves (`user:kb:<name>`, `account:kb:<name>`, …) and is what paths carry;
 * `name` is what a knowledge base is called on disk and in a chat turn's
 * `knowledge_bases` for ordinary user bases. `ref` below is the id used for
 * requests, while `chatRef` answers the different question of what to send to
 * `start_turn` — see `features/knowledge/refs.ts`.
 */

/** Statuses `KnowledgeBaseManager.get_info` can report. */
export type KnowledgeBaseStatus =
  | 'ready'
  | 'needs_reindex'
  | 'processing'
  | 'initializing'
  | 'error'
  | 'unknown'
  | 'unavailable';

/** Stages `ProgressTracker` writes. */
export type ProgressStage =
  | 'initializing'
  | 'processing_documents'
  | 'processing_file'
  | 'completed'
  | 'error';

export interface KnowledgeProgress {
  stage: ProgressStage | string;
  message: string;
  /** Files finished so far, and how many the run covers. */
  current: number;
  total: number;
  percent: number;
  /** The file being parsed right now, when the stage names one. */
  fileName: string;
  error: string;
  retryable: boolean;
  updatedAt: string;
}

export interface KnowledgeBaseSummary {
  /** Server handle used in request paths. */
  ref: string;
  id: string;
  name: string;
  description: string;
  status: KnowledgeBaseStatus | string;
  isDefault: boolean;
  documentCount: number;
  imageCount: number;
  chunkCount: number;
  ragInitialized: boolean;
  needsReindex: boolean;
  provider: string;
  /** An administrator granted this base to the current account. */
  assigned: boolean;
  /** Assigned bases are served read-only. */
  readOnly: boolean;
  /** False when a grant was revoked but is still listed. */
  available: boolean;
  progress: KnowledgeProgress | null;
  /** `metadata.last_error`, present when indexing failed. */
  lastError: string;
  updatedAt: string;
}

export interface KnowledgeFileEntry {
  /** POSIX path relative to the base's `raw/` directory. */
  name: string;
  type: 'file' | 'folder';
  size: number;
  /** Seconds since the epoch, as the server reports `st_mtime`. */
  modified: number;
  mimeType: string;
}

export interface UploadPolicy {
  /** Lower-case extensions including the dot, e.g. `.pdf`. */
  extensions: string[];
  /** Ready-to-use `accept` list, kept for parity with the web client. */
  accept: string;
  maxFileSizeBytes: number;
  /** True when the active parser accepts anything and `extensions` is empty. */
  allowAnyExtension: boolean;
}

/** One file the user picked, in the shape React Native multipart expects. */
export interface PickedFile {
  uri: string;
  name: string;
  /** Absent when the platform's picker could not report a size. */
  size?: number;
  mimeType: string;
}

const ACTIVE_STATUSES = new Set(['processing', 'initializing']);
const TERMINAL_STAGES = new Set(['completed', 'error']);

export function isLiveStatus(status: string): boolean {
  return ACTIVE_STATUSES.has(status);
}

export function isTerminalProgress(
  progress: KnowledgeProgress | null,
): boolean {
  return !progress || TERMINAL_STAGES.has(String(progress.stage));
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

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function parseProgress(value: unknown): KnowledgeProgress | null {
  if (!value || typeof value !== 'object') return null;
  const raw = value as Record<string, unknown>;
  const stage = text(raw.stage);
  if (!stage) return null;
  const total = count(raw.total);
  const current = count(raw.current);
  return {
    stage,
    message: text(raw.message),
    current,
    total,
    // The server already computes this; do not re-derive a percentage the
    // uploader would then have to be trusted for.
    percent: Math.max(0, Math.min(100, count(raw.progress_percent))),
    fileName: text(raw.file_name),
    error: text(raw.error),
    retryable: raw.retryable === true,
    updatedAt: text(raw.timestamp),
  };
}

function parseSummary(value: unknown): KnowledgeBaseSummary {
  const raw = record(value, 'a knowledge base');
  const name = text(raw.name).trim();
  const id = text(raw.id);
  if (!name && !id) throw new Error('Knowledge base is missing a name');
  const statistics =
    raw.statistics && typeof raw.statistics === 'object'
      ? (raw.statistics as Record<string, unknown>)
      : {};
  const metadata =
    raw.metadata && typeof raw.metadata === 'object'
      ? (raw.metadata as Record<string, unknown>)
      : {};
  // Status and progress are repeated inside `statistics` for the web client's
  // older readers; the top-level copy wins when both exist.
  const status =
    text(raw.status) || text(statistics.status) || 'unknown';
  return {
    ref: id || name,
    id,
    name: name || id,
    description: text(metadata.description),
    status,
    isDefault: raw.is_default === true,
    documentCount: count(statistics.raw_documents),
    imageCount: count(statistics.images),
    chunkCount: count(statistics.content_lists),
    ragInitialized: statistics.rag_initialized === true,
    needsReindex:
      raw.needs_reindex === true || statistics.needs_reindex === true,
    provider: text(metadata.rag_provider) || text(statistics.rag_provider),
    assigned: raw.assigned === true,
    readOnly: raw.read_only === true,
    available: raw.available !== false,
    progress: parseProgress(raw.progress) ?? parseProgress(statistics.progress),
    lastError: text(metadata.last_error),
    updatedAt: text(metadata.last_updated) || text(metadata.created_at),
  };
}

function parseList(value: unknown): KnowledgeBaseSummary[] {
  if (!Array.isArray(value)) throw new Error('Expected a knowledge base list');
  return value.map(parseSummary);
}

function parseFiles(value: unknown): KnowledgeFileEntry[] {
  const raw = record(value, 'a file list');
  return list(raw.files).map(entry => {
    const file = record(entry, 'a file');
    const name = text(file.name);
    if (!name) throw new Error('File entry is missing a name');
    return {
      name,
      type: file.type === 'folder' ? 'folder' : 'file',
      size: count(file.size),
      modified: count(file.modified),
      mimeType: text(file.mime_type),
    };
  });
}

function parsePolicy(value: unknown): UploadPolicy {
  const raw = record(value, 'the upload policy');
  return {
    extensions: list(raw.extensions)
      .map(extension => text(extension).toLowerCase())
      .filter(Boolean),
    accept: text(raw.accept),
    maxFileSizeBytes: count(raw.max_file_size_bytes),
    allowAnyExtension: raw.allow_any_extension === true,
  };
}

function parseCreated(value: unknown): string {
  const raw = record(value, 'a creation acknowledgement');
  const name = text(raw.name);
  if (!name) throw new Error('The server did not name the new knowledge base');
  return name;
}

function parseDeleted(value: unknown): void {
  const raw = record(value, 'a deletion acknowledgement');
  if (!text(raw.message)) {
    throw new Error('The server did not confirm the deletion');
  }
}

function parseOk(value: unknown): void {
  const raw = record(value, 'an acknowledgement');
  if (text(raw.status) !== 'ok' && raw.status !== 'success') {
    throw new Error('The server did not confirm the change');
  }
}

/** Path segments are encoded individually so a nested file keeps its folders. */
function encodePath(path: string): string {
  return path
    .split('/')
    .filter(segment => segment.length > 0)
    .map(segment => encodeURIComponent(segment))
    .join('/');
}

export class KnowledgeApi {
  constructor(private readonly client: ApiClient) {}

  list(signal?: AbortSignal): Promise<KnowledgeBaseSummary[]> {
    return this.client.json('/api/knowledge-bases', parseList, { signal });
  }

  get(ref: string, signal?: AbortSignal): Promise<KnowledgeBaseSummary> {
    return this.client.json(
      `/api/knowledge-bases/${encodeURIComponent(ref)}`,
      parseSummary,
      { signal },
    );
  }

  /**
   * Create an empty knowledge base. The endpoint is multipart even without
   * files, so `name` is a form field rather than JSON.
   */
  create(name: string): Promise<string> {
    const form = new FormData();
    form.append('name', name);
    return this.client.form('/api/knowledge-bases', form, parseCreated);
  }

  /**
   * Only the description is editable. A knowledge base's name is its directory
   * and its route, and the server exposes no rename operation.
   */
  async updateDescription(ref: string, description: string): Promise<void> {
    await this.client.json(
      `/api/knowledge-bases/${encodeURIComponent(ref)}/config`,
      payload => {
        const raw = record(payload, 'a config acknowledgement');
        if (text(raw.status) !== 'success') {
          throw new Error('The server did not save the description');
        }
      },
      { method: 'PUT', body: { description } },
    );
  }

  remove(ref: string): Promise<void> {
    return this.client.json(
      `/api/knowledge-bases/${encodeURIComponent(ref)}`,
      parseDeleted,
      { method: 'DELETE' },
    );
  }

  async files(
    ref: string,
    signal?: AbortSignal,
  ): Promise<KnowledgeFileEntry[]> {
    return this.client.json(
      `/api/knowledge-bases/${encodeURIComponent(ref)}/files`,
      parseFiles,
      { signal },
    );
  }

  removeFile(ref: string, name: string): Promise<void> {
    return this.client.json(
      `/api/knowledge-bases/${encodeURIComponent(ref)}/files/${encodePath(name)}`,
      parseOk,
      { method: 'DELETE' },
    );
  }

  progress(
    ref: string,
    signal?: AbortSignal,
  ): Promise<KnowledgeProgress | null> {
    return this.client.json(
      `/api/knowledge-bases/${encodeURIComponent(ref)}/progress`,
      payload => {
        const raw = record(payload, 'a progress report');
        // An untouched base answers `{status: "not_started"}`.
        return parseProgress(raw);
      },
      { signal },
    );
  }

  /** Re-run a base whose last initialisation failed. */
  async retry(ref: string): Promise<void> {
    await this.client.json(
      `/api/knowledge-bases/${encodeURIComponent(ref)}/retry`,
      payload => record(payload, 'a retry acknowledgement'),
      { method: 'POST' },
    );
  }

  policy(signal?: AbortSignal): Promise<UploadPolicy> {
    return this.client.json(
      '/api/knowledge-bases/supported-file-types',
      parsePolicy,
      { signal },
    );
  }
}

/** Turn an API failure into copy a learner can act on. */
export function messageFor(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.kind === 'unauthorized') {
      return 'Sign in again to manage your knowledge bases.';
    }
    if (error.kind === 'timeout') {
      return 'The server took too long to answer. Try again.';
    }
    if (error.kind === 'network') {
      return 'Could not reach the server. Check your connection.';
    }
    if (error.status === 404) {
      return 'This knowledge base no longer exists on the server.';
    }
    if (error.status === 409) {
      return 'The server refused this change in the base’s current state.';
    }
    if (error.status === 403) {
      return 'This knowledge base is read-only for your account.';
    }
  }
  return 'The server could not complete that request.';
}
