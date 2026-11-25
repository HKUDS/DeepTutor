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
 * What the app can honestly say about a document's processing state.
 *
 * The server reports progress for the *run*, and names the single file it is
 * parsing right now. It does not persist a per-file status, so a file that is
 * not the current one borrows the run's state. `ready` therefore means "the
 * base's last run finished", not "this file was verified".
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

const LABELS: Record<DocumentState, string> = {
  queued: 'Queued',
  parsing: 'Parsing',
  indexing: 'Indexing',
  ready: 'Ready',
  needs_reindex: 'Re-index needed',
  failed: 'Failed',
  unknown: 'Unknown',
};

export function stateLabel(state: DocumentState): string {
  return LABELS[state];
}

export function isBusy(state: DocumentState): boolean {
  return state === 'queued' || state === 'parsing' || state === 'indexing';
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
