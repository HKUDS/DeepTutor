jest.mock('expo/fetch', () => ({ fetch: jest.fn() }));

import { AuthService } from '../src/features/auth/authService';
import { ApiClient } from '../src/services/apiClient';

function response(status: number, value?: unknown) {
  return {
    status,
    ok: status >= 200 && status < 300,
    redirected: false,
    json: async () => value,
  };
}

const origin = 'https://tutor.example.com:9443';

test('login verifies the native cookie via a second HTTP request', async () => {
  const fetcher = jest
    .fn()
    .mockResolvedValueOnce(response(200, { ok: true }))
    .mockResolvedValueOnce(
      response(200, {
        enabled: true,
        authenticated: true,
        user_id: 'u1',
        username: 'demo',
      }),
    );
  const auth = new AuthService(new ApiClient(origin, fetcher));

  await expect(
    auth.login(' demo ', 'pass', new AbortController().signal),
  ).resolves.toEqual({ enabled: true, authenticated: true, accountId: 'u1' });
  expect(fetcher).toHaveBeenNthCalledWith(
    1,
    `${origin}/api/auth/login`,
    expect.objectContaining({
      method: 'POST',
      credentials: 'include',
      redirect: 'manual',
      body: JSON.stringify({ username: 'demo', password: 'pass' }),
    }),
  );
  expect(fetcher).toHaveBeenNthCalledWith(
    2,
    `${origin}/api/auth/status`,
    expect.objectContaining({
      method: 'GET',
      credentials: 'include',
      redirect: 'manual',
    }),
  );
  expect(fetcher.mock.calls[1][1]).not.toHaveProperty('body');
});

test('rejects a login that cannot establish an authenticated cookie session', async () => {
  const fetcher = jest
    .fn()
    .mockResolvedValueOnce(response(200, { ok: true }))
    .mockResolvedValueOnce(
      response(200, { enabled: true, authenticated: false }),
    );
  const auth = new AuthService(new ApiClient(origin, fetcher));

  await expect(
    auth.login('demo', 'pass', new AbortController().signal),
  ).rejects.toMatchObject({
    kind: 'unauthorized',
    message: 'The server could not establish a session.',
  });
});

test('handles bad credentials and an expired cookie distinctly', async () => {
  const fetcher = jest.fn().mockResolvedValue(response(401));
  const auth = new AuthService(new ApiClient(origin, fetcher));
  const signal = new AbortController().signal;

  await expect(auth.login('demo', 'wrong', signal)).rejects.toMatchObject({
    kind: 'unauthorized',
    status: 401,
    message: 'Check your username and password.',
  });
  await expect(auth.status(signal)).resolves.toEqual({
    enabled: true,
    authenticated: false,
    accountId: '',
  });
});

test.each([
  [response(307), 'redirect'],
  [response(503), 'http'],
  [response(200, { enabled: true }), 'invalid-response'],
  // An authenticated status with no account id cannot be scoped, so it fails
  // closed instead of sharing another account's local state.
  [response(200, { enabled: true, authenticated: true }), 'invalid-response'],
])('maps status and schema errors: %p', async (reply, kind) => {
  const fetcher = jest.fn().mockResolvedValue(reply);
  const auth = new AuthService(new ApiClient(origin, fetcher));
  await expect(auth.status(new AbortController().signal)).rejects.toMatchObject(
    { kind },
  );
  expect(fetcher).toHaveBeenCalledTimes(1);
});

test('does not expose native networking exception text', async () => {
  const auth = new AuthService(
    new ApiClient(
      origin,
      jest.fn().mockRejectedValue(new Error('private request')),
    ),
  );
  await expect(auth.status(new AbortController().signal)).rejects.toMatchObject(
    { kind: 'network', message: 'Could not reach the DeepTutor server.' },
  );
});

test('times out waiting on a response body and aborts native work', async () => {
  jest.useFakeTimers();
  try {
    const fetcher = jest.fn().mockResolvedValue({
      ...response(200),
      json: () => new Promise(() => {}),
    });
    const api = new ApiClient(origin, fetcher, 25);
    await Promise.all([
      expect(
        api.json('/api/auth/status', value => value),
      ).rejects.toMatchObject({
        kind: 'timeout',
      }),
      jest.advanceTimersByTimeAsync(25),
    ]);
    expect(fetcher.mock.calls[0][1].signal.aborted).toBe(true);
  } finally {
    jest.useRealTimers();
  }
});

test('abort does not wait indefinitely for a stale native response', async () => {
  const fetcher = jest.fn().mockImplementation(() => new Promise(() => {}));
  const api = new ApiClient(origin, fetcher);
  const controller = new AbortController();
  const pending = api.json('/api/auth/status', value => value, {
    signal: controller.signal,
  });

  controller.abort();
  await expect(pending).rejects.toMatchObject({ kind: 'aborted' });
  expect(fetcher.mock.calls[0][1].signal.aborted).toBe(true);
});
