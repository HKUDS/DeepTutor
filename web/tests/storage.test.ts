import assert from "node:assert/strict";
import test from "node:test";

import { defineStorageKey, physicalStorageKey } from "../shared/storage/keys";
import {
  StorageStore,
  type StorageEventLike,
  type StorageEventTargetLike,
  type StorageLike,
} from "../shared/storage/store";
import { encodeStorageValue } from "../shared/storage/schema";

class MemoryStorage implements StorageLike {
  readonly values = new Map<string, string>();
  get length() {
    return this.values.size;
  }
  getItem(key: string) {
    return this.values.get(key) ?? null;
  }
  setItem(key: string, value: string) {
    this.values.set(key, value);
  }
  removeItem(key: string) {
    this.values.delete(key);
  }
  key(index: number) {
    return [...this.values.keys()][index] ?? null;
  }
}

class MemoryEvents implements StorageEventTargetLike {
  readonly listeners = new Set<(event: StorageEventLike) => void>();
  addEventListener(
    _type: "storage",
    listener: (event: StorageEventLike) => void,
  ) {
    this.listeners.add(listener);
  }
  removeEventListener(
    _type: "storage",
    listener: (event: StorageEventLike) => void,
  ) {
    this.listeners.delete(listener);
  }
  dispatch(event: StorageEventLike) {
    for (const listener of this.listeners) listener(event);
  }
}

const countKey = defineStorageKey({
  name: "tests.count",
  scope: "local" as const,
  version: 2,
  fallback: 0,
  validate: (value: unknown): value is number =>
    typeof value === "number" && Number.isFinite(value),
  migrate: (value: unknown, fromVersion: number) =>
    fromVersion === 1 && typeof value === "string" ? Number(value) : null,
});

test("unavailable, corrupted, and invalid storage safely return the fallback", () => {
  assert.equal(new StorageStore({}).read(countKey), 0);
  const local = new MemoryStorage();
  const store = new StorageStore({ local });
  local.setItem(physicalStorageKey(countKey), "not-json");
  assert.equal(store.read(countKey), 0);
  local.setItem(
    physicalStorageKey(countKey),
    JSON.stringify({ version: 2, value: "wrong", writtenAt: 1 }),
  );
  assert.equal(store.read(countKey), 0);
});

test("old schemas migrate and are rewritten at the current version", () => {
  const local = new MemoryStorage();
  const store = new StorageStore({ local });
  local.setItem(
    physicalStorageKey(countKey),
    JSON.stringify({ version: 1, value: "7", writtenAt: 1 }),
  );
  assert.equal(store.read(countKey), 7);
  assert.equal(
    JSON.parse(local.getItem(physicalStorageKey(countKey))!).version,
    2,
  );
});

test("quota failures never escape and do not replace the current value", () => {
  const local = new MemoryStorage();
  const store = new StorageStore({
    local: {
      ...local,
      get length() {
        return local.length;
      },
      getItem: (key) => local.getItem(key),
      removeItem: (key) => local.removeItem(key),
      key: (index) => local.key(index),
      setItem: () => {
        throw Object.assign(new Error("full"), { name: "QuotaExceededError" });
      },
    },
  });
  assert.equal(store.write(countKey, 3), false);
  assert.equal(store.read(countKey), 0);
});

test("local and session values with the same logical name stay isolated", () => {
  const local = new MemoryStorage();
  const session = new MemoryStorage();
  const store = new StorageStore({ local, session });
  const sessionKey = defineStorageKey({
    ...countKey,
    scope: "session" as const,
  });
  assert.equal(store.write(countKey, 2), true);
  assert.equal(store.write(sessionKey, 9), true);
  assert.equal(store.read(countKey), 2);
  assert.equal(store.read(sessionKey), 9);
});

test("cross-tab storage events notify only matching typed keys", () => {
  const local = new MemoryStorage();
  const events = new MemoryEvents();
  const store = new StorageStore({ local }, events);
  const values: number[] = [];
  const unsubscribe = store.subscribe(countKey, (value) => values.push(value));
  events.dispatch({ key: "unrelated", newValue: "{}", storageArea: local });
  events.dispatch({
    key: physicalStorageKey(countKey),
    newValue: encodeStorageValue(countKey, 11, 1),
    storageArea: local,
  });
  events.dispatch({
    key: physicalStorageKey(countKey),
    newValue: null,
    storageArea: local,
  });
  unsubscribe();
  assert.deepEqual(values, [11, 0]);
  assert.equal(events.listeners.size, 0);
});

test("prefix cleanup removes only the requested application namespace", () => {
  const local = new MemoryStorage();
  const store = new StorageStore({ local });
  const otherKey = defineStorageKey({ ...countKey, name: "other.value" });
  store.write(countKey, 1);
  store.write(otherKey, 2);
  local.setItem("third-party", "keep");
  assert.equal(store.clearNamespace("local", "tests."), 1);
  assert.equal(store.read(countKey), 0);
  assert.equal(store.read(otherKey), 2);
  assert.equal(local.getItem("third-party"), "keep");
});
