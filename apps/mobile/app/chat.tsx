import { useRouter } from 'expo-router';
import { useAppSession } from '../src/appSession';
import { useChatRuntime } from '../src/features/chat/useChatRuntime';
import { ChatScreen } from '../src/screens/ChatScreen';

function ConnectedChat({ origin }: { origin: string }) {
  const router = useRouter();
  const { refreshAuth, invalidateAuth } = useAppSession();
  const chat = useChatRuntime({
    origin,
    refreshAuth,
    onAuthExpired: invalidateAuth,
  });
  return (
    <ChatScreen {...chat} onOpenSettings={() => router.push('/settings')} />
  );
}

export default function ChatRoute() {
  const session = useAppSession();
  if (session.phase !== 'chat' || !session.origin) return null;
  return <ConnectedChat key={session.origin} origin={session.origin} />;
}
