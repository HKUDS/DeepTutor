import type { KnowledgeBaseSummary, KnowledgeProgress } from '../../services/knowledgeApi';

/**
 * The reference a chat turn should carry for a knowledge base.
 *
 * This mirrors the web client (`web/lib/knowledge-helpers.ts`): a base shared by
 * an administrator is addressed by its id, an account- or workspace-scoped base
 * likewise, and an ordinary personal base by its name — which is what the turn
 * pipeline resolves against the local catalogue.
 */
export function knowledgeRef(kb: {
  id?: string;
  name: string;
  assigned?: boolean;
}): string {
  if (kb.assigned && kb.id) return kb.id;
  if (kb.id?.startsWith('account:kb:') || kb.id?.startsWith('workspace:')) {
    return kb.id;
  }
  return kb.name;
}

/**
 * What the app can say about a knowledge base's own processing state.
 *
 * The server reports progress for the *run*, not per document, so this is used
 * for the base's badge and for deciding whether a base can be attached to a
 * turn. File rows use `fileState` below, which does not claim more than the run
 * can prove.
 */
export type DocumentState =
  | 'queued'
  | 'parsing'
  | 'indexing'
  | 'ready'
  | 'needs_reindex'
  | 'failed'
  | 'unknown';

export function documentState(
  kb: Pick<
    KnowledgeBaseSummary,
    'status' | 'available' | 'progress'
  >,
  fileName?: string,
): DocumentState {
  if (kb.available === false) return 'unknown';
  const progress = kb.progress;
  if (progress) {
    switch (progress.stage) {
      case 'initializing':
        return 'queued';
      case 'processing_file':
        return fileName && progress.fileName === fileName ? 'parsing' : 'queued';
      case 'processing_documents':
        return 'indexing';
      case 'completed':
        return 'ready';
      case 'error':
        return 'failed';
      default:
        break;
    }
  }
  switch (kb.status) {
    case 'ready':
      return 'ready';
    case 'needs_reindex':
      return 'needs_reindex';
    case 'error':
      return 'failed';
    case 'processing':
    case 'initializing':
      return 'queued';
    default:
      return 'unknown';
  }
}

/**
 * What the app can honestly say about one document's processing state.
 *
 * `ProgressTracker` describes a run and names the single file it is parsing
 * right now; it persists no per-file result. A file row therefore cannot reuse
 * the base's `ready`: "the last run finished" is not "this document was
 * indexed". The labels below say only what the run can prove.
 */
export type FileState =
  /** This file is the one the parser is reading right now. */
  | 'parsing'
  /** A run is active and this file is part of it, but not the current one. */
  | 'in_progress'
  /** The base's last run finished; the server does not report per file. */
  | 'run_done'
  /** The run failed on this file. */
  | 'failed'
  /** The index no longer matches the documents. */
  | 'stale'
  /** No run information exists for the base, or it cannot be read. */
  | 'unknown';

export function fileState(
  kb: Pick<KnowledgeBaseSummary, 'status' | 'available' | 'progress'>,
  fileName: string,
): FileState {
  if (kb.available === false) return 'unknown';
  const progress = kb.progress;
  if (progress) {
    switch (progress.stage) {
      case 'initializing':
        return 'in_progress';
      case 'processing_file':
        return progress.fileName === fileName ? 'parsing' : 'in_progress';
      case 'processing_documents':
        // Documents are being indexed, but the tracker does not say which one.
        return 'in_progress';
      case 'completed':
        return 'run_done';
      case 'error':
        // The run names the file it gave up on; the others were not necessarily
        // reached, so they are not called failed or done.
        return progress.fileName && progress.fileName === fileName
          ? 'failed'
          : 'unknown';
      default:
        break;
    }
  }
  switch (kb.status) {
    case 'ready':
      return 'run_done';
    case 'needs_reindex':
      return 'stale';
    case 'processing':
    case 'initializing':
      return 'in_progress';
    default:
      return 'unknown';
  }
}

const LABELS: Record<DocumentState | FileState, string> = {
  queued: 'Queued',
  parsing: 'Parsing',
  indexing: 'Indexing',
  ready: 'Ready',
  needs_reindex: 'Re-index needed',
  failed: 'Failed',
  unknown: 'Unknown',
  in_progress: 'In progress',
  run_done: 'Run done',
  stale: 'Re-index needed',
};

export function stateLabel(state: DocumentState | FileState): string {
  return LABELS[state];
}

export function isBusy(state: DocumentState): boolean {
  return state === 'queued' || state === 'parsing' || state === 'indexing';
}

/** Whether a badge state means work is happening rather than settled. */
export function isActiveState(state: DocumentState | FileState): boolean {
  return (
    state === 'queued' ||
    state === 'parsing' ||
    state === 'indexing' ||
    state === 'in_progress'
  );
}

/**
 * Whether a knowledge base can be attached to a chat turn.
 *
 * Read-only (administrator-granted) bases are usable for retrieval — only
 * editing is refused — so they stay selectable. A base whose index is not
 * ready is not, because a turn would silently answer without it.
 */
export function isSelectable(kb: KnowledgeBaseSummary): boolean {
  return kb.available !== false && documentState(kb) === 'ready';
}

/**
 * The line shown under a failed run. `progress.error` is the parser's own
 * message; `metadata.last_error` is the durable copy from a previous run.
 */
export function failureReason(
  progress: KnowledgeProgress | null,
  lastError: string,
): string {
  return progress?.error || lastError || 'The server did not say why it failed.';
}

/** Sort with ready bases first, then by name, so the picker opens usefully. */
export function sortBases(
  bases: readonly KnowledgeBaseSummary[],
): KnowledgeBaseSummary[] {
  const rank = (state: DocumentState) =>
    state === 'ready' ? 0 : isBusy(state) ? 1 : 2;
  return [...bases].sort((left, right) => {
    const delta =
      rank(documentState(left)) - rank(documentState(right));
    if (delta !== 0) return delta;
    return left.name.localeCompare(right.name);
  });
}
