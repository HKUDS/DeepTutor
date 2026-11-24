import { useEffect, useMemo, useSyncExternalStore } from 'react';
import { AppState } from 'react-native';
import { ServerSession } from './serverSession';

const AUTH_REFRESH_MS = 60_000;

export function useServerSession() {
  const session = useMemo(() => new ServerSession(), []);
  const state = useSyncExternalStore(session.subscribe, session.getSnapshot);

  useEffect(() => {
    session.restore();
    let timer: ReturnType<typeof setInterval> | undefined;
    const scheduleRefresh = (active: boolean) => {
      clearInterval(timer);
      if (active) {
        session.refreshAuth();
        timer = setInterval(() => session.refreshAuth(), AUTH_REFRESH_MS);
      }
    };
    const listener = AppState.addEventListener('change', next => {
      scheduleRefresh(next === 'active');
    });
    scheduleRefresh(AppState.currentState !== 'background');
    return () => {
      clearInterval(timer);
      listener.remove();
      session.abortPending();
    };
  }, [session]);

  return {
    ...state,
    connect: session.connect,
    login: session.login,
    logout: session.logout,
    disconnect: session.disconnect,
    refreshAuth: session.refreshAuth,
    invalidateAuth: session.invalidateAuth,
  };
}
