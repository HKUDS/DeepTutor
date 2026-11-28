import type {
  SocketMessageEvent,
  TurnSocket,
} from '@/features/chat/transport/socket';

import { MobileChatRuntime } from '../src/features/chat/MobileChatRuntime';

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
    const listener = this.listeners.get(type);
    listener?.({ data: undefined, ...event });
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
    turn_id: 'turn-1',
    session_id: 'session-1',
    ...fields,
  };
}

function harness(
  options: Pick<
    ConstructorParameters<typeof MobileChatRuntime>[0],
    'onAuthExpired' | 'refreshAuth'
  > = {},
) {
  const sockets: FakeSocket[] = [];
  const runtime = new MobileChatRuntime({
    ...options,
    origin: 'https://tutor.example.test',
    socketFactory: url => {
      expect(url).toBe('wss://tutor.example.test/ws?dt_workspace=');
      const socket = new FakeSocket();
      sockets.push(socket);
      return socket;
    },
  });
  runtime.start();
  return { runtime, sockets, socket: sockets[0] };
}

beforeEach(() => {
  jest.useFakeTimers();
});
afterEach(() => {
  jest.useRealTimers();
});

test('plays two turns, resumes a gap, and ignores duplicate or retired events', () => {
  const { runtime, socket, sockets } = harness();
  socket.open();
  expect(runtime.send('First question')).toBe(true);
  expect(socket.sent[0]).toMatchObject({
    type: 'start_turn',
    content: 'First question',
    protocol_version: '2.0',
    client_submission_id: expect.any(String),
  });
  socket.frame(streamEvent('session', 1));
  socket.frame(streamEvent('content', 2, { content: 'One ' }));
  socket.close(1006);
  expect(runtime.getSnapshot().connection).toBe('recovering');
  jest.advanceTimersByTime(400);
  const resumed = sockets[1];
  resumed.open();
  expect(resumed.sent[0]).toEqual({
    type: 'resume_from',
    turn_id: 'turn-1',
    seq: 2,
    protocol_version: '2.0',
  });
  resumed.frame(streamEvent('content', 2, { content: 'replay duplicate ' }));
  resumed.frame(streamEvent('done', 4));
  resumed.frame(streamEvent('content', 3, { content: 'two' }));
  expect(runtime.getSnapshot().messages[0].answer).toBe('One two');
  expect(runtime.getSnapshot().phase).toBe('ready');

  expect(runtime.send('Next question')).toBe(true);
  expect(resumed.sent.at(-1)).toMatchObject({
    type: 'start_turn',
    session_id: 'session-1',
    content: 'Next question',
  });
  resumed.frame(streamEvent('content', 5, { content: 'late previous answer' }));
  resumed.frame(streamEvent('session', 1, { turn_id: 'turn-2' }));
  resumed.frame(
    streamEvent('content', 2, {
      turn_id: 'turn-2',
      session_id: 'unrelated-session',
      content: 'wrong session',
    }),
  );
  resumed.frame(
    streamEvent('content', 2, {
      turn_id: 'turn-2',
      content: 'private attempt',
      metadata: { call_id: 'attempt', call_kind: 'explore_context' },
    }),
  );
  resumed.frame(
    streamEvent('content', 3, { turn_id: 'turn-2', content: 'Next answer' }),
  );
  resumed.frame(streamEvent('done', 4, { turn_id: 'turn-2' }));
  expect(runtime.getSnapshot().messages.map(m => m.answer)).toEqual([
    'One two',
    'Next answer',
  ]);
  runtime.stop();
});

test('reopens a suspended socket with the current cursor and discards a retired connection', () => {
  const { runtime, socket, sockets } = harness();
  socket.open();
  runtime.send('Question');
  socket.frame(streamEvent('content', 1, { content: 'Partial' }));
  runtime.setVisible(false);
  runtime.setVisible(true);
  const reopened = sockets[1];
  reopened.open();
  expect(reopened.sent[0]).toMatchObject({
    type: 'resume_from',
    turn_id: 'turn-1',
    seq: 1,
  });
  socket.frame(streamEvent('content', 2, { content: 'stale' }));
  reopened.frame(streamEvent('content', 2, { content: ' answer' }));
  reopened.frame(streamEvent('done', 3));
  expect(runtime.getSnapshot().messages[0].answer).toBe('Partial answer');
  runtime.reset();
  const newConversation = sockets[2];
  newConversation.open();
  runtime.send('Unrelated question');
  expect(newConversation.sent[0]).not.toHaveProperty('session_id');
  reopened.frame(streamEvent('content', 4, { content: 'late old thread' }));
  expect(runtime.getSnapshot().messages[0].answer).toBe('');
  runtime.stop();
});

test('sends cancellation after admission and returns to ready on the server ACK', async () => {
  const { runtime, socket } = harness();
  socket.open();
  runtime.send('Slow question');
  await runtime.cancel();
  expect(runtime.getSnapshot().phase).toBe('stopping');
  expect(socket.sent).toHaveLength(1);
  socket.frame(streamEvent('session', 1));
  const request = socket.sent[1];
  expect(request).toMatchObject({ type: 'cancel_turn', turn_id: 'turn-1' });
  socket.frame(streamEvent('done', 2, { metadata: { status: 'cancelled' } }));
  expect(runtime.getSnapshot().phase).toBe('stopping');
  expect(runtime.send('Wait for ownership to be released')).toBe(false);
  socket.frame({
    type: 'command_ack',
    command_id: String(request.command_id),
    command_type: 'cancel_turn',
    accepted: true,
  });
  await Promise.resolve();
  expect(runtime.getSnapshot().phase).toBe('ready');
  expect(runtime.send('Next')).toBe(true);
  runtime.stop();
});

test('lets a learner reply to a waiting turn and exits waiting when the server rejects it', async () => {
  const { runtime, socket } = harness();
  socket.open();
  runtime.send('Question');
  socket.frame(streamEvent('wait_for_input', 1, { content: 'Which subject?' }));
  expect(runtime.getSnapshot()).toMatchObject({
    phase: 'waiting',
    waitingPrompt: 'Which subject?',
  });
  const pending = runtime.reply('Math');
  const reply = socket.sent[1];
  expect(reply).toMatchObject({
    type: 'submit_user_reply',
    text: 'Math',
    turn_id: 'turn-1',
  });
  socket.frame({
    type: 'command_ack',
    command_id: String(reply.command_id),
    command_type: 'submit_user_reply',
    accepted: true,
  });
  await expect(pending).resolves.toBe(true);
  expect(runtime.getSnapshot().phase).toBe('running');
  socket.frame(streamEvent('wait_for_input', 2, { content: 'Which lesson?' }));
  const next = runtime.reply('Fractions');
  socket.frame({
    type: 'command_ack',
    command_id: String(socket.sent[2].command_id),
    command_type: 'submit_user_reply',
    accepted: false,
  });
  await expect(next).resolves.toBe(false);
  expect(runtime.getSnapshot()).toMatchObject({
    phase: 'ready',
    waitingPrompt: null,
    error: expect.any(String),
  });
  runtime.stop();
});

test('clears a rejected durable start and recovers from a missing admission response', () => {
  const { runtime, sockets, socket } = harness();
  socket.open();
  runtime.send('Rejected');
  socket.frame({
    type: 'protocol_error',
    error_code: 'start_turn_rejected',
    message: 'Configure a model first.',
    retryable: true,
  });
  expect(runtime.getSnapshot()).toMatchObject({
    phase: 'ready',
    error: 'The server rejected the request.',
  });
  sockets[1].open();
  expect(sockets[1].sent).toHaveLength(0);
  runtime.send('Server stalls');
  jest.advanceTimersByTime(30_000);
  expect(runtime.getSnapshot()).toMatchObject({
    phase: 'ready',
    error: expect.stringContaining('did not confirm'),
  });
  sockets[2].open();
  expect(sockets[2].sent).toHaveLength(0);
  runtime.stop();
});

test('terminal errors release the composer without waiting for DONE', () => {
  const { runtime, socket } = harness();
  socket.open();
  runtime.send('Question');
  socket.frame(
    streamEvent('error', 1, {
      content: 'PRIVATE_PROVIDER_DETAIL',
      metadata: { turn_terminal: true },
    }),
  );
  expect(runtime.getSnapshot()).toMatchObject({
    phase: 'ready',
    error: 'The server could not finish the response.',
  });
  expect(runtime.send('Next')).toBe(true);
  runtime.stop();
});

test('rechecks HTTP authentication after ambiguous handshake failure', async () => {
  const refreshAuth = jest.fn().mockResolvedValue(true);
  const onAuthExpired = jest.fn();
  const { runtime, socket, sockets } = harness({ refreshAuth, onAuthExpired });
  socket.close(1006);
  await Promise.resolve();
  expect(refreshAuth).toHaveBeenCalledTimes(1);
  expect(onAuthExpired).not.toHaveBeenCalled();
  jest.advanceTimersByTime(400);
  sockets[1].close(4001);
  expect(onAuthExpired).toHaveBeenCalledTimes(1);
  runtime.stop();
});

test('makes a waiting prompt actionable again if reply or cancellation loses its ACK', async () => {
  const { runtime, socket } = harness();
  socket.open();
  runtime.send('Question');
  socket.frame(streamEvent('wait_for_input', 1, { content: 'What topic?' }));
  const reply = runtime.reply('Functions');
  jest.advanceTimersByTime(30_000);
  await expect(reply).resolves.toBe(false);
  expect(runtime.getSnapshot()).toMatchObject({
    phase: 'waiting',
    waitingPrompt: 'What topic?',
    error: expect.stringContaining('confirm your reply'),
  });

  const stop = runtime.cancel();
  expect(runtime.getSnapshot().phase).toBe('stopping');
  jest.advanceTimersByTime(30_000);
  await stop;
  expect(runtime.getSnapshot()).toMatchObject({
    phase: 'waiting',
    waitingPrompt: 'What topic?',
    error: expect.stringContaining('confirm the stop request'),
  });

  const retry = runtime.cancel();
  const request = socket.sent.at(-1)!;
  socket.frame({
    type: 'command_ack',
    command_id: String(request.command_id),
    command_type: 'cancel_turn',
    accepted: false,
  });
  await retry;
  expect(runtime.getSnapshot()).toMatchObject({
    phase: 'waiting',
    waitingPrompt: 'What topic?',
    error: expect.stringContaining('Try Stop again'),
  });
  runtime.stop();
});

test('replays retryable subscription failures on the same cursor, then ends a matching terminal failure', () => {
  const { runtime, socket, sockets } = harness();
  socket.open();
  runtime.send('Question');
  socket.frame(streamEvent('wait_for_input', 1, { content: 'What topic?' }));
  const failure = {
    type: 'protocol_error',
    error_code: 'subscription_failed',
    turn_id: 'turn-1',
    retryable: true,
    message: 'Could not restore the turn.',
  };
  socket.frame({ ...failure, retryable: false, turn_id: 'retired-turn' });
  expect(runtime.getSnapshot()).toMatchObject({
    phase: 'waiting',
    error: null,
  });
  socket.frame(failure);
  expect(runtime.getSnapshot()).toMatchObject({
    phase: 'waiting',
    error: 'The connection could not recover this response.',
  });
  jest.advanceTimersByTime(500);
  const reopened = sockets[1];
  reopened.open();
  expect(reopened.sent[0]).toMatchObject({
    type: 'resume_from',
    turn_id: 'turn-1',
    seq: 1,
  });
  reopened.frame({
    ...failure,
    retryable: false,
    session_id: 'another-session',
  });
  expect(runtime.getSnapshot().phase).toBe('waiting');
  reopened.frame({ ...failure, retryable: false });
  expect(runtime.getSnapshot()).toMatchObject({
    phase: 'ready',
    waitingPrompt: null,
    error: 'The connection could not recover this response.',
  });
  runtime.stop();
});

test('retries a handshake that never opens and ignores a late socket', () => {
  const { runtime, socket, sockets } = harness();
  jest.advanceTimersByTime(13_000);
  expect(sockets).toHaveLength(2);
  socket.open();
  expect(socket.readyState).toBe(3);
  expect(runtime.getSnapshot().connection).not.toBe('connected');
  sockets[1].open();
  expect(runtime.getSnapshot().connection).toBe('connected');
  runtime.stop();
  jest.advanceTimersByTime(60_000);
  expect(sockets).toHaveLength(2);
});

test('a silent admitted turn attempts replay and can be left without reusing its session', () => {
  const { runtime, socket, sockets } = harness();
  socket.open();
  runtime.send('Question');
  socket.frame(streamEvent('content', 1, { content: 'Partial answer' }));
  jest.advanceTimersByTime(60_000);
  sockets[1].open();
  expect(sockets[1].sent[0]).toMatchObject({
    type: 'resume_from',
    turn_id: 'turn-1',
    seq: 1,
  });
  jest.advanceTimersByTime(30_000);
  expect(runtime.getSnapshot()).toMatchObject({
    phase: 'running',
    canLeaveTurn: true,
  });
  runtime.reset();
  sockets[2].open();
  expect(runtime.send('New chat')).toBe(true);
  expect(sockets[2].sent[0]).not.toHaveProperty('session_id');
  runtime.stop();
});

test.each(['rejected', 'timed out'])(
  'a completed turn releases the composer after Stop is %s',
  async result => {
    const { runtime, socket } = harness();
    socket.open();
    runtime.send('Question');
    socket.frame(streamEvent('session', 1));
    const stop = runtime.cancel();
    socket.frame(streamEvent('done', 2));
    expect(runtime.getSnapshot().phase).toBe('stopping');
    if (result === 'timed out') {
      jest.advanceTimersByTime(30_000);
    } else {
      socket.frame({
        type: 'command_ack',
        command_id: String(socket.sent.at(-1)?.command_id),
        command_type: 'cancel_turn',
        accepted: false,
      });
    }
    await stop;
    expect(runtime.getSnapshot().phase).toBe('ready');
    expect(runtime.send('Next question')).toBe(true);
    expect(socket.sent.at(-1)).not.toHaveProperty('session_id');
    runtime.stop();
  },
);

test('bounds repeated replay failures and lets the learner reconnect without abandoning the turn', () => {
  const { runtime, socket, sockets } = harness();
  socket.open();
  runtime.send('Question');
  socket.frame(streamEvent('content', 1, { content: 'Partial' }));
  const failure = {
    type: 'protocol_error',
    error_code: 'subscription_failed',
    turn_id: 'turn-1',
    retryable: true,
    message: 'Could not restore the turn.',
  };
  for (const [i, delay] of [500, 1000, 2000].entries()) {
    sockets[i].frame(failure);
    jest.advanceTimersByTime(delay);
    sockets[i + 1].open();
  }
  sockets[3].frame(failure);
  expect(runtime.getSnapshot()).toMatchObject({
    phase: 'running',
    connection: 'idle',
    error: expect.stringContaining('Reconnect'),
  });
  runtime.retryConnection();
  sockets[4].open();
  expect(sockets[4].sent[0]).toMatchObject({
    type: 'resume_from',
    turn_id: 'turn-1',
    seq: 1,
  });
  sockets[4].frame(streamEvent('content', 2, { content: ' answer' }));
  sockets[4].frame(streamEvent('done', 3));
  expect(runtime.getSnapshot()).toMatchObject({ phase: 'ready', error: null });
  expect(runtime.getSnapshot().messages[0].answer).toBe('Partial answer');
  runtime.stop();
});
