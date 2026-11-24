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

import { turnRecoveryStorage } from '../src/storage/turnRecovery';

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
