import { act, renderHook } from '@testing-library/react-native';
import { AppState, type AppStateStatus } from 'react-native';
import { ServerSession } from '../src/features/server/serverSession';
import { useServerSession } from '../src/features/server/useServerSession';

jest.mock('../src/features/server/serverSession', () => ({
  ServerSession: jest.fn(),
}));

test('refreshes authentication periodically in the foreground and stops on background or unmount', () => {
  jest.useFakeTimers();
  const remove = jest.fn();
  let changeState: (next: AppStateStatus) => void = () => {};
  const appState = jest
    .spyOn(AppState, 'addEventListener')
    .mockImplementation((_event, listener) => {
      changeState = listener;
      return { remove };
    });
  const refreshAuth = jest.fn().mockResolvedValue(true);
  const snapshot = { phase: 'chat', origin: 'https://tutor.example.test' };
  jest.mocked(ServerSession).mockImplementation(
    () =>
      ({
        subscribe: () => () => {},
        getSnapshot: () => snapshot,
        restore: jest.fn(),
        abortPending: jest.fn(),
        refreshAuth,
      } as unknown as ServerSession),
  );
  try {
    const { unmount } = renderHook(useServerSession);
    act(() => changeState('active'));
    refreshAuth.mockClear();
    act(() => jest.advanceTimersByTime(60_000));
    expect(refreshAuth).toHaveBeenCalledTimes(1);
    act(() => changeState('background'));
    act(() => jest.advanceTimersByTime(120_000));
    expect(refreshAuth).toHaveBeenCalledTimes(1);
    act(() => changeState('active'));
    expect(refreshAuth).toHaveBeenCalledTimes(2);
    unmount();
    act(() => jest.advanceTimersByTime(120_000));
    expect(refreshAuth).toHaveBeenCalledTimes(2);
    expect(remove).toHaveBeenCalledTimes(1);
  } finally {
    appState.mockRestore();
    jest.useRealTimers();
  }
});
