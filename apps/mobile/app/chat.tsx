import { useRouter } from 'expo-router';
import { useAppSession } from '../src/appSession';
import { useChatRuntimeContext } from '../src/chatSession';
import { ChatScreen } from '../src/screens/ChatScreen';

export default function ChatRoute() {
  const router = useRouter();
  const session = useAppSession();
  const chat = useChatRuntimeContext();
  if (session.phase !== 'chat' || !chat) return null;
  return (
    <ChatScreen
      {...chat}
      onOpenSettings={() => router.push('/settings')}
      onOpenSessions={() => router.push('/sessions')}
    />
  );
}
