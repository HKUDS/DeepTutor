import type {
  SocketMessageEvent,
  TurnSocket,
} from '@/features/chat/transport/socket';

import { MobileChatRuntime } from '../src/features/chat/MobileChatRuntime';
import { ApiError } from '../src/services/apiClient';
import type {
  SessionApi,
  SessionDetail,
  SessionMessage,
} from '../src/services/sessionApi';
import type {
  LastSessionStore,
  RecoveryRecord,
  TurnRecoveryStore,
} from '../src/storage/turnRecovery';

type Listener = (event: SocketMessageEvent) => void;
type Frame = { type: string; [key: string]: unknown };

class FakeSocket implements TurnSocket {
  readyState = 0;
  sent: Frame[] = [];
  private listeners = new Map<string, Listener>();

  addEventListener(type: string, listener: Listener) {
    this.listeners.set(type, listener);
  }
  send(raw: string) {
    this.sent.push(JSON.parse(raw) as Frame);
  }
  close(code = 1000) {
    this.readyState = 3;
    this.emit('close', { code });
  }
  open() {
    this.readyState = 1;
    this.emit('open');
  }
  frame(frame: Frame) {
    this.emit('message', {
      data: JSON.stringify({ protocol_version: '2.0', ...frame }),
    });
  }
  private emit(type: string, event: { data?: string; code?: number } = {}) {
    this.listeners.get(type)?.({ data: undefined, ...event });
  }
}

function streamEvent(
  type: string,
  seq: number,
  fields: Record<string, unknown> = {},
) {
  return {
    type,
    seq,
    timestamp: 1,
    turn_id: 'turn-7',
    session_id: 'session-1',
    ...fields,
  };
}

function message(
  id: number | string,
  role: SessionMessage['role'],
  content: string,
): SessionMessage {
  return {
    id: String(id),
    role,
    content,
    createdAt: typeof id === 'number' ? id : 0,
    failedTurn: null,
    ...(role === 'user' ? { turnId: 'turn-7' } : {}),
  };
}

function detail(overrides: Partial<SessionDetail> = {}): SessionDetail {
  return {
    id: 'session-1',
    title: 'Fractions',
    createdAt: 1,
    updatedAt: 2,
    messageCount: 1,
    lastMessage: '',
    status: 'idle',
    activeTurnId: '',
    messages: [message(1, 'user', 'What is a half?')],
    activeTurns: [],
    ...overrides,
  };
}

function live(overrides: Partial<SessionDetail['activeTurns'][number]> = {}) {
  return {
    id: 'turn-7',
    status: 'running' as const,
    lastSeq: 9,
    error: '',
    updatedAt: 5,
    retryable: false,
    ...overrides,
  };
}

function memoryStore(initial: RecoveryRecord | null) {
  let current = initial;
  const store = {
    read: jest.fn(async () => current),
    write: jest.fn(async (_scope: unknown, record: RecoveryRecord) => {
      current = record;
    }),
    clear: jest.fn(async () => {
      current = null;
    }),
    clearServer: jest.fn(async () => {
      current = null;
    }),
  };
  return {
    store: store as unknown as TurnRecoveryStore,
    calls: store,
    peek: () => current,
  };
}

const record: RecoveryRecord = {
  version: 1,
  sessionId: 'session-1',
  turnId: 'turn-7',
  clientSubmissionId: 'submission-7',
  lastSeq: 9,
  status: 'running',
  updatedAt: Date.now(),
};

function harness(
  api: Partial<SessionApi>,
  recovery: TurnRecoveryStore | null,
  options: {
    onAuthExpired?: () => void;
    lastSession?: LastSessionStore;
  } = {},
) {
  const sockets: FakeSocket[] = [];
  const runtime = new MobileChatRuntime({
    origin: 'https://tutor.example.test',
    socketFactory: () => {
      const socket = new FakeSocket();
      sockets.push(socket);
      return socket;
    },
    sessionApi: api as SessionApi,
    recovery: recovery ?? undefined,
    lastSession: options.lastSession,
    scope: recovery
      ? {
          origin: 'https://tutor.example.test',
          account: 'acct-1',
          workspace: '',
        }
      : null,
    onAuthExpired: options.onAuthExpired,
  });
  return { runtime, sockets };
}

function lastSessionStore(initial: string | null) {
  let current = initial;
  const store = {
    read: jest.fn(async () => current),
    write: jest.fn(async (_scope: unknown, sessionId: string) => {
      current = sessionId;
    }),
    clear: jest.fn(async () => {
      current = null;
    }),
  };
  return {
    store: store as unknown as LastSessionStore,
    calls: store,
    peek: () => current,
  };
}

async function settle() {
  for (let i = 0; i < 12; i += 1) await Promise.resolve();
}

beforeEach(() => {
  jest.useFakeTimers();
});
afterEach(() => {
  jest.useRealTimers();
});

test.each(['select', 'reset', 'stop'])(
  'ignores a delayed last-session read after %s',
  async action => {
    const last = lastSessionStore(null);
    let resolveRead: (value: string) => void = () => {};
    last.calls.read.mockImplementationOnce(
      () =>
        new Promise(resolve => {
          resolveRead = resolve;
        }),
    );
    const get = jest.fn(async () => detail({ id: 'session-2' }));
    const { runtime } = harness({ get }, memoryStore(null).store, {
      lastSession: last.store,
    });
    runtime.start();
    await settle();
    expect(last.calls.read).toHaveBeenCalled();
    if (action === 'select') await runtime.openSession('session-2');
    else if (action === 'reset') runtime.reset();
    else runtime.stop();
    resolveRead('session-1');
    await settle();
    expect(get.mock.calls.flat()).not.toContain('session-1');
    expect(runtime.getSnapshot().sessionId).toBe(
      action === 'select' ? 'session-2' : null,
    );
    runtime.stop();
  },
);

test('aborts the REST request and rejects its late response after reset', async () => {
  let resolveDetail: (value: SessionDetail) => void = () => {};
  const get = jest.fn(
    (_id: string, _signal?: AbortSignal) =>
      new Promise<SessionDetail>(resolve => {
        resolveDetail = resolve;
      }),
  );
  const { runtime } = harness({ get }, memoryStore(record).store);
  runtime.start();
  await settle();
  expect(get).toHaveBeenCalledTimes(1);
  runtime.reset();
  expect(get.mock.calls[0][1]?.aborted).toBe(true);
  resolveDetail(detail({ activeTurns: [live()] }));
  await settle();
  expect(runtime.getSnapshot()).toMatchObject({
    sessionId: null,
    status: 'idle',
  });
  runtime.stop();
});

test('reconnecting before admission does not automatically resend the question', async () => {
  const { runtime, sockets } = harness({}, memoryStore(null).store);
  runtime.start();
  await settle();
  sockets[0].open();
  expect(runtime.send('A question')).toBe(true);
  expect(sockets[0].sent[0].type).toBe('start_turn');
  sockets[0].close(1006);
  jest.advanceTimersByTime(500);
  sockets[1].open();
  expect(sockets[1].sent.some(frame => frame.type === 'start_turn')).toBe(false);
  runtime.stop();
});

test.each([true, false])(
  'a live replay preserves exactly one already-saved answer (linked=%s)',
  async linked => {
    const get = jest.fn(async () =>
      detail({
        messages: [
          message(1, 'user', 'Question'),
          { ...message(2, 'assistant', 'Saved answer'), parentMessageId: '1' },
        ],
        activeTurns: [live(linked ? { assistantMessageId: '2' } : {})],
      }),
    );
    const { runtime, sockets } = harness({ get }, memoryStore(record).store);
    runtime.start();
    await settle();
    const socket = sockets.at(-1)!;
    socket.open();
    socket.frame(streamEvent('content', 1, { content: 'Saved ' }));
    socket.frame(streamEvent('content', 2, { content: 'answer' }));
    socket.frame(streamEvent('done', 3));
    expect(runtime.getSnapshot().messages).toMatchObject([
      { question: 'Question', answer: 'Saved answer' },
    ]);
    runtime.stop();
  },
);

test('cold start resumes a live turn and rebuilds its answer from the log', async () => {
  const memory = memoryStore(record);
  const get = jest.fn(async () => detail({ activeTurns: [live()] }));
  const { runtime, sockets } = harness({ get }, memory.store);

  runtime.start();
  await settle();
  expect(get).toHaveBeenCalledWith('session-1', expect.any(AbortSignal));

  const resumed = sockets.at(-1)!;
  resumed.open();
  expect(resumed.sent[0]).toEqual({
    type: 'resume_from',
    turn_id: 'turn-7',
    seq: 0,
    protocol_version: '2.0',
  });
  expect(runtime.getSnapshot()).toMatchObject({
    status: 'recovering',
    sessionId: 'session-1',
    sessionTitle: 'Fractions',
    messages: [{ question: 'What is a half?', answer: '' }],
    recovery: { kind: 'resumed' },
  });

  resumed.frame(streamEvent('content', 1, { content: 'One of ' }));
  resumed.frame(streamEvent('content', 2, { content: 'two parts.' }));
  resumed.frame(streamEvent('done', 3));
  expect(runtime.getSnapshot()).toMatchObject({ status: 'completed' });
  expect(runtime.getSnapshot().messages[0].answer).toBe('One of two parts.');
  expect(memory.calls.clear).toHaveBeenCalled();
  runtime.stop();
});

test('a turn that finished while away is read from the transcript, not resumed', async () => {
  const memory = memoryStore(record);
  const get = jest.fn(async () =>
    detail({
      status: 'completed',
      messages: [
        message(1, 'user', 'What is a half?'),
        message(2, 'assistant', 'One of two equal parts.'),
      ],
    }),
  );
  const { runtime, sockets } = harness({ get }, memory.store);

  runtime.start();
  await settle();
  const resumed = sockets.at(-1)!;
  resumed.open();

  expect(
    resumed.sent.filter(frame => frame.type === 'resume_from'),
  ).toHaveLength(0);
  expect(runtime.getSnapshot()).toMatchObject({
    status: 'completed',
    messages: [{ answer: 'One of two equal parts.' }],
    recovery: { kind: 'settled' },
  });
  expect(memory.peek()).toBeNull();
  runtime.stop();
});

test('a conversation the server no longer has is reported, never faked', async () => {
  const memory = memoryStore(record);
  const get = jest.fn(async () => {
    throw new ApiError('http', 'The server returned HTTP 404.', 404);
  });
  const { runtime } = harness({ get }, memory.store);

  runtime.start();
  await settle();

  expect(runtime.getSnapshot()).toMatchObject({
    status: 'idle',
    sessionId: null,
    sessionTitle: '',
    messages: [],
    history: 'idle',
    recovery: { kind: 'unavailable' },
  });
  expect(memory.peek()).toBeNull();
  runtime.stop();
});

test('an expired cookie during recovery asks for a new sign-in', async () => {
  const memory = memoryStore(record);
  const onAuthExpired = jest.fn();
  const get = jest.fn(async () => {
    throw new ApiError('unauthorized', 'Sign-in is required.', 401);
  });
  const { runtime } = harness({ get }, memory.store, { onAuthExpired });

  runtime.start();
  await settle();

  expect(onAuthExpired).toHaveBeenCalledTimes(1);
  expect(runtime.getSnapshot()).toMatchObject({
    status: 'idle',
    history: 'failed',
    error: 'Sign in again to load this conversation.',
  });
  expect(memory.peek()).not.toBeNull();
  runtime.stop();
});

test('a slow transcript load cannot overwrite a newer conversation', async () => {
  const memory = memoryStore(null);
  let resolveFirst: (value: SessionDetail) => void = () => {};
  const get = jest
    .fn<Promise<SessionDetail>, [string]>()
    .mockImplementationOnce(
      () =>
        new Promise<SessionDetail>(resolve => {
          resolveFirst = resolve;
        }),
    )
    .mockImplementationOnce(async () =>
      detail({ id: 'session-2', title: 'Decimals' }),
    );
  const { runtime } = harness({ get }, memory.store);
  runtime.start();
  runtime.reset();

  const first = runtime.openSession('session-1');
  const second = runtime.openSession('session-2');
  await second;
  resolveFirst(detail({ id: 'session-1', title: 'Fractions' }));
  await expect(first).resolves.toBe(false);

  expect(runtime.getSnapshot()).toMatchObject({
    sessionId: 'session-2',
    sessionTitle: 'Decimals',
  });
  runtime.stop();
});

test('switching conversations is refused while a response is running', async () => {
  const memory = memoryStore(null);
  const get = jest.fn(async () => detail());
  const { runtime, sockets } = harness({ get }, memory.store);
  runtime.start();
  await settle();
  sockets.at(-1)!.open();
  runtime.send('Question');

  await expect(runtime.openSession('session-9')).resolves.toBe(false);
  expect(get).not.toHaveBeenCalled();
  expect(runtime.getSnapshot().error).toContain(
    'Stop the current response before switching',
  );
  runtime.stop();
});

test('persists the admitted turn and clears it once the run ends', async () => {
  const memory = memoryStore(null);
  const { runtime, sockets } = harness({}, memory.store);
  runtime.start();
  await settle();
  const socket = sockets.at(-1)!;
  socket.open();

  expect(runtime.send('Question')).toBe(true);
  socket.frame(streamEvent('session', 1));
  await settle();
  expect(memory.calls.write).toHaveBeenCalledTimes(1);
  expect(memory.peek()).toMatchObject({
    sessionId: 'session-1',
    turnId: 'turn-7',
    lastSeq: 1,
    status: 'running',
    clientSubmissionId: expect.any(String),
  });

  socket.frame(streamEvent('done', 2));
  await settle();
  expect(memory.peek()).toBeNull();
  runtime.stop();
});

test('a waiting turn is persisted even when only one frame arrives', async () => {
  const memory = memoryStore(null);
  const { runtime, sockets } = harness({}, memory.store);
  runtime.start();
  await settle();
  const socket = sockets.at(-1)!;
  socket.open();
  runtime.send('Question');
  socket.frame(streamEvent('wait_for_input', 1, { content: 'Which subject?' }));
  await settle();

  expect(memory.peek()).toMatchObject({
    status: 'waiting_for_input',
    turnId: 'turn-7',
  });
  expect(runtime.getSnapshot()).toMatchObject({
    status: 'waiting_for_input',
    waitingPrompt: 'Which subject?',
  });
  runtime.stop();
});

test('a duplicate submission cannot start a second model call', () => {
  const memory = memoryStore(null);
  const { runtime, sockets } = harness({}, memory.store);
  runtime.start();
  const socket = sockets.at(-1)!;
  socket.open();

  expect(runtime.send('First')).toBe(true);
  expect(runtime.send('Second')).toBe(false);
  socket.frame(streamEvent('done', 1));
  expect(runtime.send('Third')).toBe(true);
  expect(socket.sent.filter(frame => frame.type === 'start_turn')).toHaveLength(
    2,
  );
  runtime.stop();
});

test('reopening the same conversation keeps one transcript', async () => {
  const memory = memoryStore(null);
  const get = jest.fn(async () =>
    detail({
      messages: [
        message(1, 'user', 'What is a half?'),
        message(2, 'assistant', 'One of two equal parts.'),
      ],
      status: 'completed',
    }),
  );
  const { runtime } = harness({ get }, memory.store);
  runtime.start();
  await runtime.openSession('session-1');
  await runtime.openSession('session-1');

  expect(runtime.getSnapshot().messages).toHaveLength(1);
  expect(get).toHaveBeenCalledTimes(2);
  runtime.stop();
});

test('a relaunch quietly reopens the conversation that was open last', async () => {
  const memory = memoryStore(null);
  const last = lastSessionStore('session-1');
  const get = jest.fn(async () =>
    detail({
      status: 'completed',
      messages: [
        message(1, 'user', 'What is a half?'),
        message(2, 'assistant', 'One of two equal parts.'),
      ],
    }),
  );
  const { runtime } = harness({ get }, memory.store, {
    lastSession: last.store,
  });

  runtime.start();
  await settle();

  expect(get).toHaveBeenCalledWith('session-1', expect.any(AbortSignal));
  expect(runtime.getSnapshot()).toMatchObject({
    sessionId: 'session-1',
    sessionTitle: 'Fractions',
    status: 'completed',
    history: 'ready',
    // Nothing was running, so there is nothing to announce.
    recovery: null,
    error: null,
  });
  runtime.stop();
});

test('a remembered conversation the server dropped is forgotten silently', async () => {
  const memory = memoryStore(null);
  const last = lastSessionStore('session-1');
  const get = jest.fn(async () => {
    throw new ApiError('http', 'The server returned HTTP 404.', 404);
  });
  const { runtime, sockets } = harness({ get }, memory.store, {
    lastSession: last.store,
  });

  runtime.start();
  sockets[0].open();
  await settle();

  expect(runtime.getSnapshot()).toMatchObject({
    connection: 'connected',
    sessionId: null,
    messages: [],
    history: 'idle',
    status: 'idle',
    recovery: null,
    error: null,
  });
  expect(last.calls.clear).toHaveBeenCalled();
  expect(last.peek()).toBeNull();
  runtime.stop();
});

test('a recovery record cannot decorate a conversation opened instead', async () => {
  const memory = memoryStore(record);
  let release: (value: SessionDetail) => void = () => {};
  const get = jest
    .fn<Promise<SessionDetail>, [string]>()
    .mockImplementationOnce(
      () =>
        new Promise<SessionDetail>(resolve => {
          release = resolve;
        }),
    )
    .mockImplementationOnce(async () =>
      detail({
        id: 'session-2',
        title: 'Decimals',
        status: 'completed',
        messages: [
          message(3, 'user', 'And decimals?'),
          message(4, 'assistant', 'They are fractions too.'),
        ],
      }),
    );
  const { runtime } = harness({ get }, memory.store);
  runtime.start();
  await settle();

  await runtime.openSession('session-2');
  // The abandoned load for the recorded conversation must not land either.
  release(detail({ activeTurns: [live()] }));
  await settle();

  expect(runtime.getSnapshot()).toMatchObject({
    sessionId: 'session-2',
    sessionTitle: 'Decimals',
    status: 'completed',
    // No "finished while you were away" banner: that record was for session-1.
    recovery: null,
  });
  runtime.stop();
});

test('retrying an unconfirmed start reuses its submission id', () => {
  const memory = memoryStore(null);
  const { runtime, sockets } = harness({}, memory.store);
  runtime.start();
  const first = sockets.at(-1)!;
  first.open();

  expect(runtime.send('Explain halves')).toBe(true);
  const submitted = first.sent.find(frame => frame.type === 'start_turn');
  const submissionId = submitted?.client_submission_id;
  expect(typeof submissionId).toBe('string');

  // The server never confirmed; the runtime gives up and reconnects.
  jest.advanceTimersByTime(30_000);
  expect(runtime.getSnapshot().status).toBe('failed');

  const retrySocket = sockets.at(-1)!;
  expect(retrySocket).not.toBe(first);
  retrySocket.open();

  // Same question: the server can recognise the retry and must not run it twice.
  expect(runtime.send('Explain halves')).toBe(true);
  const retried = retrySocket.sent.filter(frame => frame.type === 'start_turn');
  expect(retried).toHaveLength(1);
  expect(retried[0].client_submission_id).toBe(submissionId);

  // Once a turn is admitted the id is spent, so a new question is a new submit.
  retrySocket.frame(streamEvent('content', 1, { content: 'Half of one.' }));
  retrySocket.frame(streamEvent('done', 2));
  expect(runtime.send('Now quarters')).toBe(true);
  const later = retrySocket.sent.filter(frame => frame.type === 'start_turn');
  expect(later).toHaveLength(2);
  expect(later[1].client_submission_id).not.toBe(submissionId);
  runtime.stop();
});
