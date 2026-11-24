jest.mock('expo/fetch', () => ({ fetch: jest.fn() }));

import { ApiClient, ApiError } from '../src/services/apiClient';
import { SessionApi } from '../src/services/sessionApi';

function response(status: number, value?: unknown) {
  return {
    status,
    ok: status >= 200 && status < 300,
    redirected: false,
    json: async () => value,
  };
}

const origin = 'https://tutor.example.test';

function api(reply: unknown) {
  const fetcher = jest.fn().mockResolvedValue(reply);
  return { fetcher, api: new SessionApi(new ApiClient(origin, fetcher)) };
}

const row = {
  id: 's1',
  session_id: 's1',
  title: 'Fractions',
  created_at: 100,
  updated_at: 200,
  message_count: 4,
  last_message: 'One of three equal parts.',
  status: 'running',
  active_turn_id: 'turn-9',
  preferences: { workspace_id: 'w1' },
};

test('a row id survives whichever store produced it', async () => {
  const { api: sessions } = api(
    response(200, {
      ...row,
      // PocketBase hands out record strings, SQLite an integer rowid, and a
      // row without either must still be addressable.
      messages: [
        { id: 'a1b2c3d4e5f6g7h', role: 'user', content: 'Hi' },
        { id: 42, role: 'assistant', content: 'Hello' },
        { role: 'user', content: 'No id' },
      ],
      active_turns: [],
    }),
  );
  const detail = await sessions.get('s1');
  expect(detail.messages.map(message => message.id)).toEqual([
    'a1b2c3d4e5f6g7h',
    '42',
    '',
  ]);
});

test('lists a page and reports whether another page exists', async () => {
  const { api: sessions, fetcher } = api(
    response(200, { sessions: [row] }),
  );
  const page = await sessions.list({ limit: 1, offset: 0 });
  expect(page.sessions).toEqual([
    {
      id: 's1',
      title: 'Fractions',
      createdAt: 100,
      updatedAt: 200,
      messageCount: 4,
      lastMessage: 'One of three equal parts.',
      status: 'running',
      activeTurnId: 'turn-9',
    },
  ]);
  expect(page.hasMore).toBe(true);
  expect(fetcher.mock.calls[0][0]).toBe(
    `${origin}/api/sessions?limit=1&offset=0`,
  );
});

test('a short page ends the index and the workspace scope is forwarded', async () => {
  const { api: sessions, fetcher } = api(response(200, { sessions: [row] }));
  const page = await sessions.list({ limit: 30, offset: 60, workspaceId: '' });
  expect(page.hasMore).toBe(false);
  expect(fetcher.mock.calls[0][0]).toBe(
    `${origin}/api/sessions?limit=30&offset=60&workspace_id=`,
  );
});

test('reads a transcript with its failed-turn metadata and active turns', async () => {
  const { api: sessions } = api(
    response(200, {
      ...row,
      messages: [
        { id: 1, role: 'user', content: 'Hi', created_at: 1 },
        {
          id: 2,
          role: 'user',
          content: 'Retry me',
          created_at: 2,
          metadata: {
            orphaned_failed_turn: {
              turn_id: 'turn-3',
              error: 'Provider down',
              retryable: true,
            },
          },
        },
        {
          id: 3,
          role: 'assistant',
          content: 'Hello',
          created_at: 3,
          events: [],
          attachments: [],
          metadata: {},
        },
      ],
      active_turns: [
        {
          id: 'turn-9',
          status: 'running',
          last_seq: 12,
          error: '',
          updated_at: 9,
          retryable: false,
        },
      ],
    }),
  );
  const detail = await sessions.get('s1');
  expect(detail.messages).toEqual([
    { id: '1', role: 'user', content: 'Hi', createdAt: 1, failedTurn: null },
    {
      id: '2',
      role: 'user',
      content: 'Retry me',
      createdAt: 2,
      failedTurn: { turnId: 'turn-3', error: 'Provider down', retryable: true },
    },
    { id: '3', role: 'assistant', content: 'Hello', createdAt: 3, failedTurn: null },
  ]);
  expect(detail.activeTurns).toEqual([
    {
      id: 'turn-9',
      status: 'running',
      lastSeq: 12,
      error: '',
      updatedAt: 9,
      retryable: false,
    },
  ]);
});

test('renames with PATCH and returns the title the server stored', async () => {
  const { api: sessions, fetcher } = api(
    response(200, { session: { ...row, title: 'Halves' } }),
  );
  await expect(sessions.rename('s1', 'Halves')).resolves.toBe('Halves');
  expect(fetcher.mock.calls[0][1]).toMatchObject({
    method: 'PATCH',
    body: JSON.stringify({ title: 'Halves' }),
  });
});

test('deletes with DELETE and refuses an unconfirmed acknowledgement', async () => {
  const ok = api(response(200, { deleted: true, session_id: 's1' }));
  await expect(ok.api.remove('s1')).resolves.toBeUndefined();
  expect(ok.fetcher.mock.calls[0][1]).toMatchObject({ method: 'DELETE' });

  const refused = api(response(200, { deleted: false }));
  await expect(refused.api.remove('s1')).rejects.toMatchObject({
    kind: 'invalid-response',
  });
});

test('a missing conversation keeps its HTTP status for the caller', async () => {
  const { api: sessions } = api(response(404, { detail: 'Session not found' }));
  await expect(sessions.get('gone')).rejects.toMatchObject({
    status: 404,
  });
});

test('rejects a page the app cannot render', async () => {
  const { api: sessions } = api(response(200, { sessions: 'nope' }));
  await expect(sessions.list({ limit: 10, offset: 0 })).rejects.toBeInstanceOf(
    ApiError,
  );
});

test('encodes an identifier so it cannot escape its path segment', async () => {
  const { api: sessions, fetcher } = api(
    response(200, { ...row, id: 'a/b', session_id: 'a/b', messages: [] }),
  );
  await sessions.get('a/b');
  expect(fetcher.mock.calls[0][0]).toBe(`${origin}/api/sessions/a%2Fb`);
});

test('an unusual status falls back to idle instead of inventing a state', async () => {
  const { api: sessions } = api(
    response(200, { sessions: [{ ...row, status: 'mystery' }] }),
  );
  const page = await sessions.list({ limit: 10, offset: 0 });
  expect(page.sessions[0].status).toBe('idle');
});
