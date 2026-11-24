import {
  createContext,
  useContext,
  type PropsWithChildren,
  type ReactNode,
} from 'react';
import { useAppSession } from './appSession';
import { useChatRuntime, type UseChatRuntimeOptions } from './features/chat/useChatRuntime';

type ChatRuntime = ReturnType<typeof useChatRuntime>;

const ChatRuntimeContext = createContext<ChatRuntime | null>(null);

function ActiveRuntime({
  origin,
  account,
  refreshAuth,
  invalidateAuth,
  children,
}: {
  origin: string;
  account: string;
  refreshAuth: UseChatRuntimeOptions['refreshAuth'];
  invalidateAuth: () => void;
  children: ReactNode;
}) {
  const runtime = useChatRuntime({
    origin,
    account,
    refreshAuth,
    onAuthExpired: invalidateAuth,
  });
  return (
    <ChatRuntimeContext.Provider value={runtime}>
      {children}
    </ChatRuntimeContext.Provider>
  );
}

/**
 * One chat runtime for the whole signed-in area.
 *
 * The transport must outlive the chat screen: opening the conversation list or
 * the settings screen mid-response would otherwise close the socket and lose
 * the turn's subscription.
 */
export function ChatRuntimeProvider({ children }: PropsWithChildren) {
  const session = useAppSession();
  if (session.phase !== 'chat' || !session.origin) {
    return (
      <ChatRuntimeContext.Provider value={null}>
        {children}
      </ChatRuntimeContext.Provider>
    );
  }
  return (
    <ActiveRuntime
      key={session.origin}
      origin={session.origin}
      account={session.status?.accountId ?? ''}
      refreshAuth={session.refreshAuth}
      invalidateAuth={session.invalidateAuth}
    >
      {children}
    </ActiveRuntime>
  );
}

export function useChatRuntimeContext(): ChatRuntime | null {
  return useContext(ChatRuntimeContext);
}

/** For screens that only exist inside the signed-in area. */
export function useChatRuntimeStrict(): ChatRuntime {
  const runtime = useContext(ChatRuntimeContext);
  if (!runtime) throw new Error('ChatRuntimeProvider is not active');
  return runtime;
}
