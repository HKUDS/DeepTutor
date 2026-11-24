import { useCallback, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  FlatList,
  Modal,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { Action, ErrorNotice, Field } from '../components/FormControls';
import { Screen } from '../components/Screen';
import { radius, spacing, textSize, useTheme } from '../theme/useTheme';
import type { SessionSummary } from '../services/sessionApi';

export type SessionsScreenProps = {
  sessions: readonly SessionSummary[];
  status: 'loading' | 'ready' | 'failed';
  refreshing: boolean;
  loadingMore: boolean;
  hasMore: boolean;
  error: string | null;
  currentSessionId: string | null;
  busySessionId: string | null;
  onOpen: (sessionId: string) => void;
  onNewChat: () => void;
  onRefresh: () => void;
  onLoadMore: () => void;
  onRetry: () => void;
  onRename: (sessionId: string, title: string) => Promise<void>;
  onDelete: (sessionId: string) => Promise<void>;
};

function formatUpdatedAt(seconds: number): string {
  if (!seconds) return '';
  const date = new Date(seconds * 1000);
  if (Number.isNaN(date.getTime())) return '';
  const now = new Date();
  const sameDay =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate();
  const hours = String(date.getHours()).padStart(2, '0');
  const minutes = String(date.getMinutes()).padStart(2, '0');
  if (sameDay) return `${hours}:${minutes}`;
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return date.getFullYear() === now.getFullYear()
    ? `${month}/${day}`
    : `${date.getFullYear()}/${month}/${day}`;
}

function titleOf(session: SessionSummary): string {
  const title = session.title.trim();
  if (title) return title;
  const preview = session.lastMessage.trim().replace(/\s+/g, ' ');
  return preview ? preview.slice(0, 60) : 'Untitled conversation';
}

export function SessionsScreen({
  sessions,
  status,
  refreshing,
  loadingMore,
  hasMore,
  error,
  currentSessionId,
  busySessionId,
  onOpen,
  onNewChat,
  onRefresh,
  onLoadMore,
  onRetry,
  onRename,
  onDelete,
}: SessionsScreenProps) {
  const theme = useTheme();
  const [editing, setEditing] = useState<SessionSummary | null>(null);
  const [draft, setDraft] = useState('');
  const [actionError, setActionError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const openRename = useCallback((session: SessionSummary) => {
    setActionError(null);
    setDraft(titleOf(session));
    setEditing(session);
  }, []);

  const saveRename = useCallback(async () => {
    const session = editing;
    const title = draft.trim();
    if (!session || !title || saving) return;
    setSaving(true);
    try {
      await onRename(session.id, title);
      setEditing(null);
    } catch {
      setActionError('Could not rename this conversation. Try again.');
    } finally {
      setSaving(false);
    }
  }, [draft, editing, onRename, saving]);

  const confirmDelete = useCallback(
    (session: SessionSummary) => {
      setActionError(null);
      Alert.alert(
        'Delete conversation?',
        `"${titleOf(session)}" and its messages will be removed from the server.`,
        [
          { text: 'Cancel', style: 'cancel' },
          {
            text: 'Delete',
            style: 'destructive',
            onPress: () => {
              onDelete(session.id).catch(() => {
                setActionError(
                  'Could not delete this conversation. Try again.',
                );
              });
            },
          },
        ],
      );
    },
    [onDelete],
  );

  const loading = status === 'loading';

  return (
    <Screen>
      <View
        style={[
          styles.header,
          { backgroundColor: theme.surface, borderColor: theme.border },
        ]}
      >
        <View style={styles.heading}>
          <Text
            accessibilityRole="header"
            style={[styles.title, { color: theme.text }]}
          >
            Conversations
          </Text>
          <Text style={[styles.hint, { color: theme.muted }]}>
            Stored on your DeepTutor server.
          </Text>
        </View>
        <Action title="New" onPress={onNewChat} />
      </View>

      {actionError ? (
        <View style={styles.noticeRow}>
          <ErrorNotice message={actionError} />
        </View>
      ) : null}
      {error ? (
        <View style={styles.noticeRow}>
          <ErrorNotice message={error} />
          {status === 'failed' ? (
            <Action title="Try again" tone="secondary" onPress={onRetry} />
          ) : null}
        </View>
      ) : null}

      {loading ? (
        <View style={styles.center} accessibilityLiveRegion="polite">
          <ActivityIndicator color={theme.primary} />
          <Text style={[styles.hint, { color: theme.muted }]}>
            Loading conversations…
          </Text>
        </View>
      ) : (
        <FlatList
          data={sessions}
          keyExtractor={session => session.id}
          contentContainerStyle={styles.list}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={onRefresh}
              tintColor={theme.primary}
            />
          }
          onEndReachedThreshold={0.4}
          onEndReached={() => {
            if (hasMore && !loadingMore) onLoadMore();
          }}
          ListEmptyComponent={
            status === 'failed' ? null : (
              <View style={styles.center}>
                <Text style={[styles.emptyTitle, { color: theme.text }]}>
                  No conversations yet
                </Text>
                <Text style={[styles.hint, { color: theme.muted }]}>
                  Ask a question and it will appear here.
                </Text>
              </View>
            )
          }
          ListFooterComponent={
            loadingMore ? (
              <ActivityIndicator
                style={styles.footer}
                color={theme.primary}
              />
            ) : null
          }
          renderItem={({ item }) => {
            const current = item.id === currentSessionId;
            const live = Boolean(item.activeTurnId);
            return (
              <Pressable
                accessibilityRole="button"
                // Without an explicit label the row announces its whole subtree
                // (title, date, counts and both actions) as one name.
                accessibilityLabel={titleOf(item)}
                accessibilityState={{ selected: current, disabled: Boolean(busySessionId) }}
                disabled={Boolean(busySessionId)}
                onPress={() => onOpen(item.id)}
                style={({ pressed }) => [
                  styles.row,
                  {
                    backgroundColor: current ? theme.secondary : theme.surface,
                    borderColor: theme.border,
                    opacity: busySessionId === item.id ? 0.6 : pressed ? 0.8 : 1,
                  },
                ]}
              >
                <View style={styles.rowBody}>
                  <Text
                    numberOfLines={1}
                    style={[styles.rowTitle, { color: theme.text }]}
                  >
                    {titleOf(item)}
                  </Text>
                  <View style={styles.rowMeta}>
                    <Text style={[styles.hint, { color: theme.muted }]}>
                      {formatUpdatedAt(item.updatedAt)}
                    </Text>
                    {item.messageCount ? (
                      <Text style={[styles.hint, { color: theme.muted }]}>
                        {item.messageCount} message
                        {item.messageCount === 1 ? '' : 's'}
                      </Text>
                    ) : null}
                    {live ? (
                      <Text style={[styles.live, { color: theme.primary }]}>
                        {busySessionId === item.id ? 'Opening…' : 'Running'}
                      </Text>
                    ) : null}
                  </View>
                </View>
                <View style={styles.rowActions}>
                  <Action
                    title="Rename"
                    tone="secondary"
                    onPress={() => openRename(item)}
                  />
                  <Action
                    title="Delete"
                    tone="secondary"
                    onPress={() => confirmDelete(item)}
                  />
                </View>
              </Pressable>
            );
          }}
        />
      )}

      <Modal
        visible={editing !== null}
        transparent
        animationType="fade"
        onRequestClose={() => setEditing(null)}
      >
        <View style={styles.backdrop}>
          <View
            style={[
              styles.dialog,
              { backgroundColor: theme.surface, borderColor: theme.border },
            ]}
          >
            <Text
              accessibilityRole="header"
              style={[styles.emptyTitle, { color: theme.text }]}
            >
              Rename conversation
            </Text>
            <Field
              label="Title"
              value={draft}
              onChangeText={setDraft}
              autoFocus
              maxLength={200}
              returnKeyType="done"
              onSubmitEditing={saveRename}
            />
            <View style={styles.dialogActions}>
              <Action
                title="Cancel"
                tone="secondary"
                onPress={() => setEditing(null)}
              />
              <Action
                title="Save"
                disabled={!draft.trim()}
                busy={saving}
                onPress={saveRename}
              />
            </View>
          </View>
        </View>
      </Modal>
    </Screen>
  );
}

const styles = StyleSheet.create({
  header: {
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    borderBottomWidth: StyleSheet.hairlineWidth,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing.md,
  },
  heading: { flex: 1, gap: spacing.xs },
  title: { fontSize: textSize.heading, fontWeight: '700' },
  hint: { fontSize: textSize.small, lineHeight: 20 },
  noticeRow: { paddingHorizontal: spacing.lg, paddingTop: spacing.sm, gap: spacing.sm },
  list: { flexGrow: 1, padding: spacing.lg, gap: spacing.sm },
  center: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: spacing.xl,
    gap: spacing.sm,
  },
  emptyTitle: { fontSize: textSize.body, fontWeight: '700' },
  footer: { paddingVertical: spacing.lg },
  row: {
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.md,
    padding: spacing.md,
    gap: spacing.sm,
  },
  rowBody: { gap: spacing.xs },
  rowTitle: { fontSize: textSize.body, fontWeight: '600' },
  rowMeta: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  live: { fontSize: textSize.small, fontWeight: '700' },
  rowActions: { flexDirection: 'row', gap: spacing.sm },
  backdrop: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.4)',
    justifyContent: 'center',
    padding: spacing.xl,
  },
  dialog: {
    borderRadius: radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
    padding: spacing.lg,
    gap: spacing.md,
  },
  dialogActions: { flexDirection: 'row', justifyContent: 'flex-end', gap: spacing.sm },
});
