import { useEffect, useMemo, useRef, useSyncExternalStore } from 'react';
import { AppState } from 'react-native';

import { MobileChatRuntime, type ChatOptions } from './MobileChatRuntime';
import { ApiClient } from '../../services/apiClient';
import { SessionApi } from '../../services/sessionApi';
import { recoveryStoresFor } from '../../storage/turnRecovery';

export type UseChatRuntimeOptions = ChatOptions & {
  /** Stable account identity; without it nothing is persisted. */
  account: string;
  /** "" is the built-in general workspace, matching the socket's scope. */
  workspace?: string;
};

export function useChatRuntime(options: UseChatRuntimeOptions) {
  const {
    origin,
    socketFactory,
    onAuthExpired,
    refreshAuth,
    account,
    workspace = '',
  } = options;
  const callbacks = useRef({ onAuthExpired, refreshAuth });
  useEffect(() => {
    callbacks.current = { onAuthExpired, refreshAuth };
  }, [onAuthExpired, refreshAuth]);

  const sessionApi = useMemo(
    () => new SessionApi(new ApiClient(origin)),
    [origin],
  );

  const runtime = useMemo(
    () =>
      new MobileChatRuntime({
        origin,
        socketFactory,
        sessionApi,
        ...recoveryStoresFor(origin),
        // Signing out drops the scope, which both stops persistence and keeps
        // one account's run from ever being resumed under another.
        scope: account ? { origin, account, workspace } : null,
        onAuthExpired: () => callbacks.current.onAuthExpired?.(),
        refreshAuth: () =>
          callbacks.current.refreshAuth?.() ?? Promise.resolve(true),
      }),
    [origin, socketFactory, sessionApi, account, workspace],
  );

  useEffect(() => {
    const appState = AppState.addEventListener('change', next => {
      if (next === 'active' || next === 'background') {
        runtime.setVisible(next === 'active');
      }
    });
    runtime.start(AppState.currentState !== 'background');
    return () => {
      appState.remove();
      runtime.stop();
    };
  }, [runtime]);

  const state = useSyncExternalStore(runtime.subscribe, runtime.getSnapshot);
  const { cancel, reply, reset, retryConnection, openSession, retrySession } =
    runtime;

  return {
    ...state,
    /** Read the live snapshot after an await instead of a stale render. */
    getSnapshot: runtime.getSnapshot,
    send: runtime.send,
    cancel,
    reply,
    reset,
    retryConnection,
    openSession,
    retrySession,
    dismissRecovery: runtime.dismissRecovery,
  };
}
