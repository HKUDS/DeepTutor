import { useAppSession } from '../src/appSession';
import { LoginScreen } from '../src/screens/LoginScreen';

export default function LoginRoute() {
  const session = useAppSession();
  if (session.phase !== 'login' || !session.origin) return null;
  return (
    <LoginScreen
      origin={session.origin}
      busy={session.busy}
      error={session.error}
      onSignIn={session.login}
      onChangeServer={session.disconnect}
    />
  );
}
