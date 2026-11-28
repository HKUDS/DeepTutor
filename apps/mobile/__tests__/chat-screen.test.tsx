import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from '@testing-library/react-native';

import { ChatScreen, type ChatScreenProps } from '../src/screens/ChatScreen';

// Each test mounts a full screen; without cleanup the next one would see the
// previous tree twice.
afterEach(cleanup);

/**
 * A container's accessible name is derived from its subtree, so a query by role
 * and name can resolve to the wrong element. Match the explicit label instead.
 */
function button(label: string) {
  const match = screen
    .getAllByRole('button')
    .find(node => node.props.accessibilityLabel === label);
  if (!match) throw new Error(`No button labelled "${label}"`);
  return match;
}

function chat(overrides: Partial<ChatScreenProps> = {}): ChatScreenProps {
  return {
    connection: 'connected',
    status: 'idle',
    sessionId: null,
    sessionTitle: '',
    messages: [],
    history: 'ready',
    waitingPrompt: null,
    canLeaveTurn: false,
    recovery: null,
    error: null,
    send: jest.fn(() => true),
    reply: jest.fn(async () => true),
    cancel: jest.fn(async () => {}),
    retryConnection: jest.fn(),
    retrySession: jest.fn(async () => true),
    reset: jest.fn(),
    dismissRecovery: jest.fn(),
    onOpenSettings: jest.fn(),
    onOpenSessions: jest.fn(),
    ...overrides,
  };
}

test('the header names the open conversation and reaches the list', () => {
  const props = chat({ sessionTitle: 'Fractions', sessionId: 's1' });
  render(<ChatScreen {...props} />);

  expect(screen.getByText('Fractions')).toBeTruthy();
  expect(screen.getByText('Connected · saved on the server')).toBeTruthy();
  fireEvent.press(button('Conversations'));
  expect(props.onOpenSessions).toHaveBeenCalledTimes(1);
});

test('a running turn offers Stop instead of Send', () => {
  render(<ChatScreen {...chat({ status: 'running' })} />);
  expect(screen.getByText('DeepTutor is replying…')).toBeTruthy();
  expect(screen.queryAllByRole('button', { name: 'Send' })).toHaveLength(0);
  expect(button('Stop')).toBeTruthy();
});

test('a waiting turn asks for the reply the server needs', async () => {
  const reply = jest.fn(async () => true);
  render(
    <ChatScreen
      {...chat({
        status: 'waiting_for_input',
        waitingPrompt: 'Which subject?',
        reply,
      })}
    />,
  );
  expect(screen.getByText('Which subject?')).toBeTruthy();
  // The composer's field and its button are both labelled "Reply", so the
  // placeholder is what identifies the input.
  fireEvent.changeText(screen.getByPlaceholderText('Write a reply'), 'Math');
  // Submitting clears the draft after the reply resolves, so the press is
  // awaited rather than fired and forgotten.
  await act(async () => {
    fireEvent.press(button('Reply'));
  });
  expect(reply).toHaveBeenCalledWith('Math');
});

test('a stopped response says so and accepts the next question', () => {
  render(<ChatScreen {...chat({ status: 'cancelled' })} />);
  expect(screen.getByText('This response was stopped.')).toBeTruthy();
  expect(button('Send')).toBeTruthy();
});

test('a recovered run explains itself and can be dismissed', () => {
  const dismissRecovery = jest.fn();
  render(
    <ChatScreen
      {...chat({
        status: 'recovering',
        recovery: {
          kind: 'resumed',
          message: 'Reconnected to a response that was still running.',
        },
        dismissRecovery,
      })}
    />,
  );
  expect(
    screen.getByText('Reconnected to a response that was still running.'),
  ).toBeTruthy();
  fireEvent.press(button('Dismiss'));
  expect(dismissRecovery).toHaveBeenCalledTimes(1);
});

test('a conversation the server lost offers a fresh start', () => {
  const reset = jest.fn();
  render(
    <ChatScreen
      {...chat({
        recovery: {
          kind: 'unavailable',
          message: 'This conversation no longer exists on the server.',
        },
        reset,
      })}
    />,
  );
  fireEvent.press(button('New chat'));
  expect(reset).toHaveBeenCalledTimes(1);
});

test('a failed transcript load can be retried', () => {
  const retrySession = jest.fn(async () => true);
  render(<ChatScreen {...chat({ history: 'failed', retrySession })} />);
  fireEvent.press(button('Try again'));
  expect(retrySession).toHaveBeenCalledTimes(1);
});

test('a transcript that failed to load does not accept a question', () => {
  const send = jest.fn(() => true);
  render(
    <ChatScreen
      {...chat({
        history: 'failed',
        sessionId: 'session-1',
        send,
        error: 'Could not load this conversation.',
      })}
    />,
  );
  fireEvent.changeText(
    screen.getByPlaceholderText('Ask a question'),
    'What about quarters?',
  );
  const submit = button('Send');
  expect(submit.props.accessibilityState?.disabled).toBe(true);
  fireEvent.press(submit);
  expect(send).not.toHaveBeenCalled();
});

test('a failed turn keeps its question and shows the failure', () => {
  render(
    <ChatScreen
      {...chat({
        messages: [
          {
            id: 'm1',
            question: 'Explain entropy',
            answer: '',
            failed: 'The provider timed out.',
            retryable: true,
          },
        ],
      })}
    />,
  );
  expect(screen.getByText('Explain entropy')).toBeTruthy();
  expect(screen.getByText('The provider timed out.')).toBeTruthy();
});
