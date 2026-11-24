import { useCallback, useMemo, useState } from 'react';
import { useRouter } from 'expo-router';
import { useAppSession } from '../src/appSession';
import { useChatRuntimeContext } from '../src/chatSession';
import { useSessionList } from '../src/features/sessions/useSessionList';
import { SessionsScreen } from '../src/screens/SessionsScreen';
import { ApiClient } from '../src/services/apiClient';
import { SessionApi } from '../src/services/sessionApi';

export default function SessionsRoute() {
  const router = useRouter();
  const session = useAppSession();
  const chat = useChatRuntimeContext();

  const api = useMemo(
    () => (session.origin ? new SessionApi(new ApiClient(session.origin)) : null),
    [session.origin],
  );
  const list = useSessionList(api, undefined);
  const [busySessionId, setBusySessionId] = useState<string | null>(null);
  const [openError, setOpenError] = useState<string | null>(null);

  const open = useCallback(
    async (sessionId: string) => {
      if (!chat || busySessionId) return;
      setOpenError(null);
      setBusySessionId(sessionId);
      try {
        await chat.openSession(sessionId);
        // A blocked switch leaves the previous conversation in place; a load
        // failure still moves to the chat screen so its retry is reachable.
        if (chat.getSnapshot().sessionId === sessionId) {
          router.replace('/chat');
        } else {
          setOpenError(
            chat.getSnapshot().error ??
              'Could not open this conversation on the server.',
          );
        }
      } finally {
        setBusySessionId(null);
      }
    },
    [busySessionId, chat, router],
  );

  const newChat = useCallback(() => {
    chat?.reset();
    router.replace('/chat');
  }, [chat, router]);

  if (session.phase !== 'chat' || !chat) return null;

  return (
    <SessionsScreen
      sessions={list.sessions}
      status={list.status}
      refreshing={list.refreshing}
      loadingMore={list.loadingMore}
      hasMore={list.hasMore}
      error={openError ?? list.error}
      currentSessionId={chat.sessionId}
      busySessionId={busySessionId}
      onOpen={open}
      onNewChat={newChat}
      onRefresh={list.refresh}
      onLoadMore={list.loadMore}
      onRetry={list.retry}
      onRename={list.rename}
      onDelete={list.remove}
    />
  );
}
