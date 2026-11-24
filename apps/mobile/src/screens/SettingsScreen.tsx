import { StyleSheet, Text, View } from 'react-native';
import { Action, ErrorNotice } from '../components/FormControls';
import { FormScreen } from '../components/Screen';
import { radius, spacing, textSize, useTheme } from '../theme/useTheme';

export function SettingsScreen({
  origin,
  authenticated,
  busy = false,
  error,
  onChangeServer,
  onSignOut,
}: {
  origin: string;
  authenticated: boolean;
  busy?: boolean;
  error?: string | null;
  onChangeServer: () => void;
  onSignOut: () => void;
}) {
  const theme = useTheme();

  return (
    <FormScreen topInset={false}>
      <View
        style={[
          styles.connection,
          { backgroundColor: theme.surface, borderColor: theme.border },
        ]}
      >
        <Text style={[styles.label, { color: theme.muted }]}>
          Current server
        </Text>
        <Text selectable style={[styles.address, { color: theme.text }]}>
          {origin}
        </Text>
      </View>
      <ErrorNotice message={error} />
      <Action
        title="Change server"
        onPress={onChangeServer}
        tone="secondary"
        disabled={busy}
      />
      {authenticated ? (
        <Action
          title={busy ? 'Signing out…' : 'Sign out'}
          onPress={onSignOut}
          busy={busy}
        />
      ) : null}
    </FormScreen>
  );
}

const styles = StyleSheet.create({
  connection: {
    borderWidth: 1,
    borderRadius: radius.md,
    padding: spacing.lg,
    gap: spacing.xs,
  },
  label: { fontSize: textSize.small },
  address: { fontSize: textSize.body, fontWeight: '600' },
});
