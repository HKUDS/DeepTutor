import { StyleSheet, Text, View } from 'react-native';

import {
  isActiveState,
  stateLabel,
  type DocumentState,
  type FileState,
} from '../../features/knowledge/refs';
import { radius, spacing, textSize, useTheme } from '../../theme/useTheme';

/** A small pill naming a knowledge base's or a document's processing state. */
export function StateBadge({
  state,
}: {
  state: DocumentState | FileState;
}) {
  const theme = useTheme();
  const active = isActiveState(state);
  const color =
    state === 'ready'
      ? theme.primary
      : state === 'failed'
        ? theme.error
        : active
          ? theme.text
          : theme.muted;
  const background =
    state === 'failed'
      ? theme.errorSurface
      : active
        ? theme.secondary
        : theme.surface;

  return (
    <View
      style={[styles.badge, { backgroundColor: background, borderColor: theme.border }]}
    >
      <Text style={[styles.label, { color }]}>{stateLabel(state)}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  badge: {
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    alignSelf: 'flex-start',
  },
  label: { fontSize: textSize.small, fontWeight: '600' },
});
