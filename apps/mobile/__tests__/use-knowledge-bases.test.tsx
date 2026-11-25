import { act, renderHook, waitFor } from '@testing-library/react-native';

import { useKnowledgeBases } from '../src/features/knowledge/useKnowledgeBases';
import { ApiError } from '../src/services/apiClient';
import type {
  KnowledgeApi,
  KnowledgeBaseSummary,
} from '../src/services/knowledgeApi';

function base(name: string, overrides: Partial<KnowledgeBaseSummary> = {}) {
  return {
    ref: `user:kb:${name}`,
    id: `user:kb:${name}`,
    name,
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
  } satisfies KnowledgeBaseSummary;
}

function fakeApi(list: jest.Mock) {
  return { list } as unknown as KnowledgeApi;
}

function deferred<T>() {
  let resolve: (value: T) => void = () => {};
  let reject: (reason: unknown) => void = () => {};
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}

test('reads the whole catalogue once and reports when it is usable', async () => {
  const list = jest.fn().mockResolvedValue([base('physics')]);
  const { result } = renderHook(() => useKnowledgeBases(fakeApi(list)));
  expect(result.current.status).toBe('loading');
  await waitFor(() => expect(result.current.status).toBe('ready'));
  expect(result.current.bases.map(item => item.name)).toEqual(['physics']);
  expect(list).toHaveBeenCalledTimes(1);
});

test('without a server there is nothing to ask, so it stays loading', async () => {
  const { result } = renderHook(() => useKnowledgeBases(null));
  expect(result.current.status).toBe('loading');
  expect(result.current.bases).toEqual([]);
});

test('a first-load failure is reported instead of looking like an empty list', async () => {
  const list = jest
    .fn()
    .mockRejectedValue(new ApiError('network', 'offline'));
  const { result } = renderHook(() => useKnowledgeBases(fakeApi(list)));
  await waitFor(() => expect(result.current.status).toBe('failed'));
  expect(result.current.error).toBe(
    'Could not reach the server. Check your connection.',
  );
});

test('a failed refresh keeps the rows already on screen', async () => {
  const list = jest
    .fn()
    .mockResolvedValueOnce([base('physics')])
    .mockRejectedValueOnce(new ApiError('timeout', 'slow'));
  const { result } = renderHook(() => useKnowledgeBases(fakeApi(list)));
  await waitFor(() => expect(result.current.status).toBe('ready'));

  await act(async () => {
    await result.current.refresh();
  });
  expect(result.current.status).toBe('ready');
  expect(result.current.bases.map(item => item.name)).toEqual(['physics']);
  expect(result.current.error).toBe('The server took too long to answer. Try again.');
  expect(result.current.refreshing).toBe(false);
});

test('a slow reply cannot overwrite the refresh that replaced it', async () => {
  const first = deferred<KnowledgeBaseSummary[]>();
  const second = deferred<KnowledgeBaseSummary[]>();
  const list = jest
    .fn()
    .mockReturnValueOnce(first.promise)
    .mockReturnValueOnce(second.promise);
  const { result } = renderHook(() => useKnowledgeBases(fakeApi(list)));

  let refreshing: Promise<void> = Promise.resolve();
  act(() => {
    refreshing = result.current.refresh();
  });
  await act(async () => {
    second.resolve([base('fresh')]);
    await refreshing;
  });
  await act(async () => {
    first.resolve([base('stale')]);
    await first.promise;
  });
  expect(result.current.bases.map(item => item.name)).toEqual(['fresh']);
});

test('leaving the screen cancels the request it started', async () => {
  const seen: AbortSignal[] = [];
  const list = jest.fn((signal?: AbortSignal) => {
    if (signal) seen.push(signal);
    return new Promise<KnowledgeBaseSummary[]>(() => {});
  });
  const { unmount } = renderHook(() => useKnowledgeBases(fakeApi(list)));
  expect(seen).toHaveLength(1);
  unmount();
  expect(seen[0].aborted).toBe(true);
});

test('a deleted base leaves the list at once, and a new one joins it', async () => {
  const list = jest.fn().mockResolvedValue([base('physics'), base('biology')]);
  const { result } = renderHook(() => useKnowledgeBases(fakeApi(list)));
  await waitFor(() => expect(result.current.status).toBe('ready'));

  act(() => result.current.forget('user:kb:physics'));
  expect(result.current.bases.map(item => item.name)).toEqual(['biology']);

  act(() => result.current.remember(base('chemistry')));
  expect(result.current.bases.map(item => item.name)).toEqual([
    'chemistry',
    'biology',
  ]);

  // Renaming or re-reading a base replaces its row rather than duplicating it.
  act(() => result.current.remember(base('biology', { description: 'Cells' })));
  expect(result.current.bases).toHaveLength(2);
  expect(result.current.bases[1].description).toBe('Cells');
});
