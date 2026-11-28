import { resolveTurn, toExchanges } from '../src/features/sessions/history';
import type {
  SessionDetail,
  SessionMessage,
} from '../src/services/sessionApi';

function message(
  id: number | string,
  role: SessionMessage['role'],
  content: string,
  failedTurn?: { turn_id: string; error: string; retryable: boolean },
): SessionMessage {
  return {
    id: String(id),
    role,
    content,
    createdAt: typeof id === 'number' ? id : 0,
    failedTurn: failedTurn
      ? {
          turnId: failedTurn.turn_id,
          error: failedTurn.error,
          retryable: failedTurn.retryable,
        }
      : null,
  };
}

function detail(overrides: Partial<SessionDetail> = {}): SessionDetail {
  return {
    id: 'session-1',
    title: 'Fractions',
    createdAt: 1,
    updatedAt: 2,
    messageCount: 0,
    lastMessage: '',
    status: 'idle',
    activeTurnId: '',
    messages: [],
    activeTurns: [],
    knowledgeBases: [],
    ...overrides,
  };
}

test('pairs each question with the reply that followed it', () => {
  expect(
    toExchanges([
      message(1, 'user', 'What is a half?'),
      message(2, 'assistant', 'One of two equal parts.'),
      message(3, 'user', 'And a third?'),
      message(4, 'assistant', 'One of three equal parts.'),
    ]),
  ).toEqual([
    {
      id: 'm1',
      question: 'What is a half?',
      answer: 'One of two equal parts.',
      failed: null,
      retryable: false,
    },
    {
      id: 'm3',
      question: 'And a third?',
      answer: 'One of three equal parts.',
      failed: null,
      retryable: false,
    },
  ]);
});

test('skips system rows and keeps an unanswered question addressable', () => {
  const exchanges = toExchanges([
    message(1, 'system', 'You are a tutor.'),
    message(2, 'user', 'Still thinking?'),
  ]);
  expect(exchanges).toHaveLength(1);
  expect(exchanges[0]).toMatchObject({ id: 'm2', answer: '', failed: null });
});

test('surfaces a failed turn that saved the question but never replied', () => {
  const [exchange] = toExchanges([
    message(1, 'user', 'Explain entropy', {
      turn_id: 'turn-9',
      error: 'The provider timed out.',
      retryable: true,
    }),
  ]);
  expect(exchange).toMatchObject({
    failed: 'The provider timed out.',
    retryable: true,
  });
});

test('a second assistant row becomes its own entry instead of overwriting', () => {
  const exchanges = toExchanges([
    message(1, 'user', 'Question'),
    message(2, 'assistant', 'First'),
    message(3, 'assistant', 'Second'),
  ]);
  expect(exchanges.map(item => item.answer)).toEqual(['First', 'Second']);
  expect(exchanges[1].question).toBe('');
});

test('a settled conversation reports the status its last turn reached', () => {
  expect(resolveTurn(detail({ status: 'failed' }), 'turn-1')).toEqual({
    kind: 'settled',
    status: 'failed',
  });
});

test('a turn still in the active set is resumable', () => {
  const live = {
    id: 'turn-2',
    status: 'running' as const,
    lastSeq: 7,
    error: '',
    updatedAt: 5,
    retryable: false,
  };
  expect(resolveTurn(detail({ activeTurns: [live] }), 'turn-2')).toEqual({
    kind: 'live',
    turn: live,
  });
  // A newer run on the same session is followed even when the stored id is old.
  expect(resolveTurn(detail({ activeTurns: [live] }), 'turn-1')).toEqual({
    kind: 'live',
    turn: live,
  });
});

test('an unknown conversation has nothing to resume', () => {
  expect(resolveTurn(null, 'turn-1')).toEqual({ kind: 'missing' });
});

test('a transcript without ids still gets one key per exchange', () => {
  const exchanges = toExchanges([
    message('', 'user', 'What is a third?'),
    message('', 'assistant', 'One of three equal parts.'),
    message('', 'user', 'And a quarter?'),
  ]);
  expect(exchanges.map(exchange => exchange.id)).toEqual(['m#0', 'm#2']);
});
