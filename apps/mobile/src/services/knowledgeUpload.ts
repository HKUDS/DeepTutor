import { ApiError } from './apiClient';
import type { PickedFile, UploadPolicy } from './knowledgeApi';

/**
 * Multipart upload with real transfer progress.
 *
 * `fetch` cannot report upload progress, and a timer that fakes a percentage
 * would be a lie, so this uses `XMLHttpRequest`: React Native reports the bytes
 * the platform has actually written to the socket through `upload.onprogress`.
 *
 * A knowledge base upload is fire-and-forget on the server: the response names
 * a `task_id` and parsing continues there. Cancelling the request therefore
 * cancels *this* transfer, not the server's parsing run, and is reported that
 * way in the UI.
 */

export interface UploadResult {
  taskId: string;
  /** Names the server stored, relative to the base's `raw/` directory. */
  files: string[];
  message: string;
}

export interface UploadHandle {
  promise: Promise<UploadResult>;
  /** Abort the transfer. The server keeps whatever bytes it already received. */
  abort(): void;
}

/** No progress for this long means the connection is dead, not slow. */
const STALL_TIMEOUT_MS = 60_000;

export interface UploadRequest {
  origin: string;
  /** Server handle for the knowledge base. */
  ref: string;
  files: readonly PickedFile[];
  onProgress?: (loaded: number, total: number) => void;
  signal?: AbortSignal;
}

function parseUploadResult(value: unknown): UploadResult {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new ApiError('invalid-response', 'The server did not accept the upload.');
  }
  const raw = value as Record<string, unknown>;
  const files = Array.isArray(raw.files)
    ? raw.files.filter((name): name is string => typeof name === 'string')
    : [];
  return {
    taskId: typeof raw.task_id === 'string' ? raw.task_id : '',
    files,
    message: typeof raw.message === 'string' ? raw.message : '',
  };
}

export function uploadKnowledgeFiles({
  origin,
  ref,
  files,
  onProgress,
  signal,
}: UploadRequest): UploadHandle {
  const url = `${origin}/api/knowledge-bases/${encodeURIComponent(ref)}/upload`;
  const form = new FormData();
  for (const file of files) {
    // React Native's FormData takes a `{uri, name, type}` descriptor and streams
    // the file from disk; the bytes never pass through JavaScript.
    form.append('files', {
      uri: file.uri,
      name: file.name,
      type: file.mimeType || 'application/octet-stream',
    } as unknown as Blob);
  }

  const xhr = new XMLHttpRequest();
  let settled = false;
  let stall: ReturnType<typeof setTimeout> | undefined;
  let resolveResult: (value: UploadResult) => void = () => {};
  let rejectResult: (reason: ApiError) => void = () => {};

  const promise = new Promise<UploadResult>((resolve, reject) => {
    resolveResult = resolve;
    rejectResult = reject;
  });

  const cleanup = () => {
    if (stall) clearTimeout(stall);
    signal?.removeEventListener('abort', onAbortSignal);
  };
  const succeed = (value: UploadResult) => {
    if (settled) return;
    settled = true;
    cleanup();
    resolveResult(value);
  };
  const fail = (kind: ApiError['kind'], message: string, status?: number) => {
    if (settled) return;
    settled = true;
    cleanup();
    rejectResult(new ApiError(kind, message, status));
  };
  const armStall = () => {
    if (stall) clearTimeout(stall);
    stall = setTimeout(
      () =>
        fail(
          'timeout',
          'The upload stopped making progress. Check your connection and try again.',
        ),
      STALL_TIMEOUT_MS,
    );
  };
  const abortTransfer = () => {
    if (settled) return;
    // `abort` fires `onabort`, which settles the promise as aborted; settling
    // here first would race with that handler and mislabel a cancel as success.
    xhr.abort();
  };
  const onAbortSignal = () => abortTransfer();

  if (signal?.aborted) {
    fail('aborted', 'The upload was cancelled.');
    return { promise, abort: abortTransfer };
  }
  signal?.addEventListener('abort', onAbortSignal);

  xhr.open('POST', url, true);
  // The session is an HttpOnly cookie; the platform cookie jar supplies it.
  xhr.withCredentials = true;
  xhr.setRequestHeader('Accept', 'application/json');
  // The platform sets the multipart boundary itself.
  xhr.timeout = 0;

  xhr.upload.onprogress = event => {
    if (!event.lengthComputable) return;
    armStall();
    onProgress?.(event.loaded, event.total);
  };

  xhr.onload = () => {
    const status = xhr.status;
    if (status === 401) {
      fail('unauthorized', 'Sign-in is required.', 401);
      return;
    }
    if (status >= 300 && status < 400) {
      fail('redirect', 'Enter the final address of the DeepTutor server.', status);
      return;
    }
    if (status < 200 || status >= 300) {
      fail('http', `The server returned HTTP ${status}.`, status);
      return;
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(xhr.responseText) as unknown;
    } catch {
      fail('invalid-response', 'The server did not accept the upload.');
      return;
    }
    try {
      succeed(parseUploadResult(parsed));
    } catch (error) {
      if (error instanceof ApiError) fail(error.kind, error.message, error.status);
      else fail('invalid-response', 'The server did not accept the upload.');
    }
  };
  xhr.onerror = () =>
    fail('network', 'Could not reach the server. Check your connection.');
  xhr.onabort = () => fail('aborted', 'The upload was cancelled.');
  xhr.ontimeout = () =>
    fail('timeout', 'The upload took too long. Try again.');

  armStall();
  try {
    xhr.send(form);
  } catch {
    fail('network', 'Could not start the upload.');
  }

  return { promise, abort: abortTransfer };
}

export interface RejectedFile {
  name: string;
  reason: string;
}

export interface FileValidation {
  accepted: PickedFile[];
  rejected: RejectedFile[];
}

/** Strip any directory part a picker may have kept; the batch uploads flat. */
function baseName(name: string): string {
  const parts = name.split(/[\\/]/).filter(Boolean);
  return parts.length ? parts[parts.length - 1] : '';
}

function extensionOf(name: string): string {
  const index = name.lastIndexOf('.');
  return index > 0 ? name.slice(index).toLowerCase() : '';
}

/**
 * Client-side pre-flight against the server's own policy.
 *
 * This is a courtesy, not a security boundary: the server re-validates every
 * batch, and its answer wins.
 */
export function validatePickedFiles(
  files: readonly PickedFile[],
  policy: UploadPolicy | null,
): FileValidation {
  const allowed = new Set(policy?.extensions ?? []);
  // The upload route also accepts `.zip` as a container and validates its
  // members during extraction, but does not advertise it in the policy.
  allowed.add('.zip');
  const max = policy?.maxFileSizeBytes ?? 0;
  // With no policy in hand there is nothing to check against; the server's own
  // limit is the authority either way, so the pick is not blocked here.
  const checkExtension = policy !== null && !policy.allowAnyExtension;
  const accepted: PickedFile[] = [];
  const rejected: RejectedFile[] = [];

  for (const file of files) {
    const name = baseName(file.name);
    if (!name || name === '.' || name === '..') {
      rejected.push({ name: file.name, reason: 'This file has no usable name.' });
      continue;
    }
    // An unknown size is not an error: some providers report none, and the
    // server's own limit still applies.
    if (file.size !== undefined && file.size <= 0) {
      rejected.push({ name, reason: 'This file is empty.' });
      continue;
    }
    if (file.size !== undefined && max > 0 && file.size > max) {
      rejected.push({
        name,
        reason: `Larger than the ${formatBytes(max)} limit on this server.`,
      });
      continue;
    }
    const extension = extensionOf(name);
    if (checkExtension && !allowed.has(extension)) {
      rejected.push({
        name,
        reason: extension
          ? `This server does not accept ${extension} files.`
          : 'This server needs a file extension it recognises.',
      });
      continue;
    }
    accepted.push({
      uri: file.uri,
      name,
      size: file.size,
      mimeType: file.mimeType || mimeTypeFor(extension),
    });
  }

  return { accepted, rejected };
}

const MIME_TYPES: Record<string, string> = {
  '.pdf': 'application/pdf',
  '.txt': 'text/plain',
  '.md': 'text/markdown',
  '.markdown': 'text/markdown',
  '.doc': 'application/msword',
  '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  '.ppt': 'application/vnd.ms-powerpoint',
  '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  '.xls': 'application/vnd.ms-excel',
  '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  '.csv': 'text/csv',
  '.json': 'application/json',
  '.html': 'text/html',
  '.htm': 'text/html',
  '.epub': 'application/epub+zip',
  '.zip': 'application/zip',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.webp': 'image/webp',
};

export function mimeTypeFor(extension: string): string {
  return MIME_TYPES[extension] ?? 'application/octet-stream';
}

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const rounded = value >= 10 || unit === 0 ? Math.round(value) : value.toFixed(1);
  return `${rounded} ${units[unit]}`;
}
