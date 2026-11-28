import AsyncStorage from '@react-native-async-storage/async-storage';
import { act, renderHook, waitFor } from '@testing-library/react-native';
import { fetch } from 'expo/fetch';
import { useChatRuntime } from '../src/features/chat/useChatRuntime';
import {
  recoveryStoresFor,
  turnRecoveryStorage,
} from '../src/storage/turnRecovery';

jest.mock('expo/fetch', () => ({ fetch: jest.fn() }));
jest.mock('@react-native-async-storage/async-storage', () =>
  jest.requireActual(
    '@react-native-async-storage/async-storage/jest/async-storage-mock',
  ),
);

const scope = {
  origin: 'https://hook.example.test',
  account: 'account-1',
  workspace: '',
};
const socketFactory = () => ({
  readyState: 0,
  send() {},
  close() {},
  addEventListener() {},
});
const useRuntime = () => useChatRuntime({ ...scope, socketFactory });

beforeEach(async () => {
  jest.clearAllMocks();
  await AsyncStorage.clear();
});

test('the real hook persists a selection and restores it after cold remount', async () => {
  jest.mocked(fetch).mockResolvedValue({
    ok: true,
    status: 200,
    redirected: false,
    json: async () => ({
      id: 'session-1',
      title: 'Saved conversation',
      messages: [{ id: 1, role: 'user', content: 'A saved question' }],
    }),
  } as Awaited<ReturnType<typeof fetch>>);
  const first = renderHook(useRuntime);
  await act(async () => {
    expect(await first.result.current.openSession('session-1')).toBe(true);
  });
  await waitFor(() => expect(AsyncStorage.setItem).toHaveBeenCalled());
  first.unmount();
  const second = renderHook(useRuntime);
  await waitFor(() =>
    expect(second.result.current.sessionTitle).toBe('Saved conversation'),
  );
  expect(second.result.current.messages[0].question).toBe('A saved question');
  expect(fetch).toHaveBeenCalledTimes(2);
  second.unmount();
});

test('a store bound before logout cannot write after origin cleanup', async () => {
  const retiring = recoveryStoresFor(scope.origin).lastSession;
  await retiring.write(scope, 'old-selection');
  const clear = turnRecoveryStorage.clearServer(scope.origin);
  await Promise.all([clear, retiring.write(scope, 'late-selection')]);
  const next = recoveryStoresFor(scope.origin).lastSession;
  expect(await next.read(scope)).toBeNull();
  await next.write(scope, 'new-selection');
  expect(await next.read(scope)).toBe('new-selection');
});
