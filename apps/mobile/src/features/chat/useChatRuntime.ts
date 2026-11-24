import { useEffect, useMemo, useRef, useSyncExternalStore } from 'react';
import { AppState } from 'react-native';

import { MobileChatRuntime, type ChatOptions } from './MobileChatRuntime';

export function useChatRuntime(options: ChatOptions) {
  const { origin, socketFactory, onAuthExpired, refreshAuth } = options;
  const callbacks = useRef({ onAuthExpired, refreshAuth });
  useEffect(() => {
    callbacks.current = { onAuthExpired, refreshAuth };
  }, [onAuthExpired, refreshAuth]);

  const runtime = useMemo(
    () =>
      new MobileChatRuntime({
        origin,
        socketFactory,
        onAuthExpired: () => callbacks.current.onAuthExpired?.(),
        refreshAuth: () =>
          callbacks.current.refreshAuth?.() ?? Promise.resolve(true),
      }),
    [origin, socketFactory],
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
  return {
    ...state,
    send: runtime.send,
    cancel: runtime.cancel,
    reply: runtime.reply,
    reset: runtime.reset,
    retryConnection: runtime.retryConnection,
  };
}
