import { act, renderHook, waitFor } from '@testing-library/react-native';
import { AppState, type AppStateStatus } from 'react-native';

import { useKnowledgeBase } from '../src/features/knowledge/useKnowledgeBase';
import { ApiError } from '../src/services/apiClient';
import type {
  KnowledgeApi,
  KnowledgeBaseSummary,
  KnowledgeFileEntry,
  KnowledgeProgress,
} from '../src/services/knowledgeApi';

function record(
  overrides: Partial<KnowledgeBaseSummary> = {},
): KnowledgeBaseSummary {
  return {
    ref: 'user:kb:physics',
    id: 'user:kb:physics',
    name: 'physics',
    description: '',
    status: 'ready',
    isDefault: false,
    documentCount: 1,
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
    message: 'Parsing',
    current: 0,
    total: 2,
    percent: 0,
    fileName: 'a.pdf',
    error: '',
    retryable: false,
    updatedAt: '',
    ...overrides,
  };
}

function entry(name: string, overrides: Partial<KnowledgeFileEntry> = {}) {
  return {
    name,
    type: 'file' as const,
    size: 1024,
    modified: 1_700_000_000,
    mimeType: 'application/pdf',
    ...overrides,
  };
}

type Stub = {
  get: jest.Mock;
  files: jest.Mock;
  retry: jest.Mock;
  updateDescription: jest.Mock;
  removeFile: jest.Mock;
};

function stub(overrides: Partial<Stub> = {}) {
  const calls: Stub = {
    get: jest.fn().mockResolvedValue(record()),
    files: jest.fn().mockResolvedValue([]),
    retry: jest.fn().mockResolvedValue(undefined),
    updateDescription: jest.fn().mockResolvedValue(undefined),
    removeFile: jest.fn().mockResolvedValue(undefined),
    ...overrides,
  };
  return { calls, api: calls as unknown as KnowledgeApi };
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

/**
 * The test renderer's `AppState` returns no subscription, so the platform's
 * listener registry is stood in for and driven directly.
 */
const appState = AppState as unknown as { currentState: AppStateStatus };
const listeners = new Set<(next: AppStateStatus) => void>();
const originalState = appState.currentState;

beforeEach(() => {
  listeners.clear();
  // Without a state the hook treats the app as absent and never polls.
  appState.currentState = 'active';
  jest.spyOn(AppState, 'addEventListener').mockImplementation((_event, listener) => {
    listeners.add(listener);
    return {
      remove: () => listeners.delete(listener),
    } as ReturnType<typeof AppState.addEventListener>;
  });
});

afterEach(() => {
  jest.mocked(AppState.addEventListener).mockRestore();
  appState.currentState = originalState;
});

function foreground(next: AppStateStatus) {
  appState.currentState = next;
  for (const listener of [...listeners]) listener(next);
}

test('opens a base with its record and its raw documents', async () => {
  const { api, calls } = stub({
    get: jest.fn().mockResolvedValue(record({ description: 'Mechanics' })),
    files: jest.fn().mockResolvedValue([entry('a.pdf')]),
  });
  const { result } = renderHook(() =>
    useKnowledgeBase(api, 'user:kb:physics'),
  );
  await waitFor(() => expect(result.current.status).toBe('ready'));
  expect(result.current.kb).toMatchObject({
    name: 'physics',
    description: 'Mechanics',
  });
  expect(result.current.files.map(file => file.name)).toEqual(['a.pdf']);
  expect(calls.get).toHaveBeenCalledWith(
    'user:kb:physics',
    expect.any(AbortSignal),
  );
});

test('polls a live run with a growing delay and stops when it ends', async () => {
  jest.useFakeTimers();
  try {
    const get = jest
      .fn()
      .mockResolvedValue(record({ status: 'processing', progress: progress() }));
    const files = jest.fn().mockResolvedValue([entry('a.pdf')]);
    const { api } = stub({ get, files });
    const { result } = renderHook(() =>
      useKnowledgeBase(api, 'user:kb:physics'),
    );
    await act(async () => {});
    expect(get).toHaveBeenCalledTimes(1);

    await act(async () => {
      jest.advanceTimersByTime(2_000);
    });
    expect(get).toHaveBeenCalledTimes(2);

    // The second wait is 2.8 s: half a second short of it changes nothing.
    await act(async () => {
      jest.advanceTimersByTime(2_000);
    });
    expect(get).toHaveBeenCalledTimes(2);
    await act(async () => {
      jest.advanceTimersByTime(800);
    });
    expect(get).toHaveBeenCalledTimes(3);

    // The run reports a terminal stage, so no further poll is armed.
    get.mockResolvedValue(record({ status: 'ready' }));
    await act(async () => {
      jest.advanceTimersByTime(4_000);
    });
    expect(result.current.kb?.status).toBe('ready');
    const settled = get.mock.calls.length;
    await act(async () => {
      jest.advanceTimersByTime(60_000);
    });
    expect(get.mock.calls.length).toBe(settled);
    // The file list is re-read when the run ends, so each row gets its final
    // state; before that only the initial read happened.
    expect(files).toHaveBeenCalledTimes(2);
  } finally {
    jest.useRealTimers();
  }
});

test('a backgrounded app stops polling and refreshes the moment it returns', async () => {
  jest.useFakeTimers();
  try {
    const get = jest
      .fn()
      .mockResolvedValue(record({ status: 'processing', progress: progress() }));
    const { api } = stub({ get });
    const { result } = renderHook(() =>
      useKnowledgeBase(api, 'user:kb:physics'),
    );
    await act(async () => {});
    expect(get).toHaveBeenCalledTimes(1);

    appState.currentState = 'background';
    await act(async () => {
      jest.advanceTimersByTime(2_000);
    });
    // JavaScript is not kept alive there, so no request is made.
    expect(get).toHaveBeenCalledTimes(1);

    act(() => foreground('active'));
    await act(async () => {});
    expect(get).toHaveBeenCalledTimes(2);
    expect(result.current.kb?.status).toBe('processing');
  } finally {
    jest.useRealTimers();
  }
});

test('a base that fails to load says so and can be tried again', async () => {
  const get = jest
    .fn()
    .mockRejectedValueOnce(new ApiError('http', 'missing', 404))
    .mockResolvedValueOnce(record());
  const { api } = stub({ get });
  const { result } = renderHook(() =>
    useKnowledgeBase(api, 'user:kb:physics'),
  );
  await waitFor(() => expect(result.current.status).toBe('failed'));
  expect(result.current.error).toBe(
    'This knowledge base no longer exists on the server.',
  );
  await act(async () => {
    await result.current.refresh();
  });
  expect(result.current.status).toBe('ready');
  expect(result.current.kb?.name).toBe('physics');
});

test('a failed refresh keeps the record that is already open', async () => {
  const get = jest
    .fn()
    .mockResolvedValueOnce(record())
    .mockRejectedValueOnce(new ApiError('network', 'offline'));
  const { api } = stub({ get });
  const { result } = renderHook(() =>
    useKnowledgeBase(api, 'user:kb:physics'),
  );
  await waitFor(() => expect(result.current.status).toBe('ready'));
  await act(async () => {
    await result.current.refresh();
  });
  expect(result.current.status).toBe('ready');
  expect(result.current.kb?.name).toBe('physics');
  expect(result.current.error).toBe(
    'Could not reach the server. Check your connection.',
  );
});

test('retry explains a refusal in the server’s own words', async () => {
  // The live server answers 409 with the real reason — no embedding model, a run
  // that already finished, a read-only base. Inventing one from the status code
  // told the learner something the server never said.
  const retry = jest.fn().mockRejectedValue(
    new ApiError(
      'http',
      'The server returned HTTP 409.',
      409,
      'No embedding model is configured. Set up the embedding profile in Settings before re-indexing.',
    ),
  );
  const { api, calls } = stub({ retry });
  const { result } = renderHook(() =>
    useKnowledgeBase(api, 'user:kb:physics'),
  );
  await waitFor(() => expect(result.current.status).toBe('ready'));
  await act(async () => {
    await result.current.retry();
  });
  expect(result.current.error).toBe(
    'No embedding model is configured. Set up the embedding profile in Settings before re-indexing.',
  );
  expect(result.current.retrying).toBe(false);
  expect(calls.get).toHaveBeenCalledTimes(1);
});

test('a refusal without an explanation still says what is known, not a guess', async () => {
  const retry = jest.fn().mockRejectedValue(new ApiError('http', 'no', 409));
  const { api } = stub({ retry });
  const { result } = renderHook(() =>
    useKnowledgeBase(api, 'user:kb:physics'),
  );
  await waitFor(() => expect(result.current.status).toBe('ready'));
  await act(async () => {
    await result.current.retry();
  });
  expect(result.current.error).toBe(
    'The server refused this change in the base’s current state.',
  );
  expect(result.current.retrying).toBe(false);
});

test('a retry that the server accepts re-reads the base', async () => {
  const get = jest
    .fn()
    .mockResolvedValueOnce(record({ status: 'error' }))
    .mockResolvedValueOnce(record({ status: 'processing', progress: progress() }));
  const { api, calls } = stub({ get });
  const { result } = renderHook(() =>
    useKnowledgeBase(api, 'user:kb:physics'),
  );
  await waitFor(() => expect(result.current.status).toBe('ready'));
  await act(async () => {
    await result.current.retry();
  });
  expect(calls.retry).toHaveBeenCalledWith('user:kb:physics');
  expect(result.current.kb?.status).toBe('processing');
});

test('the description saves on the server before the screen agrees', async () => {
  const updateDescription = jest
    .fn()
    .mockResolvedValueOnce(undefined)
    .mockRejectedValueOnce(new ApiError('http', 'no', 403));
  const { api } = stub({ updateDescription });
  const { result } = renderHook(() =>
    useKnowledgeBase(api, 'user:kb:physics'),
  );
  await waitFor(() => expect(result.current.status).toBe('ready'));

  let saved = false;
  await act(async () => {
    saved = await result.current.saveDescription('Mechanics');
  });
  expect(saved).toBe(true);
  expect(updateDescription).toHaveBeenCalledWith(
    'user:kb:physics',
    'Mechanics',
  );
  expect(result.current.kb?.description).toBe('Mechanics');

  await act(async () => {
    saved = await result.current.saveDescription('Cells');
  });
  expect(saved).toBe(false);
  // The old copy stays on screen when the server refuses the change.
  expect(result.current.kb?.description).toBe('Mechanics');
  expect(result.current.error).toBe(
    'This knowledge base is read-only for your account.',
  );
});

test('removing a document drops the row and re-reads what remains', async () => {
  const get = jest
    .fn()
    .mockResolvedValueOnce(record({ documentCount: 1 }))
    .mockResolvedValueOnce(record({ documentCount: 0 }));
  const files = jest
    .fn()
    .mockResolvedValueOnce([entry('a.pdf')])
    .mockResolvedValueOnce([]);
  const removeFile = jest.fn().mockResolvedValue(undefined);
  const { api } = stub({ get, files, removeFile });
  const { result } = renderHook(() =>
    useKnowledgeBase(api, 'user:kb:physics'),
  );
  await waitFor(() => expect(result.current.files).toHaveLength(1));

  let removed = false;
  await act(async () => {
    removed = await result.current.removeFile('a.pdf');
  });
  expect(removed).toBe(true);
  expect(removeFile).toHaveBeenCalledWith('user:kb:physics', 'a.pdf');
  expect(result.current.files).toEqual([]);
  expect(result.current.kb?.documentCount).toBe(0);
});

test('a refused deletion leaves the document in place and explains why', async () => {
  const removeFile = jest.fn().mockRejectedValue(new ApiError('http', 'no', 403));
  const { api } = stub({ removeFile, files: jest.fn().mockResolvedValue([entry('a.pdf')]) });
  const { result } = renderHook(() =>
    useKnowledgeBase(api, 'user:kb:physics'),
  );
  await waitFor(() => expect(result.current.files).toHaveLength(1));
  await act(async () => {
    await result.current.removeFile('a.pdf');
  });
  expect(result.current.files).toHaveLength(1);
  expect(result.current.error).toBe(
    'This knowledge base is read-only for your account.',
  );
});

test('switching bases cancels the previous read and ignores its late reply', async () => {
  const first = deferred<KnowledgeBaseSummary>();
  const second = deferred<KnowledgeBaseSummary>();
  const signals: AbortSignal[] = [];
  const get = jest.fn((ref: string, signal: AbortSignal) => {
    signals.push(signal);
    return ref === 'user:kb:physics' ? first.promise : second.promise;
  });
  const { api } = stub({ get });
  const { result, rerender } = renderHook(
    ({ ref }: { ref: string }) => useKnowledgeBase(api, ref),
    { initialProps: { ref: 'user:kb:physics' } },
  );

  rerender({ ref: 'user:kb:biology' });
  expect(signals[0].aborted).toBe(true);

  await act(async () => {
    second.resolve(record({ ref: 'user:kb:biology', name: 'biology' }));
    await second.promise;
  });
  await act(async () => {
    first.resolve(record({ name: 'physics' }));
    await first.promise;
  });
  expect(result.current.kb?.name).toBe('biology');
});
