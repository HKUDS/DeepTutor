jest.mock('expo/fetch', () => ({ fetch: jest.fn() }));
jest.mock('@react-native-async-storage/async-storage', () => ({
  getItem: jest.fn(),
  setItem: jest.fn(),
  removeItem: jest.fn(),
  getAllKeys: jest.fn(async () => []),
  multiRemove: jest.fn(async () => {}),
}));

import type { AuthStatus } from '../src/features/auth/authService';
import { ApiError } from '../src/services/apiClient';
import { serverOrigin } from '../src/features/server/serverAddress';
import { ServerSession } from '../src/features/server/serverSession';

const first = 'https://tutor.example.com:8443';
const second = 'https://tutor.example.com:9443';
const anonymous = { enabled: true, authenticated: false, accountId: '' };
const signedIn = { ...anonymous, authenticated: true, accountId: 'acct-1' };

function fixture(initial: string | null = null) {
  const events: string[] = [];
  let saved: string | null = initial;

  const auth = {
    status: jest
      .fn<Promise<AuthStatus>, [AbortSignal]>()
      .mockResolvedValue(anonymous),
    login: jest
      .fn<Promise<AuthStatus>, [string, string, AbortSignal]>()
      .mockResolvedValue(signedIn),
    logout: jest
      .fn<Promise<void>, [AbortSignal]>()
      .mockResolvedValue(undefined),
  };
  const clearCookies = jest.fn(async () => {
    events.push('clear cookies');
  });
  const clearRecovery = jest.fn(async (_origin: string) => {});
  const storage = {
    read: jest.fn(async () => saved),
    write: jest.fn(async (value: string | null) => {
      events.push(`save ${value ?? '<none>'}`);
      saved = value;
    }),
  };
  const session = new ServerSession({
    storage,
    clearCookies,
    clearRecovery,
    normalizeOrigin: address => serverOrigin(address, false),
    authFor: origin => {
      events.push(`use ${origin}`);
      return auth;
    },
  });
  return { session, auth, clearCookies, clearRecovery, storage, events };
}

test('validates the saved origin and current cookie at launch', async () => {
  const { session, auth, events, clearCookies } = fixture(first);
  auth.status.mockResolvedValueOnce(signedIn);

  await session.restore();

  expect(session.getSnapshot()).toMatchObject({
    phase: 'chat',
    origin: first,
    network: 'online',
  });
  expect(events).toEqual([`use ${first}`]);
  expect(clearCookies).not.toHaveBeenCalled();
});

test('connect persists only the server origin and login gates the chat route', async () => {
  const { session, auth, storage } = fixture();
  await session.restore();
  await session.connect(first);
  expect(session.getSnapshot()).toMatchObject({
    phase: 'login',
    origin: first,
  });
  expect(storage.write.mock.calls).toEqual([[null], [first]]);

  auth.login.mockRejectedValueOnce(
    new ApiError('unauthorized', 'Check your username and password.', 401),
  );
  await session.login('demo', 'wrong');
  expect(session.getSnapshot()).toMatchObject({
    phase: 'login',
    error: 'Check your username and password.',
  });
  await session.login('demo', 'right');
  expect(session.getSnapshot()).toMatchObject({ phase: 'chat', error: null });
  expect(storage.write.mock.calls).toEqual([[null], [first]]);
});

test('switching port clears cookies before accessing the new origin', async () => {
  const { session, auth, events } = fixture(first);
  auth.status.mockResolvedValueOnce(signedIn);
  await session.restore();
  events.length = 0;

  await session.connect(second);

  expect(events).toEqual([
    'save <none>',
    'clear cookies',
    `use ${second}`,
    `save ${second}`,
  ]);
  expect(session.getSnapshot()).toMatchObject({
    phase: 'login',
    origin: second,
  });
});

test('leaving a server drops the task state saved for it', async () => {
  const { session, auth, clearRecovery } = fixture(first);
  auth.status.mockResolvedValueOnce(signedIn);
  await session.restore();

  await session.connect(second);
  expect(clearRecovery).toHaveBeenCalledWith(first);

  await session.login('learner', 'a-test-password');
  clearRecovery.mockClear();
  await session.logout();
  expect(clearRecovery).toHaveBeenCalledWith(second);
});

test('a failed cookie clear blocks a server switch before authentication', async () => {
  const { session, auth, clearCookies, storage } = fixture(first);
  await session.restore();
  clearCookies.mockRejectedValueOnce(new Error('Cookie error'));

  await session.connect(second);

  expect(auth.status).toHaveBeenCalledTimes(1);
  await expect(storage.read()).resolves.toBeNull();
  expect(session.getSnapshot()).toMatchObject({
    phase: 'connect',
    origin: null,
    error: 'Could not clear the saved session. Try again.',
  });
});

test('drops the old status response if a server switch begins', async () => {
  const { session, auth } = fixture(first);
  auth.status.mockResolvedValueOnce(signedIn);
  await session.restore();
  let complete: (status: AuthStatus) => void = () => {};
  auth.status.mockImplementationOnce(
    () =>
      new Promise(resolve => {
        complete = resolve;
      }),
  );

  const refresh = session.refreshAuth();
  await session.connect(second);
  complete(signedIn);
  await expect(refresh).resolves.toBe(false);
  expect(session.getSnapshot()).toMatchObject({
    phase: 'login',
    origin: second,
  });
});

test('refresh routes explicit expiry to login but leaves chat open on network errors', async () => {
  const { session, auth } = fixture(first);
  auth.status.mockResolvedValueOnce(signedIn);
  await session.restore();
  auth.status.mockRejectedValueOnce(new ApiError('network', 'Offline'));
  await expect(session.refreshAuth()).resolves.toBe(true);
  expect(session.getSnapshot()).toMatchObject({
    phase: 'chat',
    network: 'offline',
  });

  await expect(session.refreshAuth()).resolves.toBe(false);
  expect(session.getSnapshot()).toMatchObject({
    phase: 'login',
    network: 'online',
  });
});

test('logout clears the native jar even when its HTTP request fails', async () => {
  const { session, auth, events } = fixture(first);
  auth.status.mockResolvedValueOnce(signedIn);
  await session.restore();
  events.length = 0;
  auth.logout.mockRejectedValueOnce(new ApiError('network', 'Offline'));

  await session.logout();

  expect(events).toEqual([
    'save <none>',
    `use ${first}`,
    'clear cookies',
    `save ${first}`,
  ]);
  expect(session.getSnapshot()).toMatchObject({
    phase: 'login',
    error: 'Offline',
  });
});

test.each(['logout', 'disconnect'] as const)(
  '%s still clears the native jar when removing the saved origin fails',
  async action => {
    const { session, auth, clearCookies, storage } = fixture(first);
    auth.status.mockResolvedValueOnce(signedIn);
    await session.restore();
    storage.write.mockRejectedValueOnce(
      new Error('local path or other detail'),
    );

    await session[action]();

    expect(clearCookies).toHaveBeenCalledTimes(1);
    expect(auth.logout).toHaveBeenCalledTimes(action === 'logout' ? 1 : 0);
    expect(session.getSnapshot()).toMatchObject({
      phase: action === 'logout' ? 'login' : 'connect',
      error: 'Could not update the saved server address.',
    });
  },
);
