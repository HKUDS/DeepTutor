import { useEffect, useMemo, useSyncExternalStore } from 'react';
import { AppState } from 'react-native';
import { ServerSession } from './serverSession';

export function useServerSession() {
  const session = useMemo(() => new ServerSession(), []);
  const state = useSyncExternalStore(session.subscribe, session.getSnapshot);

  useEffect(() => {
    session.restore();
    const listener = AppState.addEventListener('change', next => {
      if (next === 'active') session.refreshAuth();
    });
    return () => {
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
