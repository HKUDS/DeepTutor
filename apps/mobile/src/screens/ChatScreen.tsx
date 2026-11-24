import { useRef, useState } from 'react';
import {
  FlatList,
  StyleSheet,
  Text,
  View,
  type NativeScrollEvent,
  type NativeSyntheticEvent,
} from 'react-native';
import type { RuntimeConnectionState } from '@/features/chat/transport/TurnRuntimeClient';
import { Action, ErrorNotice, Field } from '../components/FormControls';
import { Screen } from '../components/Screen';
import { radius, spacing, textSize, useTheme } from '../theme/useTheme';

type Message = { id: string; question: string; answer: string };

export type ChatScreenProps = {
  connection: RuntimeConnectionState;
  messages: readonly Message[];
  phase: 'ready' | 'running' | 'waiting' | 'stopping';
  waitingPrompt: string | null;
  error: string | null;
  send: (text: string) => boolean;
  reply: (text: string) => Promise<boolean>;
  cancel: () => Promise<void>;
  retryConnection: () => void;
  reset: () => void;
  onOpenSettings: () => void;
};

const connectionCopy: Record<RuntimeConnectionState, string> = {
  idle: 'Disconnected',
  connecting: 'Connecting…',
  connected: 'Connected',
  recovering: 'Reconnecting…',
  stopped: 'Disconnected',
};

export function ChatScreen({
  connection,
  messages,
  phase,
  waitingPrompt,
  error,
  send,
  reply,
  cancel,
  retryConnection,
  reset,
  onOpenSettings,
}: ChatScreenProps) {
  const theme = useTheme();
  const [draft, setDraft] = useState('');
  const [replying, setReplying] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const list = useRef<FlatList<Message>>(null);
  const follow = useRef(true);
  const awaitingInput = phase === 'waiting';
  const composing = phase === 'ready' || awaitingInput;
  const canSubmit =
    composing && connection === 'connected' && !replying && !!draft.trim();

  function followLatest() {
    if (follow.current) list.current?.scrollToEnd({ animated: false });
  }

  function handleScroll(event: NativeSyntheticEvent<NativeScrollEvent>) {
    const { contentOffset, contentSize, layoutMeasurement } = event.nativeEvent;
    follow.current =
      contentSize.height - layoutMeasurement.height - contentOffset.y < 72;
  }

  async function submit() {
    if (!canSubmit) return;
    setActionError(null);
    follow.current = true;
    if (!awaitingInput) {
      if (send(draft.trim())) setDraft('');
      return;
    }
    setReplying(true);
    try {
      if (await reply(draft.trim())) setDraft('');
    } catch {
      setActionError('Could not send your reply. Try again.');
    } finally {
      setReplying(false);
    }
  }

  async function stop() {
    setActionError(null);
    try {
      await cancel();
    } catch {
      setActionError('Could not stop this reply. Try again.');
    }
  }

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
            DeepTutor
          </Text>
          <Text
            accessibilityLiveRegion="polite"
            style={[styles.status, { color: theme.muted }]}
          >
            {connectionCopy[connection]}
          </Text>
        </View>
        <Action title="Settings" tone="secondary" onPress={onOpenSettings} />
      </View>
      <FlatList
        ref={list}
        data={messages}
        keyExtractor={message => message.id}
        contentContainerStyle={styles.conversation}
        keyboardShouldPersistTaps="handled"
        onScroll={handleScroll}
        scrollEventThrottle={48}
        onContentSizeChange={followLatest}
        renderItem={({ item }) => (
          <View style={styles.exchange}>
            <Text
              selectable
              style={[
                styles.question,
                { color: theme.text, backgroundColor: theme.secondary },
              ]}
            >
              {item.question}
            </Text>
            {item.answer ? (
              <Text selectable style={[styles.answer, { color: theme.text }]}>
                {item.answer}
              </Text>
            ) : null}
          </View>
        )}
        ListEmptyComponent={
          <View style={styles.empty}>
            <Text
              accessibilityRole="header"
              style={[styles.emptyTitle, { color: theme.text }]}
            >
              What would you like to learn?
            </Text>
            <Text style={[styles.status, { color: theme.muted }]}>
              Ask a question to get started.
            </Text>
          </View>
        }
      />
      <View
        style={[
          styles.composer,
          { backgroundColor: theme.surface, borderColor: theme.border },
        ]}
      >
        <ErrorNotice message={actionError || error} />
        {connection === 'stopped' || connection === 'idle' ? (
          <Action
            title="Reconnect"
            tone="secondary"
            onPress={retryConnection}
          />
        ) : null}
        {awaitingInput ? (
          <Text
            accessibilityLiveRegion="polite"
            style={[styles.status, { color: theme.text }]}
          >
            {waitingPrompt || 'DeepTutor is waiting for your reply.'}
          </Text>
        ) : null}
        {phase === 'running' || phase === 'stopping' ? (
          <Text
            accessibilityLiveRegion="polite"
            style={[styles.status, { color: theme.muted }]}
          >
            {phase === 'stopping' ? 'Stopping…' : 'DeepTutor is replying…'}
          </Text>
        ) : null}
        <View style={styles.composerRow}>
          <Field
            label={awaitingInput ? 'Reply' : 'Message'}
            hideLabel
            value={draft}
            onChangeText={setDraft}
            editable={composing && !replying}
            placeholder={awaitingInput ? 'Write a reply' : 'Ask a question'}
            style={styles.composerInput}
            multiline
          />
          {composing ? (
            <Action
              title={awaitingInput ? 'Reply' : 'Send'}
              disabled={!canSubmit && !replying}
              busy={replying}
              onPress={submit}
            />
          ) : (
            <Action
              title="Stop"
              tone="secondary"
              busy={phase === 'stopping'}
              onPress={stop}
            />
          )}
        </View>
        {awaitingInput || (phase === 'ready' && messages.length > 0) ? (
          <View style={styles.secondaryRow}>
            {awaitingInput ? (
              <Action
                title="Stop task"
                tone="secondary"
                disabled={replying}
                onPress={stop}
              />
            ) : (
              <Action
                title="New chat"
                tone="secondary"
                onPress={() => {
                  reset();
                  follow.current = true;
                  setDraft('');
                  setActionError(null);
                }}
              />
            )}
          </View>
        ) : null}
      </View>
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
  status: { fontSize: textSize.small, lineHeight: 20 },
  conversation: { flexGrow: 1, padding: spacing.lg, gap: spacing.lg },
  exchange: { gap: spacing.md },
  question: {
    alignSelf: 'flex-end',
    maxWidth: '88%',
    borderRadius: radius.md,
    padding: spacing.md,
    fontSize: textSize.body,
    lineHeight: 23,
  },
  answer: { fontSize: textSize.body, lineHeight: 24 },
  empty: {
    flex: 1,
    justifyContent: 'center',
    padding: spacing.md,
    gap: spacing.sm,
  },
  emptyTitle: { fontSize: textSize.heading, fontWeight: '700' },
  composer: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    gap: spacing.sm,
    borderTopWidth: StyleSheet.hairlineWidth,
  },
  composerRow: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    gap: spacing.sm,
  },
  composerInput: { flex: 1 },
  secondaryRow: { alignSelf: 'flex-end' },
});
