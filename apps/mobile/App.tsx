import { useEffect, useRef, useState } from 'react';
import {
  AppState,
  Button,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  StatusBar,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';
import { buildStartTurn, newCommandId } from '@/contracts/parse/turn-command';
import {
  TurnRuntimeClient,
  type RuntimeConnectionState,
} from '@/features/chat/transport/TurnRuntimeClient';

type Message = { id: string; question: string; answer: string };
type Connection = {
  origin: string;
  status: 'login' | 'chat';
};

const defaultAddress = __DEV__
  ? Platform.OS === 'android'
    ? 'http://10.0.2.2:18001'
    : 'http://localhost:18001'
  : '';

function serverOrigin(address: string): string {
  const match = /^(https?):\/\/([^/?#\s@]+)\/?$/i.exec(address.trim());
  if (!match) {
    throw new Error(
      'Enter the server address, for example https://tutor.example.com.',
    );
  }
  const [, protocol, host] = match;
  const local = /^(localhost|127\.0\.0\.1|10\.0\.2\.2)(:\d+)?$/i.test(host);
  if (protocol.toLowerCase() !== 'https' && !(__DEV__ && local)) {
    throw new Error('Use HTTPS to connect to this server.');
  }
  return `${protocol.toLowerCase()}://${host}`;
}

function App() {
  return (
    <SafeAreaProvider>
      <StatusBar barStyle="dark-content" />
      <SafeAreaView style={styles.screen}>
        <KeyboardAvoidingView
          style={styles.screen}
          behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        >
          <DeepTutor />
        </KeyboardAvoidingView>
      </SafeAreaView>
    </SafeAreaProvider>
  );
}

function DeepTutor() {
  const [address, setAddress] = useState(defaultAddress);
  const [connection, setConnection] = useState<Connection | null>(null);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState('');

  async function connect(signIn: boolean) {
    setChecking(true);
    setError('');
    try {
      const origin = serverOrigin(address);
      if (signIn) {
        const login = await fetch(`${origin}/api/auth/login`, {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username: username.trim(), password }),
        });
        if (login.status === 401)
          throw new Error('Check your username and password.');
        if (!login.ok)
          throw new Error(`Sign-in failed (HTTP ${login.status}).`);
      }
      const response = await fetch(`${origin}/api/auth/status`, {
        credentials: 'include',
      });
      if (!response.ok)
        throw new Error(`Server check failed (HTTP ${response.status}).`);
      const status = await response.json();
      if (
        typeof status.enabled !== 'boolean' ||
        typeof status.authenticated !== 'boolean'
      ) {
        throw new Error('This server did not return a DeepTutor session.');
      }
      const needsLogin = status.enabled && !status.authenticated;
      setConnection({ origin, status: needsLogin ? 'login' : 'chat' });
      if (signIn && needsLogin)
        throw new Error('The server session could not be established.');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to connect.');
    } finally {
      setChecking(false);
      if (signIn) setPassword('');
    }
  }

  if (connection?.status === 'chat') {
    return (
      <Chat origin={connection.origin} disconnect={() => setConnection(null)} />
    );
  }

  const showLogin = connection?.status === 'login';
  return (
    <ScrollView
      contentContainerStyle={styles.form}
      keyboardShouldPersistTaps="handled"
    >
      <Text style={styles.title}>DeepTutor</Text>
      <Text style={styles.label}>Server address</Text>
      <TextInput
        accessibilityLabel="Server address"
        style={styles.input}
        value={address}
        onChangeText={value => {
          setAddress(value);
          setConnection(null);
          setPassword('');
          setError('');
        }}
        autoCapitalize="none"
        autoCorrect={false}
        keyboardType="url"
        editable={!checking}
        placeholder="https://tutor.example.com"
      />
      {showLogin && (
        <>
          <TextInput
            accessibilityLabel="Username"
            style={styles.input}
            value={username}
            onChangeText={setUsername}
            autoCapitalize="none"
            autoComplete="username"
            editable={!checking}
            placeholder="Username"
          />
          <TextInput
            accessibilityLabel="Password"
            style={styles.input}
            value={password}
            onChangeText={setPassword}
            autoComplete="current-password"
            editable={!checking}
            secureTextEntry
            placeholder="Password"
          />
        </>
      )}
      <Button
        title={checking ? 'Connecting…' : showLogin ? 'Sign in' : 'Connect'}
        disabled={
          checking ||
          !address.trim() ||
          (showLogin && (!username.trim() || !password))
        }
        onPress={() => {
          connect(showLogin);
        }}
      />
      {!!error && (
        <Text accessibilityRole="alert" style={styles.error}>
          {error}
        </Text>
      )}
    </ScrollView>
  );
}

function Chat({
  origin,
  disconnect,
}: {
  origin: string;
  disconnect: () => void;
}) {
  const [state, setState] = useState<RuntimeConnectionState>('idle');
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const transport = useRef<TurnRuntimeClient | null>(null);
  const pending = useRef<string | null>(null);
  const sessionId = useRef<string | undefined>(undefined);
  const scroll = useRef<ScrollView>(null);

  useEffect(() => {
    const client = new TurnRuntimeClient({
      url: `${origin.replace(/^http/, 'ws')}/ws?dt_workspace=`,
      onStateChange: setState,
      onEvent(event) {
        const id = pending.current;
        if (!id) return;
        if (event.type === 'protocol_error') {
          setError(event.message || 'The server rejected this request.');
          pending.current = null;
          setBusy(false);
          return;
        }
        if (!('timestamp' in event)) return;
        if (event.session_id) sessionId.current = event.session_id;
        const finalAnswer = event.metadata?.response;
        const content = event.type === 'content' ? event.content : undefined;
        if (
          typeof content === 'string' ||
          (event.type === 'result' && typeof finalAnswer === 'string')
        ) {
          setMessages(previous =>
            previous.map(message => {
              if (message.id !== id) return message;
              return {
                ...message,
                answer:
                  typeof finalAnswer === 'string' && event.type === 'result'
                    ? finalAnswer
                    : message.answer + (content ?? ''),
              };
            }),
          );
        } else if (event.type === 'error') {
          setError(
            event.content || 'The server could not finish the response.',
          );
        } else if (event.type === 'wait_for_input') {
          setError('This turn needs a reply in the web app.');
        } else if (event.type === 'done') {
          pending.current = null;
          setBusy(false);
        }
      },
    });
    transport.current = client;
    client.connect();
    const listener = AppState.addEventListener('change', next => {
      client.setPageVisible(next === 'active');
    });
    return () => {
      listener.remove();
      client.stop();
      transport.current = null;
    };
  }, [origin]);

  function send() {
    const question = draft.trim();
    const client = transport.current;
    if (!question || !client || pending.current || client.state !== 'connected')
      return;
    const id = newCommandId();
    pending.current = id;
    setBusy(true);
    setError('');
    setDraft('');
    setMessages(previous => [...previous, { id, question, answer: '' }]);
    client.setResumeCursor(null, 0);
    client.send(
      buildStartTurn({
        content: question,
        capability: 'chat',
        client_submission_id: id,
        ...(sessionId.current ? { session_id: sessionId.current } : {}),
      }),
    );
  }

  return (
    <View style={styles.screen}>
      <View style={styles.header}>
        <View>
          <Text style={styles.title}>DeepTutor</Text>
          <Text style={styles.label}>
            {state === 'connected'
              ? 'Connected'
              : state === 'recovering'
              ? 'Reconnecting…'
              : 'Connecting…'}
          </Text>
        </View>
        <Button title="Server" onPress={disconnect} />
      </View>
      <ScrollView
        ref={scroll}
        contentContainerStyle={styles.messages}
        keyboardShouldPersistTaps="handled"
        onContentSizeChange={() =>
          scroll.current?.scrollToEnd({ animated: false })
        }
      >
        {messages.map(message => (
          <View key={message.id} style={styles.exchange}>
            <Text style={styles.question} selectable>
              {message.question}
            </Text>
            {!!message.answer && (
              <Text style={styles.answer} selectable>
                {message.answer}
              </Text>
            )}
          </View>
        ))}
        {!!error && (
          <Text accessibilityRole="alert" style={styles.error}>
            {error}
          </Text>
        )}
      </ScrollView>
      <View style={styles.composer}>
        <TextInput
          accessibilityLabel="Message"
          style={[styles.input, styles.messageInput]}
          value={draft}
          onChangeText={setDraft}
          placeholder="Ask a question"
          multiline
        />
        <Button
          title={busy ? 'Waiting…' : 'Send'}
          onPress={send}
          disabled={busy || !draft.trim() || state !== 'connected'}
        />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: '#f8fafc' },
  form: { padding: 24, gap: 12 },
  title: { fontSize: 24, fontWeight: '700', color: '#142139' },
  label: { color: '#435269' },
  input: {
    backgroundColor: '#fff',
    borderColor: '#9ba9ba',
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 9,
    color: '#142139',
  },
  header: {
    padding: 16,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    backgroundColor: '#fff',
  },
  messages: { padding: 16, gap: 16 },
  exchange: { gap: 8 },
  question: {
    alignSelf: 'flex-end',
    backgroundColor: '#dceafb',
    padding: 12,
    borderRadius: 8,
    color: '#142139',
  },
  answer: { color: '#142139', lineHeight: 22 },
  error: { color: '#a22624' },
  composer: {
    padding: 12,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    backgroundColor: '#fff',
  },
  messageInput: { flex: 1, maxHeight: 120 },
});

export default App;
