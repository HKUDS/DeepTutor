import {
  act,
  cleanup,
  renderHook,
  waitFor,
} from '@testing-library/react-native';

import { useSessionList } from '../src/features/sessions/useSessionList';
import { ApiError } from '../src/services/apiClient';
import type {
  SessionApi,
  SessionPage,
  SessionSummary,
} from '../src/services/sessionApi';

afterEach(cleanup);

function summary(id: string, overrides: Partial<SessionSummary> = {}) {
  return {
    id,
    title: `Conversation ${id}`,
    createdAt: 1,
    updatedAt: 2,
    messageCount: 2,
    lastMessage: '',
    status: 'idle' as const,
    activeTurnId: '',
    ...overrides,
  };
}

function page(sessions: SessionSummary[], hasMore = false): SessionPage {
  return { sessions, hasMore };
}

function fakeApi(overrides: Partial<SessionApi> = {}): SessionApi {
  return {
    list: jest.fn(async () => page([])),
    get: jest.fn(),
    rename: jest.fn(async (_id: string, title: string) => title),
    remove: jest.fn(async () => undefined),
    ...overrides,
  } as unknown as SessionApi;
}

test('loads the first page and asks for another when it is full', async () => {
  const list = jest.fn(async () => page([summary('a'), summary('b')], true));
  const api = fakeApi({ list });
  const { result } = renderHook(() => useSessionList(api));

  await waitFor(() => expect(result.current.status).toBe('ready'));
  expect(result.current.sessions.map(row => row.id)).toEqual(['a', 'b']);
  expect(result.current.hasMore).toBe(true);
  expect(list).toHaveBeenCalledWith(
    { limit: 30, offset: 0, workspaceId: undefined },
    expect.anything(),
  );
});

test('appends the next page without duplicating rows that shifted', async () => {
  const pages = [
    page([summary('a'), summary('b')], true),
    page([summary('b'), summary('c')], false),
  ];
  const list = jest.fn(async () => pages.shift() ?? page([]));
  const api = fakeApi({ list });
  const { result } = renderHook(() => useSessionList(api));

  await waitFor(() => expect(result.current.hasMore).toBe(true));
  await act(() => result.current.loadMore());

  expect(result.current.sessions.map(row => row.id)).toEqual(['a', 'b', 'c']);
  expect(result.current.hasMore).toBe(false);
  expect(list).toHaveBeenNthCalledWith(
    2,
    { limit: 30, offset: 2, workspaceId: undefined },
    expect.anything(),
  );
});

test('refreshing replaces the index instead of extending it', async () => {
  const list = jest
    .fn()
    .mockResolvedValueOnce(page([summary('a'), summary('b')], true))
    .mockResolvedValueOnce(page([summary('z')], false));
  const api = fakeApi({ list });
  const { result } = renderHook(() => useSessionList(api));

  await waitFor(() => expect(result.current.status).toBe('ready'));
  await act(() => result.current.refresh());

  expect(result.current.sessions.map(row => row.id)).toEqual(['z']);
  expect(list).toHaveBeenNthCalledWith(
    2,
    { limit: 30, offset: 0, workspaceId: undefined },
    expect.anything(),
  );
});

test('a failed first page reports an error the learner can retry', async () => {
  const list = jest
    .fn()
    .mockRejectedValueOnce(
      new ApiError('network', 'Could not reach the DeepTutor server.'),
    )
    .mockResolvedValueOnce(page([summary('a')]));
  const api = fakeApi({ list });
  const { result } = renderHook(() => useSessionList(api));

  await waitFor(() => expect(result.current.status).toBe('failed'));
  expect(result.current.error).toBe(
    'Could not reach the server. Check your connection.',
  );

  await act(() => result.current.retry());
  expect(result.current.status).toBe('ready');
  expect(result.current.error).toBeNull();
});

test('an expired session is named as an authentication problem', async () => {
  const list = jest.fn(async () => {
    throw new ApiError('unauthorized', 'Sign-in is required.', 401);
  });
  const { result } = renderHook(() => useSessionList(fakeApi({ list })));

  await waitFor(() => expect(result.current.status).toBe('failed'));
  expect(result.current.error).toBe(
    'Sign in again to see your conversations.',
  );
});

test('rename replaces just the row the server confirmed', async () => {
  const list = jest.fn(async () => page([summary('a'), summary('b')]));
  const rename = jest.fn(async () => 'Halves and thirds');
  const { result } = renderHook(() =>
    useSessionList(fakeApi({ list, rename })),
  );
  await waitFor(() => expect(result.current.status).toBe('ready'));

  await act(() => result.current.rename('a', '  Halves and thirds  '));
  expect(rename).toHaveBeenCalledWith('a', 'Halves and thirds');
  expect(result.current.sessions.map(row => row.title)).toEqual([
    'Halves and thirds',
    'Conversation b',
  ]);
});

test('a blank rename never reaches the server', async () => {
  const rename = jest.fn();
  const list = jest.fn(async () => page([summary('a')]));
  const { result } = renderHook(() =>
    useSessionList(fakeApi({ list, rename })),
  );
  await waitFor(() => expect(result.current.status).toBe('ready'));

  await act(() => result.current.rename('a', '   '));
  expect(rename).not.toHaveBeenCalled();
});

test('deleting removes the row only after the server confirms', async () => {
  const list = jest.fn(async () => page([summary('a'), summary('b')]));
  const remove = jest.fn(async () => undefined);
  const { result } = renderHook(() =>
    useSessionList(fakeApi({ list, remove })),
  );
  await waitFor(() => expect(result.current.status).toBe('ready'));

  await act(() => result.current.remove('a'));
  expect(remove).toHaveBeenCalledWith('a');
  expect(result.current.sessions.map(row => row.id)).toEqual(['b']);
});

test('a rejected delete leaves the list untouched for the caller to report', async () => {
  const list = jest.fn(async () => page([summary('a')]));
  const remove = jest.fn(async () => {
    throw new ApiError('http', 'The server returned HTTP 500.', 500);
  });
  const { result } = renderHook(() =>
    useSessionList(fakeApi({ list, remove })),
  );
  await waitFor(() => expect(result.current.status).toBe('ready'));

  await expect(
    act(() => result.current.remove('a')),
  ).rejects.toBeInstanceOf(ApiError);
  expect(result.current.sessions.map(row => row.id)).toEqual(['a']);
});

test('unmounting during a pending load does not commit the late page', async () => {
  let resolvePage: (value: SessionPage) => void = () => {};
  const list = jest.fn(
    () =>
      new Promise<SessionPage>(resolve => {
        resolvePage = resolve;
      }),
  );
  const { result, unmount } = renderHook(() =>
    useSessionList(fakeApi({ list })),
  );
  expect(result.current.status).toBe('loading');

  unmount();
  resolvePage(page([summary('a')]));
  await Promise.resolve();
  // No state update after unmount is the assertion: the hook's guard keeps
  // React from warning about a write to an unmounted tree.
  expect(result.current.sessions).toEqual([]);
});

test('a null client never fetches', async () => {
  const list = jest.fn();
  const { result } = renderHook(() => useSessionList(null));
  await Promise.resolve();
  expect(list).not.toHaveBeenCalled();
  expect(result.current.status).toBe('loading');
});

test('a refresh supersedes a page that is still loading', async () => {
  let release: (value: SessionPage) => void = () => {};
  const list = jest
    .fn()
    .mockResolvedValueOnce(page([summary('a')], true))
    .mockImplementationOnce(
      () =>
        new Promise<SessionPage>(resolve => {
          release = resolve;
        }),
    )
    .mockResolvedValueOnce(page([summary('fresh')], false));
  const api = fakeApi({ list });
  const { result } = renderHook(() => useSessionList(api));

  await waitFor(() => expect(result.current.status).toBe('ready'));
  await act(async () => {
    result.current.loadMore().catch(() => {});
  });
  expect(result.current.loadingMore).toBe(true);

  // Pulling to refresh must not be swallowed by the page in flight.
  await act(async () => {
    await result.current.refresh();
  });
  expect(result.current.sessions.map(row => row.id)).toEqual(['fresh']);
  expect(result.current.loadingMore).toBe(false);

  // The abandoned page lands late and is discarded.
  await act(async () => {
    release(page([summary('stale')], true));
  });
  expect(result.current.sessions.map(row => row.id)).toEqual(['fresh']);
});
