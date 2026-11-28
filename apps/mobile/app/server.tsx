import { useAppSession } from '../src/appSession';
import { devSuggestedServerAddress } from '../src/features/server/serverAddress';
import { ServerScreen } from '../src/screens/ServerScreen';

export default function ServerRoute() {
  const session = useAppSession();
  return (
    <ServerScreen
      initialAddress={session.origin ?? devSuggestedServerAddress()}
      busy={session.busy}
      error={session.error}
      onConnect={session.connect}
    />
  );
}
