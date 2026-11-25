import { useRouter } from 'expo-router';
import { useAppSession } from '../src/appSession';
import { SettingsScreen } from '../src/screens/SettingsScreen';

export default function SettingsRoute() {
  const router = useRouter();
  const session = useAppSession();
  if (session.phase !== 'chat' || !session.origin) return null;
  return (
    <SettingsScreen
      origin={session.origin}
      authenticated={
        session.status?.enabled === true && session.status.authenticated
      }
      busy={session.busy}
      error={session.error}
      onChangeServer={session.disconnect}
      onOpenKnowledge={() => router.push('/knowledge')}
      onSignOut={session.logout}
    />
  );
}
