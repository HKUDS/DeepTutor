import { Redirect } from 'expo-router';
import { useAppSession } from '../src/appSession';
import { LoadingScreen } from '../src/components/Screen';

export default function IndexRoute() {
  const { phase } = useAppSession();
  switch (phase) {
    case 'connect':
      return <Redirect href="/server" />;
    case 'login':
      return <Redirect href="/login" />;
    case 'chat':
      return <Redirect href="/chat" />;
    case 'loading':
      return <LoadingScreen label="Checking your connection…" />;
  }
}
