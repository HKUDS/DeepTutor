import { useRef, useState } from 'react';
import type { TextInput } from 'react-native';
import { Action, ErrorNotice, Field } from '../components/FormControls';
import { FormScreen } from '../components/Screen';

export function LoginScreen({
  origin,
  busy = false,
  error,
  onSignIn,
  onChangeServer,
}: {
  origin: string;
  busy?: boolean;
  error?: string | null;
  onSignIn: (username: string, password: string) => void;
  onChangeServer: () => void;
}) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const passwordField = useRef<TextInput>(null);
  const canSignIn = !busy && username.trim().length > 0 && password.length > 0;

  function signIn() {
    if (!canSignIn) return;
    onSignIn(username.trim(), password);
    setPassword('');
  }

  return (
    <FormScreen title="Sign in to DeepTutor" description={origin}>
      <Field
        label="Username"
        value={username}
        onChangeText={setUsername}
        editable={!busy}
        autoCapitalize="none"
        autoCorrect={false}
        autoComplete="username"
        returnKeyType="next"
        submitBehavior="submit"
        onSubmitEditing={() => passwordField.current?.focus()}
      />
      <Field
        ref={passwordField}
        label="Password"
        value={password}
        onChangeText={setPassword}
        editable={!busy}
        autoComplete="current-password"
        secureTextEntry
        returnKeyType="go"
        onSubmitEditing={signIn}
      />
      <ErrorNotice message={error} />
      <Action
        title={busy ? 'Signing in…' : 'Sign in'}
        busy={busy}
        disabled={!canSignIn && !busy}
        onPress={signIn}
      />
      <Action
        title="Change server"
        onPress={onChangeServer}
        tone="secondary"
        disabled={busy}
      />
    </FormScreen>
  );
}
