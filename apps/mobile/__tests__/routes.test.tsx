import { fireEvent, waitFor } from '@testing-library/react-native';
import { renderRouter, screen, testRouter } from 'expo-router/testing-library';
import { useEffect, useState } from 'react';
import { parse } from 'query-string';
import RootLayout from '../app/_layout';
import { redirectSystemPath } from '../app/+native-intent';
import ChatRoute from '../app/chat';
import IndexRoute from '../app/index';
import LoginRoute from '../app/login';
import ServerRoute from '../app/server';
import SettingsRoute from '../app/settings';
import { useChatRuntime } from '../src/features/chat/useChatRuntime';
import { useServerSession } from '../src/features/server/useServerSession';

jest.mock('../src/features/server/useServerSession', () => ({
  useServerSession: jest.fn(),
}));
jest.mock('../src/features/chat/useChatRuntime', () => ({
  useChatRuntime: jest.fn(),
}));

const routes = {
  _layout: RootLayout,
  index: IndexRoute,
  server: ServerRoute,
  login: LoginRoute,
  chat: ChatRoute,
  settings: SettingsRoute,
};

const origin = 'https://tutor.example.test';
const mockServer = jest.mocked(useServerSession);
const mockChat = jest.mocked(useChatRuntime);
const send = jest.fn((_text: string) => true);

test('native intents allow known routes and reject input the app does not use', () => {
  expect(redirectSystemPath({ path: 'deeptutor-mobile://chat' })).toBe('/chat');
  expect(redirectSystemPath({ path: 'deeptutor-mobile:///settings' })).toBe(
    '/settings',
  );
  expect(redirectSystemPath({ path: '/chat?extra=x' })).toBe('/');
  expect(redirectSystemPath({ path: 'https://elsewhere.example/chat' })).toBe(
    '/',
  );
  expect(redirectSystemPath({ path: '/unknown' })).toBe('/');
  expect(redirectSystemPath({ path: '/'.repeat(300) })).toBe('/');
  expect(redirectSystemPath({ path: '/chat?x=%E0%A4' })).toBe('/');
});

test('query-string still decodes valid and malformed parameters with the SDK-compatible patch', () => {
  expect(parse('word=hello%20world&word=ok&odd=%E0%A4')).toMatchObject({
    word: ['hello world', 'ok'],
    odd: expect.any(String),
  });
});

function mockSession(initial: 'connect' | 'login' | 'chat') {
  mockServer.mockImplementation(function useMockSession() {
    const [phase, setPhase] = useState(initial);
    return {
      phase,
      network: phase === 'connect' ? 'unknown' : 'online',
      origin: phase === 'connect' ? null : origin,
      busy: false,
      error: null,
      status: { enabled: true, authenticated: phase === 'chat' },
      connect: async () => setPhase('login'),
      login: async () => setPhase('chat'),
      logout: async () => setPhase('login'),
      disconnect: async () => setPhase('connect'),
      refreshAuth: async () => phase === 'chat',
      invalidateAuth: () => setPhase('login'),
    };
  });
}

beforeEach(() => {
  send.mockClear();
  mockChat.mockClear();
  mockChat.mockReturnValue({
    connection: 'connected',
    messages: [],
    phase: 'ready',
    waitingPrompt: null,
    canLeaveTurn: false,
    error: null,
    send,
    reply: async () => true,
    cancel: async () => {},
    retryConnection: () => {},
    reset: () => {},
  });
});

test('a warm chat link reuses the existing runtime with Settings open', async () => {
  mockSession('chat');
  const initialChat = mockChat({ origin });
  const mount = jest.fn();
  mockChat.mockImplementation(function useMountedChat() {
    useEffect(mount, []);
    return initialChat;
  });
  const { getPathname } = renderRouter(routes);
  await waitFor(() => expect(getPathname()).toBe('/chat'));
  fireEvent.press(screen.getByRole('button', { name: 'Settings' }));
  await waitFor(() => expect(getPathname()).toBe('/settings'));
  testRouter.navigate(redirectSystemPath({ path: 'deeptutor-mobile://chat' }));
  await waitFor(() => expect(getPathname()).toBe('/chat'));
  expect(mount).toHaveBeenCalledTimes(1);
});

test('a protected deep link routes to server setup while disconnected', async () => {
  mockSession('connect');
  const { getPathname } = renderRouter(routes, { initialUrl: '/chat' });
  await waitFor(() => expect(getPathname()).toBe('/server'));
  expect(mockChat).not.toHaveBeenCalled();
});

test('connecting opens login, and signing out removes protected history', async () => {
  mockSession('connect');
  const { getPathname } = renderRouter(routes);
  await waitFor(() => expect(getPathname()).toBe('/server'));
  fireEvent.changeText(screen.getByLabelText('Server address'), origin);
  fireEvent.press(screen.getByRole('button', { name: 'Connect' }));
  await waitFor(() => expect(getPathname()).toBe('/login'));
  fireEvent.changeText(screen.getByLabelText('Username'), 'learner');
  fireEvent.changeText(screen.getByLabelText('Password'), 'a-test-password');
  fireEvent.press(screen.getByRole('button', { name: 'Sign in' }));
  await waitFor(() => expect(getPathname()).toBe('/chat'));
  fireEvent.press(screen.getByRole('button', { name: 'Settings' }));
  await waitFor(() => expect(getPathname()).toBe('/settings'));
  expect(testRouter.canGoBack()).toBe(true);
  fireEvent.press(screen.getByRole('button', { name: 'Sign out' }));
  await waitFor(() => expect(getPathname()).toBe('/login'));
  expect(testRouter.canGoBack()).toBe(false);
});
