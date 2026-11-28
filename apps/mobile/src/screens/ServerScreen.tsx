import { useState } from 'react';
import { Action, ErrorNotice, Field } from '../components/FormControls';
import { FormScreen } from '../components/Screen';

export function ServerScreen({
  initialAddress = '',
  busy = false,
  error,
  onConnect,
}: {
  initialAddress?: string;
  busy?: boolean;
  error?: string | null;
  onConnect: (address: string) => void;
}) {
  const [address, setAddress] = useState(initialAddress);
  const canConnect = !busy && address.trim().length > 0;

  function connect() {
    if (canConnect) onConnect(address.trim());
  }

  return (
    <FormScreen
      title="Connect to DeepTutor"
      description="Enter the address of your DeepTutor server. If someone set it up for you, ask them for the link."
    >
      <Field
        label="Server address"
        value={address}
        onChangeText={setAddress}
        editable={!busy}
        autoCapitalize="none"
        autoCorrect={false}
        keyboardType="url"
        returnKeyType="go"
        onSubmitEditing={connect}
        placeholder="https://tutor.example.com"
      />
      <ErrorNotice message={error} />
      <Action
        title={busy ? 'Connecting…' : 'Connect'}
        busy={busy}
        disabled={!canConnect && !busy}
        onPress={connect}
      />
    </FormScreen>
  );
}
