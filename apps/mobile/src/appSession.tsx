import { createContext, useContext, type PropsWithChildren } from 'react';
import { useServerSession } from './features/server/useServerSession';

type AppSession = ReturnType<typeof useServerSession>;

const SessionContext = createContext<AppSession | null>(null);

export function AppSessionProvider({ children }: PropsWithChildren) {
  const session = useServerSession();
  return (
    <SessionContext.Provider value={session}>
      {children}
    </SessionContext.Provider>
  );
}

export function useAppSession() {
  const session = useContext(SessionContext);
  if (!session) {
    throw new Error('AppSessionProvider is required');
  }
  return session;
}
