import {
  documentState,
  failureReason,
  fileState,
  isBusy,
  isSelectable,
  knowledgeRef,
  sortBases,
  stateLabel,
} from '../src/features/knowledge/refs';
import type {
  KnowledgeBaseSummary,
  KnowledgeProgress,
} from '../src/services/knowledgeApi';

function base(
  overrides: Partial<KnowledgeBaseSummary> = {},
): KnowledgeBaseSummary {
  return {
    ref: 'user:kb:physics',
    id: 'user:kb:physics',
    name: 'physics',
    description: '',
    status: 'ready',
    isDefault: false,
    documentCount: 0,
    imageCount: 0,
    chunkCount: 0,
    ragInitialized: true,
    needsReindex: false,
    provider: '',
    assigned: false,
    readOnly: false,
    available: true,
    progress: null,
    lastError: '',
    updatedAt: '',
    ...overrides,
  };
}

function progress(overrides: Partial<KnowledgeProgress> = {}): KnowledgeProgress {
  return {
    stage: 'processing_file',
    message: '',
    current: 1,
    total: 3,
    percent: 33,
    fileName: '',
    error: '',
    retryable: false,
    updatedAt: '',
    ...overrides,
  };
}

test('a chat turn carries the same reference the web client would send', () => {
  // A personal base is resolved by name against the local catalogue.
  expect(knowledgeRef({ id: 'user:kb:physics', name: 'physics' })).toBe('physics');
  // An administrator's grant is only addressable by its id.
  expect(
    knowledgeRef({ id: 'admin:kb:shared', name: 'shared', assigned: true }),
  ).toBe('admin:kb:shared');
  // Account- and workspace-scoped bases likewise.
  expect(knowledgeRef({ id: 'account:kb:shared', name: 'shared' })).toBe(
    'account:kb:shared',
  );
  expect(knowledgeRef({ id: 'workspace:team', name: 'team' })).toBe(
    'workspace:team',
  );
  // Without an id there is nothing else to send.
  expect(knowledgeRef({ name: 'notes' })).toBe('notes');
});

test('the file being parsed is the only one that can be called parsing', () => {
  const live = base({
    status: 'processing',
    progress: progress({ fileName: 'chapter 1.pdf' }),
  });
  expect(documentState(live, 'chapter 1.pdf')).toBe('parsing');
  // The server keeps no per-file status, so a queued file borrows the run's
  // state rather than being guessed at.
  expect(documentState(live, 'chapter 2.pdf')).toBe('queued');
  expect(documentState(live)).toBe('queued');
});

test('every stage the tracker writes maps to one visible state', () => {
  const stateOf = (stage: string, fileName = '') =>
    documentState(base({ progress: progress({ stage, fileName }) }), 'a.pdf');
  expect(stateOf('initializing')).toBe('queued');
  expect(stateOf('processing_file', 'a.pdf')).toBe('parsing');
  expect(stateOf('processing_documents')).toBe('indexing');
  expect(stateOf('completed')).toBe('ready');
  expect(stateOf('error')).toBe('failed');
  // An unknown stage falls back to the base's own status, never invented.
  expect(stateOf('some_future_stage')).toBe('ready');
});

test('without a run the base status decides, and an absent base is unknown', () => {
  expect(documentState(base({ status: 'ready' }))).toBe('ready');
  expect(documentState(base({ status: 'needs_reindex' }))).toBe('needs_reindex');
  expect(documentState(base({ status: 'error' }))).toBe('failed');
  expect(documentState(base({ status: 'processing' }))).toBe('queued');
  expect(documentState(base({ status: 'initializing' }))).toBe('queued');
  expect(documentState(base({ status: 'unavailable' }))).toBe('unknown');
  expect(documentState(base({ available: false }))).toBe('unknown');
});

test('only a ready index can be attached to a question', () => {
  expect(isSelectable(base({ status: 'ready' }))).toBe(true);
  // Read-only is about editing, not about retrieval.
  expect(isSelectable(base({ status: 'ready', readOnly: true, assigned: true }))).toBe(
    true,
  );
  expect(isSelectable(base({ status: 'processing' }))).toBe(false);
  expect(isSelectable(base({ status: 'error' }))).toBe(false);
  expect(isSelectable(base({ status: 'needs_reindex' }))).toBe(false);
  expect(isSelectable(base({ available: false }))).toBe(false);
});

test('a busy state is one the app should keep polling', () => {
  expect(isBusy('queued')).toBe(true);
  expect(isBusy('parsing')).toBe(true);
  expect(isBusy('indexing')).toBe(true);
  expect(isBusy('ready')).toBe(false);
  expect(isBusy('failed')).toBe(false);
});

test('a failure explains itself, preferring the run’s own message', () => {
  expect(failureReason(progress({ stage: 'error', error: 'No text layer' }), 'old')).toBe(
    'No text layer',
  );
  expect(failureReason(null, 'Embedding model missing')).toBe(
    'Embedding model missing',
  );
  expect(failureReason(null, '')).toBe('The server did not say why it failed.');
});

test('a file row never claims a readiness the run cannot prove', () => {
  const running = base({
    status: 'processing',
    progress: progress({ stage: 'processing_file', fileName: 'chapter 1.pdf' }),
  });
  // The parser names the file it is reading; only that one is parsing.
  expect(fileState(running, 'chapter 1.pdf')).toBe('parsing');
  expect(fileState(running, 'chapter 2.pdf')).toBe('in_progress');

  // "The run finished" is not "this document was indexed".
  const finished = base({
    status: 'ready',
    progress: progress({ stage: 'completed' }),
  });
  expect(fileState(finished, 'chapter 1.pdf')).toBe('run_done');
  expect(fileState(finished, 'chapter 1.pdf')).not.toBe('ready');
  expect(stateLabel('run_done')).toBe('Run done');

  // A failed run names the file it gave up on; the others are unknown.
  const failed = base({
    status: 'error',
    progress: progress({ stage: 'error', fileName: 'bad.pdf' }),
  });
  expect(fileState(failed, 'bad.pdf')).toBe('failed');
  expect(fileState(failed, 'other.pdf')).toBe('unknown');

  expect(fileState(base({ status: 'needs_reindex' }), 'a.pdf')).toBe('stale');
  expect(stateLabel('stale')).toBe('Re-index needed');
  // A revoked base yields nothing to say about its files.
  expect(fileState(base({ available: false }), 'a.pdf')).toBe('unknown');
});

test('labels are stable copy rather than raw protocol strings', () => {
  expect(stateLabel('needs_reindex')).toBe('Re-index needed');
  expect(stateLabel('parsing')).toBe('Parsing');
});

test('the picker opens with usable bases first, then by name', () => {
  const sorted = sortBases([
    base({ ref: 'c', name: 'zeta', status: 'error' }),
    base({ ref: 'a', name: 'alpha', status: 'ready' }),
    base({ ref: 'b', name: 'beta', status: 'processing' }),
    base({ ref: 'd', name: 'gamma', status: 'ready' }),
  ]);
  expect(sorted.map(item => item.name)).toEqual([
    'alpha',
    'gamma',
    'beta',
    'zeta',
  ]);
});
