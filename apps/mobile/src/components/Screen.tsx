import type { ReactNode } from 'react';
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { spacing, textSize, useTheme } from '../theme/useTheme';

export function Screen({
  children,
  topInset = true,
}: {
  children: ReactNode;
  topInset?: boolean;
}) {
  const theme = useTheme();

  return (
    <SafeAreaView
      style={[styles.fill, { backgroundColor: theme.background }]}
      edges={topInset ? undefined : ['left', 'right', 'bottom']}
    >
      <KeyboardAvoidingView
        style={styles.fill}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        {children}
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

export function FormScreen({
  title,
  description,
  children,
  topInset,
}: {
  title?: string;
  description?: string;
  children: ReactNode;
  topInset?: boolean;
}) {
  const theme = useTheme();

  return (
    <Screen topInset={topInset}>
      <ScrollView
        keyboardShouldPersistTaps="handled"
        contentContainerStyle={styles.formScroll}
      >
        <View style={styles.form}>
          {title ? (
            <Text
              accessibilityRole="header"
              style={[styles.title, { color: theme.text }]}
            >
              {title}
            </Text>
          ) : null}
          {description ? (
            <Text style={[styles.description, { color: theme.muted }]}>
              {description}
            </Text>
          ) : null}
          {children}
        </View>
      </ScrollView>
    </Screen>
  );
}

export function LoadingScreen({ label }: { label: string }) {
  const theme = useTheme();

  return (
    <Screen>
      <View style={styles.loading} accessibilityLiveRegion="polite">
        <ActivityIndicator color={theme.primary} />
        <Text style={[styles.description, { color: theme.muted }]}>
          {label}
        </Text>
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  formScroll: { flexGrow: 1, padding: spacing.xl },
  form: { width: '100%', maxWidth: 520, alignSelf: 'center', gap: spacing.lg },
  title: { fontSize: textSize.title, fontWeight: '700' },
  description: { fontSize: textSize.body, lineHeight: 23 },
  loading: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.md,
  },
});
