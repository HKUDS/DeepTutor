import {
  ActivityIndicator,
  FlatList,
  Modal,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import { Action, ErrorNotice } from '../../components/FormControls';
import { documentState, stateLabel } from '../../features/knowledge/refs';
import type { KnowledgeBaseSummary } from '../../services/knowledgeApi';
import { radius, spacing, textSize, useTheme } from '../../theme/useTheme';

export type KnowledgePickerProps = {
  visible: boolean;
  bases: readonly KnowledgeBaseSummary[];
  /** Refs the next turn will carry. */
  selected: readonly string[];
  status: 'loading' | 'ready' | 'failed';
  error: string | null;
  onToggle: (ref: string) => void;
  onClose: () => void;
  onRefresh: () => void;
  onManage: () => void;
};

function reasonFor(base: KnowledgeBaseSummary): string | null {
  if (base.available === false) return 'This base is no longer available to you.';
  const state = documentState(base);
  if (state === 'ready') return null;
  return `Not ready — ${stateLabel(state).toLowerCase()}.`;
}

/** A server handle is not something to show a learner. */
export function displayRef(ref: string): string {
  const parts = ref.split(':').filter(Boolean);
  return parts.length ? parts[parts.length - 1] : ref;
}

type Row = {
  ref: string;
  name: string;
  /** Absent when the conversation remembers a base the server no longer lists. */
  base: KnowledgeBaseSummary | null;
};

/**
 * Which knowledge bases the next question may cite.
 *
 * Only bases whose index is ready can be picked: attaching one that is still
 * parsing would look like it was used while the answer silently had no
 * documents to draw on.
 */
export function KnowledgePicker({
  visible,
  bases,
  selected,
  status,
  error,
  onToggle,
  onClose,
  onRefresh,
  onManage,
}: KnowledgePickerProps) {
  const theme = useTheme();
  const chosen = new Set(selected);
  // A conversation can remember a base that has since been deleted or lost. It
  // stays on the list, selectable, so the stale choice can be removed here
  // instead of being sent with every question.
  const rows: Row[] = [
    ...bases.map(base => ({ ref: base.ref, name: base.name, base })),
    ...selected
      .filter(ref => !bases.some(base => base.ref === ref))
      .map(ref => ({ ref, name: displayRef(ref), base: null })),
  ];

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <View
          style={[
            styles.sheet,
            { backgroundColor: theme.surface, borderColor: theme.border },
          ]}
        >
          <Text
            accessibilityRole="header"
            style={[styles.title, { color: theme.text }]}
          >
            Knowledge bases
          </Text>
          <Text style={[styles.hint, { color: theme.muted }]}>
            The next question is answered with these documents.
          </Text>

          {error ? <ErrorNotice message={error} /> : null}

          {status === 'loading' ? (
            <View style={styles.center} accessibilityLiveRegion="polite">
              <ActivityIndicator color={theme.primary} />
              <Text style={[styles.hint, { color: theme.muted }]}>
                Loading knowledge bases…
              </Text>
            </View>
          ) : (
            <FlatList
              data={rows}
              keyExtractor={row => row.ref}
              style={styles.list}
              contentContainerStyle={styles.listContent}
              ListEmptyComponent={
                <Text style={[styles.hint, { color: theme.muted }]}>
                  {status === 'failed'
                    ? 'Could not load your knowledge bases.'
                    : 'No knowledge bases yet. Create one to answer from your own documents.'}
                </Text>
              }
              renderItem={({ item }) => {
                const reason = item.base ? reasonFor(item.base) : null;
                const disabled = item.base ? reason !== null : false;
                const checked = chosen.has(item.ref);
                const boxBackground = checked ? theme.primary : 'transparent';
                const detail = !item.base
                  ? 'This base is no longer on the server. Tap to remove it.'
                  : disabled
                    ? reason
                    : `${item.base.documentCount} document${item.base.documentCount === 1 ? '' : 's'}${
                        item.base.assigned ? ' · shared with you' : ''
                      }`;
                return (
                  <Pressable
                    accessibilityRole="checkbox"
                    accessibilityLabel={item.name}
                    accessibilityState={{ checked, disabled }}
                    disabled={disabled}
                    onPress={() => onToggle(item.ref)}
                    style={({ pressed }) => [
                      styles.row,
                      {
                        borderColor: theme.border,
                        backgroundColor: checked ? theme.secondary : 'transparent',
                        opacity: disabled ? 0.55 : pressed ? 0.8 : 1,
                      },
                    ]}
                  >
                    <View
                      style={[
                        styles.box,
                        {
                          borderColor: checked ? theme.primary : theme.inputBorder,
                          backgroundColor: boxBackground,
                        },
                      ]}
                    >
                      {checked ? (
                        <Text style={[styles.tick, { color: theme.onPrimary }]}>✓</Text>
                      ) : null}
                    </View>
                    <View style={styles.rowBody}>
                      <Text
                        numberOfLines={1}
                        style={[styles.name, { color: theme.text }]}
                      >
                        {item.name}
                      </Text>
                      <Text style={[styles.hint, { color: theme.muted }]}>
                        {detail}
                      </Text>
                    </View>
                  </Pressable>
                );
              }}
            />
          )}

          <View style={styles.actions}>
            <Action title="Manage" tone="secondary" onPress={onManage} />
            {status === 'failed' ? (
              <Action title="Retry" tone="secondary" onPress={onRefresh} />
            ) : null}
            <Action title="Done" onPress={onClose} />
          </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    justifyContent: 'flex-end',
    backgroundColor: 'rgba(0,0,0,0.35)',
  },
  sheet: {
    maxHeight: '80%',
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
    padding: spacing.xl,
    gap: spacing.md,
  },
  title: { fontSize: textSize.heading, fontWeight: '700' },
  hint: { fontSize: textSize.small, lineHeight: 20 },
  center: { padding: spacing.lg, alignItems: 'center', gap: spacing.sm },
  list: { flexGrow: 0 },
  listContent: { gap: spacing.sm },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.md,
    padding: spacing.md,
  },
  box: {
    width: 22,
    height: 22,
    borderRadius: 6,
    borderWidth: 1.5,
    alignItems: 'center',
    justifyContent: 'center',
  },
  tick: { fontSize: 14, fontWeight: '700' },
  rowBody: { flex: 1, gap: 2 },
  name: { fontSize: textSize.body, fontWeight: '600' },
  actions: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    gap: spacing.sm,
    flexWrap: 'wrap',
  },
});
