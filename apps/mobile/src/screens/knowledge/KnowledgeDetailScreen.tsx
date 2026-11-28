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

import { Action, ErrorNotice, Field } from '../../components/FormControls';
import { Screen } from '../../components/Screen';
import {
  documentState,
  failureReason,
  fileState,
  isBusy,
  type DocumentState,
} from '../../features/knowledge/refs';
import type { UploadItem } from '../../features/knowledge/useUploads';
import type {
  KnowledgeBaseSummary,
  KnowledgeFileEntry,
  KnowledgeProgress,
  UploadPolicy,
} from '../../services/knowledgeApi';
import { formatBytes } from '../../services/knowledgeUpload';
import { radius, spacing, textSize, useTheme } from '../../theme/useTheme';
import { StateBadge } from './StateBadge';

export type KnowledgeDetailScreenProps = {
  kb: KnowledgeBaseSummary | null;
  files: readonly KnowledgeFileEntry[];
  status: 'loading' | 'ready' | 'failed';
  error: string | null;
  refreshing: boolean;
  retrying: boolean;
  saving: boolean;
  policy: UploadPolicy | null;
  uploads: {
    items: readonly UploadItem[];
    cancel: (id: string) => void;
    retry: (id: string) => void;
    dismiss: (id: string) => void;
  };
  onBack: () => void;
  onRefresh: () => void;
  onRetry: () => void;
  onPickFiles: () => void;
  onDeleteFile: (name: string) => Promise<boolean>;
  onSaveDescription: (text: string) => Promise<boolean>;
  onDeleteBase: () => void;
};

function formatModified(seconds: number): string {
  if (!seconds) return '';
  const date = new Date(seconds * 1000);
  if (Number.isNaN(date.getTime())) return '';
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${date.getFullYear()}/${month}/${day}`;
}

/**
 * One line under the status badge.
 *
 * Everything here is something the server actually reported: a failure reason,
 * a run's own message, or the fact that the index is older than its documents.
 * Rebuilding is a provider-specific confirmation flow the web app owns, so the
 * app says where to rebuild instead of pretending it can.
 */
function statusCopy(
  kb: KnowledgeBaseSummary,
  state: DocumentState,
  live: KnowledgeProgress | null,
): string {
  if (state === 'failed') return failureReason(kb.progress, kb.lastError);
  if (state === 'needs_reindex') {
    return 'The index is older than its documents. Rebuild it from the web app to cite them.';
  }
  if (state === 'ready') {
    return kb.ragInitialized
      ? 'Answers can cite these documents.'
      : 'This base has not been indexed yet.';
  }
  return live?.message || 'The server is working on this base.';
}

function UploadRow({
  item,
  onCancel,
  onRetry,
  onDismiss,
}: {
  item: UploadItem;
  onCancel: () => void;
  onRetry: () => void;
  onDismiss: () => void;
}) {
  const theme = useTheme();
  const percent =
    item.total > 0 ? Math.min(100, Math.round((item.loaded / item.total) * 100)) : 0;
  const uploading = item.status === 'uploading';
  const copy =
    item.status === 'queued'
      ? 'Waiting to upload…'
      : item.status === 'uploading'
        ? `${percent}% · ${formatBytes(item.loaded)} of ${formatBytes(item.total)}`
        : item.status === 'done'
          ? 'Uploaded. The server is processing it.'
          : item.status === 'cancelled'
            ? 'Upload cancelled. The server keeps whatever it already received.'
            : item.error || 'The upload failed.';

  return (
    <View
      style={[
        styles.uploadRow,
        { borderColor: theme.border, backgroundColor: theme.surface },
      ]}
    >
      <View style={styles.uploadHead}>
        <Text numberOfLines={1} style={[styles.fileName, { color: theme.text }]}>
          {item.name}
        </Text>
        {uploading || item.status === 'queued' ? (
          <Action
            title="Cancel"
            label={`Cancel ${item.name}`}
            tone="secondary"
            onPress={onCancel}
          />
        ) : item.status === 'failed' && item.retryable ? (
          <Action
            title="Retry"
            label={`Retry ${item.name}`}
            tone="secondary"
            onPress={onRetry}
          />
        ) : (
          <Action
            title="Dismiss"
            label={`Dismiss ${item.name}`}
            tone="secondary"
            onPress={onDismiss}
          />
        )}
      </View>
      {uploading ? (
        <View
          accessible
          accessibilityRole="progressbar"
          accessibilityValue={{ min: 0, max: 100, now: percent }}
          style={[styles.track, { backgroundColor: theme.secondary }]}
        >
          <View
            style={[styles.fill, { width: `${percent}%`, backgroundColor: theme.primary }]}
          />
        </View>
      ) : null}
      <Text
        style={[
          styles.hint,
          { color: item.status === 'failed' ? theme.error : theme.muted },
        ]}
      >
        {copy}
      </Text>
    </View>
  );
}

export function KnowledgeDetailScreen({
  kb,
  files,
  status,
  error,
  refreshing,
  retrying,
  saving,
  policy,
  uploads,
  onBack,
  onRefresh,
  onRetry,
  onPickFiles,
  onDeleteFile,
  onSaveDescription,
  onDeleteBase,
}: KnowledgeDetailScreenProps) {
  const theme = useTheme();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');

  const openEditor = useCallback(() => {
    setDraft(kb?.description ?? '');
    setEditing(true);
  }, [kb?.description]);

  const save = useCallback(async () => {
    const ok = await onSaveDescription(draft.trim());
    if (ok) setEditing(false);
  }, [draft, onSaveDescription]);

  const confirmDeleteFile = useCallback(
    (entry: KnowledgeFileEntry) => {
      Alert.alert(
        'Remove this document?',
        `"${entry.name}" will be removed from the server. Its vectors are not pruned until the base is re-indexed.`,
        [
          { text: 'Cancel', style: 'cancel' },
          {
            text: 'Remove',
            style: 'destructive',
            onPress: () => {
              onDeleteFile(entry.name).catch(() => {});
            },
          },
        ],
      );
    },
    [onDeleteFile],
  );

  const confirmDeleteBase = useCallback(() => {
    if (!kb) return;
    Alert.alert(
      'Delete this knowledge base?',
      `"${kb.name}" and all of its documents will be removed from the server. This cannot be undone.`,
      [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Delete', style: 'destructive', onPress: onDeleteBase },
      ],
    );
  }, [kb, onDeleteBase]);

  const state = kb ? documentState(kb) : 'unknown';
  const live = kb?.progress && isBusy(state) ? kb.progress : null;
  const filesReadable = kb ? !kb.readOnly : false;

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
            numberOfLines={1}
            style={[styles.title, { color: theme.text }]}
          >
            {kb?.name ?? 'Knowledge base'}
          </Text>
          <Text style={[styles.hint, { color: theme.muted }]}>
            {kb
              ? `${kb.documentCount} document${kb.documentCount === 1 ? '' : 's'}${kb.provider ? ` · ${kb.provider}` : ''}`
              : 'Loading…'}
          </Text>
        </View>
        <View style={styles.headerActions}>
          <Action title="Back" tone="secondary" onPress={onBack} />
          {kb && filesReadable ? (
            <Action title="Delete" tone="secondary" onPress={confirmDeleteBase} />
          ) : null}
        </View>
      </View>

      {error ? (
        <View style={styles.noticeRow}>
          <ErrorNotice message={error} />
        </View>
      ) : null}

      {status === 'loading' ? (
        <View style={styles.center} accessibilityLiveRegion="polite">
          <ActivityIndicator color={theme.primary} />
          <Text style={[styles.hint, { color: theme.muted }]}>
            Loading this knowledge base…
          </Text>
        </View>
      ) : status === 'failed' ? (
        <View style={styles.center}>
          <Text style={[styles.hint, { color: theme.muted }]}>
            This knowledge base could not be loaded.
          </Text>
          <Action title="Try again" tone="secondary" onPress={onRetry} />
        </View>
      ) : (
        <FlatList
          data={files}
          keyExtractor={file => `${file.type}:${file.name}`}
          contentContainerStyle={styles.list}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={onRefresh}
              tintColor={theme.primary}
            />
          }
          ListHeaderComponent={
            <View style={styles.headerBlock}>
              <View style={styles.statusRow}>
                <StateBadge state={state} />
                {kb ? (
                  <Text style={[styles.hint, { color: theme.muted }]}>
                    {statusCopy(kb, state, live)}
                  </Text>
                ) : null}
              </View>

              {live ? (
                <View style={styles.progressBlock}>
                  <View
                    accessible
                    accessibilityRole="progressbar"
                    accessibilityValue={{ min: 0, max: 100, now: live.percent }}
                    style={[styles.track, { backgroundColor: theme.secondary }]}
                  >
                    <View
                      style={[
                        styles.fill,
                        { width: `${live.percent}%`, backgroundColor: theme.primary },
                      ]}
                    />
                  </View>
                  <Text style={[styles.hint, { color: theme.muted }]}>
                    {live.total > 0
                      ? `${live.current} of ${live.total}${live.fileName ? ` · ${live.fileName}` : ''}`
                      : live.message}
                  </Text>
                </View>
              ) : null}

              {kb && state === 'failed' ? (
                <Action
                  title="Retry processing"
                  tone="secondary"
                  busy={retrying}
                  onPress={onRetry}
                />
              ) : null}

              <View style={styles.descriptionRow}>
                <Text style={[styles.hint, { color: theme.muted }]}>
                  {kb?.description || 'No description yet.'}
                </Text>
                {filesReadable ? (
                  <Action
                    title="Edit description"
                    tone="secondary"
                    onPress={openEditor}
                  />
                ) : null}
              </View>

              {filesReadable ? (
                <View style={styles.uploadBar}>
                  <Action title="Upload files" onPress={onPickFiles} />
                  <Text style={[styles.hint, { color: theme.muted }]}>
                    {policy
                      ? policy.allowAnyExtension
                        ? `Any file up to ${formatBytes(policy.maxFileSizeBytes)}.`
                        : `${policy.extensions.join(', ')} up to ${formatBytes(policy.maxFileSizeBytes)}.`
                      : 'Checking which formats this server accepts…'}
                  </Text>
                </View>
              ) : (
                <Text style={[styles.hint, { color: theme.muted }]}>
                  This base is read-only for your account.
                </Text>
              )}

              {uploads.items.length ? (
                <View style={styles.uploads}>
                  <Text style={[styles.sectionTitle, { color: theme.text }]}>
                    Uploads
                  </Text>
                  {uploads.items.map(item => (
                    <UploadRow
                      key={item.id}
                      item={item}
                      onCancel={() => uploads.cancel(item.id)}
                      onRetry={() => uploads.retry(item.id)}
                      onDismiss={() => uploads.dismiss(item.id)}
                    />
                  ))}
                </View>
              ) : null}

              <Text style={[styles.sectionTitle, { color: theme.text }]}>
                Documents
              </Text>
              <Text style={[styles.hint, { color: theme.muted }]}>
                The server reports processing per run, not per document. “Run
                done” means the last run finished, not that this file was
                verified on its own.
              </Text>
            </View>
          }
          ListEmptyComponent={
            <View style={styles.center}>
              <Text style={[styles.hint, { color: theme.muted }]}>
                No documents yet. Upload a PDF, text or Office file to get started.
              </Text>
            </View>
          }
          renderItem={({ item }) => {
            const fileStateValue = kb ? fileState(kb, item.name) : 'unknown';
            const isFolder = item.type === 'folder';
            return (
              <View
                style={[
                  styles.fileRow,
                  { borderColor: theme.border, backgroundColor: theme.surface },
                ]}
              >
                <View style={styles.fileBody}>
                  <Text
                    numberOfLines={1}
                    style={[styles.fileName, { color: theme.text }]}
                  >
                    {item.name}
                  </Text>
                  <Text style={[styles.hint, { color: theme.muted }]}>
                    {isFolder
                      ? 'Folder'
                      : `${formatBytes(item.size)}${item.modified ? ` · ${formatModified(item.modified)}` : ''}`}
                  </Text>
                </View>
                {isFolder ? null : <StateBadge state={fileStateValue} />}
                {filesReadable && !isFolder ? (
                  <Pressable
                    accessibilityRole="button"
                    accessibilityLabel={`Remove ${item.name}`}
                    onPress={() => confirmDeleteFile(item)}
                    style={({ pressed }) => [styles.remove, { opacity: pressed ? 0.6 : 1 }]}
                  >
                    <Text style={[styles.removeLabel, { color: theme.error }]}>
                      Remove
                    </Text>
                  </Pressable>
                ) : null}
              </View>
            );
          }}
        />
      )}

      <Modal
        visible={editing}
        transparent
        animationType="fade"
        onRequestClose={() => setEditing(false)}
      >
        <View style={styles.backdrop}>
          <View
            style={[
              styles.sheet,
              { backgroundColor: theme.surface, borderColor: theme.border },
            ]}
          >
            <Text
              accessibilityRole="header"
              style={[styles.sheetTitle, { color: theme.text }]}
            >
              Description
            </Text>
            <Field
              label="Description"
              hideLabel
              value={draft}
              onChangeText={setDraft}
              multiline
              autoFocus
              placeholder="What is this base for?"
              editable={!saving}
            />
            <View style={styles.sheetActions}>
              <Action
                title="Cancel"
                tone="secondary"
                disabled={saving}
                onPress={() => setEditing(false)}
              />
              <Action title="Save" busy={saving} onPress={save} />
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
  headerActions: { flexDirection: 'row', gap: spacing.sm },
  title: { fontSize: textSize.heading, fontWeight: '700' },
  hint: { fontSize: textSize.small, lineHeight: 20 },
  noticeRow: { paddingHorizontal: spacing.lg, paddingTop: spacing.sm },
  center: { padding: spacing.xl, gap: spacing.md, alignItems: 'center' },
  list: { padding: spacing.lg, gap: spacing.md, flexGrow: 1 },
  headerBlock: { gap: spacing.md },
  statusRow: { gap: spacing.sm },
  progressBlock: { gap: spacing.xs },
  track: { height: 8, borderRadius: radius.sm, overflow: 'hidden' },
  fill: { height: '100%' },
  descriptionRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing.md,
  },
  uploadBar: { gap: spacing.sm },
  uploads: { gap: spacing.sm },
  uploadRow: {
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.md,
    padding: spacing.md,
    gap: spacing.sm,
    marginBottom: spacing.sm,
  },
  uploadHead: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing.sm,
  },
  sectionTitle: { fontSize: textSize.body, fontWeight: '700' },
  fileRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.md,
    padding: spacing.md,
  },
  fileBody: { flex: 1, gap: spacing.xs },
  fileName: { fontSize: textSize.body, fontWeight: '600' },
  remove: { paddingHorizontal: spacing.sm, paddingVertical: spacing.xs },
  removeLabel: { fontSize: textSize.small, fontWeight: '600' },
  backdrop: {
    flex: 1,
    justifyContent: 'center',
    padding: spacing.xl,
    backgroundColor: 'rgba(0,0,0,0.35)',
  },
  sheet: {
    borderRadius: radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
    padding: spacing.xl,
    gap: spacing.md,
  },
  sheetTitle: { fontSize: textSize.heading, fontWeight: '700' },
  sheetActions: { flexDirection: 'row', justifyContent: 'flex-end', gap: spacing.sm },
});
