jest.mock('@react-native-async-storage/async-storage', () => {
  const data = new Map<string, string>();
  return {
    __data: data,
    getItem: jest.fn(async (key: string) => data.get(key) ?? null),
    setItem: jest.fn(async (key: string, value: string) => {
      data.set(key, value);
    }),
    removeItem: jest.fn(async (key: string) => {
      data.delete(key);
    }),
    getAllKeys: jest.fn(async () => [...data.keys()]),
    multiRemove: jest.fn(async (keys: string[]) => {
      for (const key of keys) data.delete(key);
    }),
  };
});

import AsyncStorage from '@react-native-async-storage/async-storage';

import { turnRecoveryStorage, lastSessionStorage } from '../src/storage/turnRecovery';

const store = (
  AsyncStorage as unknown as { __data: Map<string, string> }
).__data;

const scope = {
  origin: 'https://tutor.example.test',
  account: 'acct-1',
  workspace: '',
};

// Fixed at load so a round-trip assertion cannot drift by a millisecond.
const NOW = Date.now();

function record(overrides: Record<string, unknown> = {}) {
  return {
    version: 1 as const,
    sessionId: 'session-1',
    turnId: 'turn-1',
    clientSubmissionId: 'submission-1',
    lastSeq: 12,
    status: 'running' as const,
    updatedAt: NOW,
    ...overrides,
  };
}

beforeEach(() => store.clear());

test('round-trips the minimum needed to ask the server about a run', async () => {
  await turnRecoveryStorage.write(scope, record());
  await expect(turnRecoveryStorage.read(scope)).resolves.toEqual(record());
});

test('keeps accounts, servers and workspaces in separate namespaces', async () => {
  await turnRecoveryStorage.write(scope, record());
  await expect(
    turnRecoveryStorage.read({ ...scope, account: 'acct-2' }),
  ).resolves.toBeNull();
  await expect(
    turnRecoveryStorage.read({ ...scope, origin: 'https://other.test' }),
  ).resolves.toBeNull();
  await expect(
    turnRecoveryStorage.read({ ...scope, workspace: 'w1' }),
  ).resolves.toBeNull();
});

test('a delimiter inside an identifier cannot collide with another namespace', async () => {
  await turnRecoveryStorage.write(
    { origin: 'https://a.test', account: 'x:y', workspace: '' },
    record(),
  );
  await expect(
    turnRecoveryStorage.read({
      origin: 'https://a.test',
      account: 'x',
      workspace: 'y',
    }),
  ).resolves.toBeNull();
});

test('ignores a corrupt, stale or unknown-version record', async () => {
  await turnRecoveryStorage.write(scope, record());
  const key = [...store.keys()][0];
  store.set(key, '{not json');
  await expect(turnRecoveryStorage.read(scope)).resolves.toBeNull();

  store.set(key, JSON.stringify(record({ updatedAt: NOW - 8 * 86_400_000 })));
  await expect(turnRecoveryStorage.read(scope)).resolves.toBeNull();

  store.set(key, JSON.stringify(record({ version: 2 })));
  await expect(turnRecoveryStorage.read(scope)).resolves.toBeNull();
});

test('a record without a turn id is not actionable and is dropped', async () => {
  await turnRecoveryStorage.write(scope, record({ turnId: '' }));
  await expect(turnRecoveryStorage.read(scope)).resolves.toBeNull();
});

test('clearing removes one scope and leaving a server removes all of them', async () => {
  await turnRecoveryStorage.write(scope, record());
  await turnRecoveryStorage.write({ ...scope, account: 'acct-2' }, record());
  await turnRecoveryStorage.clear(scope);
  await expect(turnRecoveryStorage.read(scope)).resolves.toBeNull();
  await expect(
    turnRecoveryStorage.read({ ...scope, account: 'acct-2' }),
  ).resolves.not.toBeNull();

  await turnRecoveryStorage.clearServer(scope.origin);
  await expect(
    turnRecoveryStorage.read({ ...scope, account: 'acct-2' }),
  ).resolves.toBeNull();
});

test('remembers the last open conversation per scope', async () => {
  await expect(lastSessionStorage.read(scope)).resolves.toBeNull();
  await lastSessionStorage.write(scope, 'session-9');
  await expect(lastSessionStorage.read(scope)).resolves.toBe('session-9');
  // Another account on the same server must not inherit it.
  await expect(
    lastSessionStorage.read({ ...scope, account: 'acct-2' }),
  ).resolves.toBeNull();
  await lastSessionStorage.clear(scope);
  await expect(lastSessionStorage.read(scope)).resolves.toBeNull();
});

test('a last-session entry that is stale, corrupt or empty is ignored', async () => {
  await lastSessionStorage.write(scope, 'session-9');
  const key = [...store.keys()].find(k => k.includes('last-session')) as string;
  expect(key).toBeDefined();

  store.set(key, '{"version":1,"sessionId":"","updatedAt":' + NOW + '}');
  await expect(lastSessionStorage.read(scope)).resolves.toBeNull();

  store.set(key, '{"version":1,"sessionId":"s","updatedAt":1}');
  await expect(lastSessionStorage.read(scope)).resolves.toBeNull();

  store.set(key, 'not json');
  await expect(lastSessionStorage.read(scope)).resolves.toBeNull();
});

test('leaving a server forgets the conversation as well as the run', async () => {
  await turnRecoveryStorage.write(scope, record());
  await lastSessionStorage.write(scope, 'session-9');
  await turnRecoveryStorage.clearServer(scope.origin);
  await expect(turnRecoveryStorage.read(scope)).resolves.toBeNull();
  await expect(lastSessionStorage.read(scope)).resolves.toBeNull();
});
