import { useRouter } from 'expo-router';
import { useAppSession } from '../src/appSession';
import { useChatRuntimeContext } from '../src/chatSession';
import {
  knowledgeScope,
  useKnowledgeApi,
} from '../src/features/knowledge/useKnowledgeApi';
import { useKnowledgeBases } from '../src/features/knowledge/useKnowledgeBases';
import { useRefreshOnFocus } from '../src/features/knowledge/useRefreshOnFocus';
import { ChatScreen } from '../src/screens/ChatScreen';

export default function ChatRoute() {
  const router = useRouter();
  const session = useAppSession();
  const chat = useChatRuntimeContext();
  const api = useKnowledgeApi(session);
  // The picker reads the server's catalogue; the conversation's own selection
  // lives in the runtime so a turn can carry it.
  const knowledge = useKnowledgeBases(api, knowledgeScope(session));
  // Returning from Settings or the knowledge screens may have changed which
  // bases exist, so the picker's catalogue is re-read when this screen is back.
  useRefreshOnFocus(knowledge.refresh);

  if (session.phase !== 'chat' || !chat) return null;

  return (
    <ChatScreen
      {...chat}
      knowledgeOptions={knowledge.bases}
      knowledgeStatus={knowledge.status}
      knowledgeError={knowledge.error}
      onToggleKnowledge={chat.toggleKnowledgeBase}
      onRefreshKnowledge={() => {
        knowledge.refresh().catch(() => {});
      }}
      onManageKnowledge={() => router.push('/knowledge')}
      onOpenSettings={() => router.push('/settings')}
      onOpenSessions={() => router.push('/sessions')}
    />
  );
}
