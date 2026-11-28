import { forwardRef } from 'react';
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  type TextInputProps,
  View,
} from 'react-native';
import { radius, spacing, textSize, useTheme } from '../theme/useTheme';

type FieldProps = TextInputProps & { label: string; hideLabel?: boolean };

export const Field = forwardRef<TextInput, FieldProps>(function LabeledField(
  { label, hideLabel, style, ...props },
  ref,
) {
  const theme = useTheme();

  return (
    <View style={[styles.field, style]}>
      {hideLabel ? null : (
        <Text style={[styles.label, { color: theme.text }]}>{label}</Text>
      )}
      <TextInput
        {...props}
        ref={ref}
        accessibilityLabel={label}
        placeholderTextColor={theme.muted}
        selectionColor={theme.primary}
        keyboardAppearance={theme.dark ? 'dark' : 'light'}
        style={[
          styles.input,
          {
            color: theme.text,
            backgroundColor: theme.surface,
            borderColor: theme.inputBorder,
          },
          props.multiline && styles.multiline,
        ]}
      />
    </View>
  );
});

export function Action({
  title,
  onPress,
  disabled = false,
  busy = false,
  tone = 'primary',
}: {
  title: string;
  onPress: () => void;
  disabled?: boolean;
  busy?: boolean;
  tone?: 'primary' | 'secondary';
}) {
  const theme = useTheme();
  const primary = tone === 'primary';
  const color = primary ? theme.onPrimary : theme.text;

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={title}
      accessibilityState={{ disabled: disabled || busy, busy }}
      disabled={disabled || busy}
      onPress={onPress}
      style={({ pressed }) => [
        styles.action,
        {
          backgroundColor: primary ? theme.primary : theme.secondary,
          opacity: disabled ? 0.5 : pressed ? 0.78 : 1,
        },
      ]}
    >
      {busy ? <ActivityIndicator size="small" color={color} /> : null}
      <Text style={[styles.actionLabel, { color }]}>{title}</Text>
    </Pressable>
  );
}

export function ErrorNotice({ message }: { message?: string | null }) {
  const theme = useTheme();
  if (!message) return null;

  return (
    <Text
      accessibilityRole="alert"
      accessibilityLiveRegion="polite"
      style={[
        styles.notice,
        { color: theme.error, backgroundColor: theme.errorSurface },
      ]}
    >
      {message}
    </Text>
  );
}

const styles = StyleSheet.create({
  field: { gap: spacing.sm },
  label: { fontSize: textSize.small, fontWeight: '600' },
  input: {
    minHeight: 48,
    borderWidth: 1,
    borderRadius: radius.md,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.lg,
    fontSize: textSize.body,
  },
  multiline: { maxHeight: 140, textAlignVertical: 'center' },
  action: {
    minHeight: 48,
    borderRadius: radius.md,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.sm,
  },
  actionLabel: {
    flexShrink: 1,
    textAlign: 'center',
    fontSize: textSize.body,
    fontWeight: '600',
  },
  notice: {
    padding: spacing.md,
    borderRadius: radius.sm,
    fontSize: textSize.small,
    lineHeight: 20,
  },
});
