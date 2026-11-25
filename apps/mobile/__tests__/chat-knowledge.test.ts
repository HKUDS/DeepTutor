import type {
  SocketMessageEvent,
  TurnSocket,
} from '@/features/chat/transport/socket';

import { MobileChatRuntime } from '../src/features/chat/MobileChatRuntime';
import type {
  SessionApi,
  SessionDetail,
  SessionMessage,
} from '../src/services/sessionApi';

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
    this.emit('message', { data: JSON.stringify({ protocol_version: '2.0', ...frame }) });
  }
  lastStart() {
    const frames = this.sent.filter(frame => frame.type === 'start_turn');
    return frames[frames.length - 1];
  }
  private emit(type: string, event: { data?: string; code?: number } = {}) {
    this.listeners.get(type)?.({ data: undefined, ...event });
  }
}

/** Play the one turn a question opened through to its end. */
function finish(socket: FakeSocket) {
  socket.frame({
    type: 'session',
    seq: 1,
    timestamp: 1,
    turn_id: 'turn-1',
    session_id: 'session-1',
  });
  socket.frame({
    type: 'done',
    seq: 2,
    timestamp: 1,
    turn_id: 'turn-1',
    session_id: 'session-1',
  });
}

function message(
  id: string,
  role: SessionMessage['role'],
  content: string,
): SessionMessage {
  return {
    id,
    role,
    content,
    createdAt: 1,
    failedTurn: null,
    ...(role === 'user' ? { turnId: 'turn-1' } : {}),
  };
}

function detail(overrides: Partial<SessionDetail> = {}): SessionDetail {
  return {
    id: 'session-1',
    title: 'Waves',
    createdAt: 1,
    updatedAt: 2,
    messageCount: 1,
    lastMessage: '',
    status: 'idle',
    activeTurnId: '',
    messages: [message('1', 'user', 'What is a wave?')],
    activeTurns: [],
    knowledgeBases: [],
    ...overrides,
  };
}

let running: MobileChatRuntime | null = null;

function harness(get: jest.Mock = jest.fn(async () => detail())) {
  const sockets: FakeSocket[] = [];
  const runtime = new MobileChatRuntime({
    origin: 'https://tutor.example.test',
    socketFactory: () => {
      const socket = new FakeSocket();
      sockets.push(socket);
      return socket;
    },
    sessionApi: { get } as unknown as SessionApi,
  });
  runtime.start();
  sockets[0].open();
  running = runtime;
  return { runtime, socket: sockets[0], sockets };
}

beforeEach(() => {
  jest.useFakeTimers();
});

afterEach(() => {
  running?.stop();
  running = null;
  jest.useRealTimers();
});

test('a question is sent without a knowledge override until one is chosen', () => {
  const { runtime, socket } = harness();
  expect(runtime.getSnapshot().knowledgeBases).toEqual([]);
  expect(runtime.getSnapshot().knowledgeBasesTouched).toBe(false);

  expect(runtime.send('What is a wave?')).toBe(true);
  // Omitted, not empty: the server keeps whatever the conversation stored.
  expect(socket.lastStart()).not.toHaveProperty('knowledge_bases');
});

test('choosing a base carries its reference on the next question only', () => {
  const { runtime, socket } = harness();
  runtime.setKnowledgeBases(['physics']);
  expect(runtime.getSnapshot()).toMatchObject({
    knowledgeBases: ['physics'],
    knowledgeBasesTouched: true,
  });

  expect(runtime.send('Explain interference')).toBe(true);
  expect(socket.lastStart()).toMatchObject({
    type: 'start_turn',
    knowledge_bases: ['physics'],
  });

  // The choice stays attached to the following question as well.
  finish(socket);
  expect(runtime.send('And diffraction?')).toBe(true);
  expect(socket.lastStart()).toMatchObject({ knowledge_bases: ['physics'] });
});

test('clearing the choice is sent as an empty list so the server forgets it', () => {
  const { runtime, socket } = harness();
  runtime.setKnowledgeBases(['physics']);
  runtime.setKnowledgeBases([]);
  expect(runtime.send('Answer without documents')).toBe(true);
  // An omitted field would silently fall back to the stored base.
  expect(socket.lastStart()).toMatchObject({ knowledge_bases: [] });
});

test('an unchanged selection is not reported as a change', () => {
  const { runtime, socket } = harness();
  runtime.setKnowledgeBases([]);
  runtime.setKnowledgeBases(['  ', '']);
  expect(runtime.getSnapshot().knowledgeBasesTouched).toBe(false);
  runtime.send('Plain question');
  expect(socket.lastStart()).not.toHaveProperty('knowledge_bases');
});

test('toggling keeps the list deduplicated and trimmed', () => {
  const { runtime } = harness();
  runtime.toggleKnowledgeBase('physics');
  runtime.toggleKnowledgeBase('biology');
  expect(runtime.getSnapshot().knowledgeBases).toEqual(['physics', 'biology']);

  runtime.toggleKnowledgeBase('physics');
  expect(runtime.getSnapshot().knowledgeBases).toEqual(['biology']);

  runtime.setKnowledgeBases([' biology ', 'chemistry', 'biology']);
  expect(runtime.getSnapshot().knowledgeBases).toEqual(['biology', 'chemistry']);

  runtime.toggleKnowledgeBase('   ');
  expect(runtime.getSnapshot().knowledgeBases).toEqual(['biology', 'chemistry']);
});

test('opening a saved conversation adopts the bases the server stored', async () => {
  const get = jest.fn(async () =>
    detail({ knowledgeBases: ['user:kb:physics'] }),
  );
  const { runtime, socket } = harness(get);

  // A selection made for the previous conversation must not leak into this one.
  runtime.setKnowledgeBases(['biology']);
  await expect(runtime.openSession('session-1')).resolves.toBe(true);

  expect(runtime.getSnapshot()).toMatchObject({
    knowledgeBases: ['user:kb:physics'],
    knowledgeBasesTouched: false,
  });
  expect(runtime.send('Continue')).toBe(true);
  expect(socket.lastStart()).not.toHaveProperty('knowledge_bases');

  // Changing it for this conversation is still announced.
  runtime.setKnowledgeBases([]);
  finish(socket);
  expect(runtime.send('Without documents')).toBe(true);
  expect(socket.lastStart()).toMatchObject({ knowledge_bases: [] });
});

test('starting over drops the selection with the rest of the conversation', () => {
  const { runtime, sockets } = harness();
  runtime.setKnowledgeBases(['physics']);
  runtime.reset();
  expect(runtime.getSnapshot()).toMatchObject({
    knowledgeBases: [],
    knowledgeBasesTouched: false,
  });
  // Starting over reconnects, so wait for the new transport.
  const fresh = sockets[sockets.length - 1];
  fresh.open();
  expect(runtime.send('Fresh question')).toBe(true);
  expect(fresh.lastStart()).not.toHaveProperty('knowledge_bases');
});
