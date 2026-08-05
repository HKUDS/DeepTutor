import test from "node:test";
import assert from "node:assert/strict";
import {
  FEYNMAN_HANDOFF_STORAGE_PREFIX,
  FEYNMAN_HANDOFF_TTL_MS,
  FEYNMAN_HANDOFF_VERSION,
  consumeFeynmanHandoff,
  feynmanHandoffKey,
  parseFeynmanHandoff,
  writeFeynmanHandoff,
  type FeynmanHandoff,
  type StorageLike,
} from "../lib/feynman-learning-handoff";

/** In-memory Storage shim for Node tests. */
class MemoryStorage implements StorageLike {
  private map = new Map<string, string>();

  getItem(key: string): string | null {
    return this.map.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.map.set(key, value);
  }

  removeItem(key: string): void {
    this.map.delete(key);
  }

  keys(): string[] {
    return [...this.map.keys()];
  }
}

const NOW = 1_000_000_000_000;

function roundtrip(now = NOW): { storage: MemoryStorage; handoff: FeynmanHandoff } {
  const storage = new MemoryStorage();
  writeFeynmanHandoff(storage, "path-001", "text", " 我的讲解 ", now);
  const handoff = consumeFeynmanHandoff(storage, "path-001", now);
  assert.ok(handoff, "valid handoff is consumed");
  return { storage, handoff };
}

/* ── Roundtrip + single consumption ───────────────────────────────────── */

test("write + consume returns the draft and clears the slot", () => {
  const { storage, handoff } = roundtrip();
  assert.equal(handoff.draft, "我的讲解");
  assert.equal(handoff.pathId, "path-001");
  assert.equal(handoff.kind, "text");
  assert.equal(handoff.version, FEYNMAN_HANDOFF_VERSION);
  assert.equal(storage.getItem(feynmanHandoffKey("path-001")), null);
});

test("consume is single-shot: a second consume returns null", () => {
  const storage = new MemoryStorage();
  writeFeynmanHandoff(storage, "path-001", "text", "once", NOW);
  assert.ok(consumeFeynmanHandoff(storage, "path-001", NOW));
  assert.equal(consumeFeynmanHandoff(storage, "path-001", NOW), null);
});

test("each path owns its own slot", () => {
  const storage = new MemoryStorage();
  writeFeynmanHandoff(storage, "path-001", "text", "A", NOW);
  writeFeynmanHandoff(storage, "path-002", "help", "B", NOW);
  assert.equal(consumeFeynmanHandoff(storage, "path-002", NOW)?.draft, "B");
  // Consuming path-002 must not disturb path-001.
  assert.ok(storage.getItem(feynmanHandoffKey("path-001")));
  assert.equal(consumeFeynmanHandoff(storage, "path-001", NOW)?.draft, "A");
  assert.equal(storage.getItem(feynmanHandoffKey("path-001")), null);
});

test("empty draft is never written", () => {
  const storage = new MemoryStorage();
  writeFeynmanHandoff(storage, "path-001", "text", "   ", NOW);
  assert.equal(storage.getItem(feynmanHandoffKey("path-001")), null);
  assert.equal(consumeFeynmanHandoff(storage, "path-001", NOW), null);
});

/* ── Malformed / wrong-session / unsupported-version ──────────────────── */

function rawWith(overrides: Partial<FeynmanHandoff>): string {
  const base: FeynmanHandoff = {
    version: FEYNMAN_HANDOFF_VERSION,
    pathId: "path-001",
    kind: "text",
    draft: "draft",
    createdAt: NOW,
  };
  return JSON.stringify({ ...base, ...overrides });
}

test("malformed JSON is discarded and the slot is removed", () => {
  const storage = new MemoryStorage();
  storage.setItem(feynmanHandoffKey("path-001"), "{not-json");
  assert.equal(consumeFeynmanHandoff(storage, "path-001", NOW), null);
  assert.equal(storage.getItem(feynmanHandoffKey("path-001")), null);
});

test("wrong-session handoff is discarded", () => {
  const storage = new MemoryStorage();
  storage.setItem(feynmanHandoffKey("path-001"), rawWith({ pathId: "path-002" }));
  assert.equal(consumeFeynmanHandoff(storage, "path-001", NOW), null);
  assert.equal(storage.getItem(feynmanHandoffKey("path-001")), null);
});

test("unsupported-version handoff is discarded", () => {
  const storage = new MemoryStorage();
  storage.setItem(
    feynmanHandoffKey("path-001"),
    rawWith({ version: FEYNMAN_HANDOFF_VERSION + 1 }),
  );
  assert.equal(consumeFeynmanHandoff(storage, "path-001", NOW), null);
  assert.equal(storage.getItem(feynmanHandoffKey("path-001")), null);
});

test("unknown kind is discarded", () => {
  const storage = new MemoryStorage();
  storage.setItem(
    feynmanHandoffKey("path-001"),
    rawWith({ kind: "evidence" as FeynmanHandoff["kind"] }),
  );
  assert.equal(consumeFeynmanHandoff(storage, "path-001", NOW), null);
});

test("non-object payload is discarded", () => {
  const storage = new MemoryStorage();
  storage.setItem(feynmanHandoffKey("path-001"), JSON.stringify("text"));
  assert.equal(parseFeynmanHandoff(storage.getItem(feynmanHandoffKey("path-001")), "path-001", NOW), null);
});

/* ── Expiry / clock ───────────────────────────────────────────────────── */

test("expired handoff is discarded and the slot is removed", () => {
  const storage = new MemoryStorage();
  writeFeynmanHandoff(storage, "path-001", "text", "old", NOW);
  assert.equal(
    consumeFeynmanHandoff(storage, "path-001", NOW + FEYNMAN_HANDOFF_TTL_MS + 1),
    null,
  );
  assert.equal(storage.getItem(feynmanHandoffKey("path-001")), null);
});

test("a future-dated (clock-skewed) handoff is discarded", () => {
  const storage = new MemoryStorage();
  writeFeynmanHandoff(storage, "path-001", "text", "future", NOW);
  assert.equal(consumeFeynmanHandoff(storage, "path-001", NOW - 1), null);
});

test("a fresh handoff survives exactly up to the TTL boundary", () => {
  const storage = new MemoryStorage();
  writeFeynmanHandoff(storage, "path-001", "text", "fresh", NOW);
  assert.ok(
    consumeFeynmanHandoff(storage, "path-001", NOW + FEYNMAN_HANDOFF_TTL_MS),
  );
});

/* ── Parse-level validation ───────────────────────────────────────────── */

test("parseFeynmanHandoff accepts the three source kinds", () => {
  for (const kind of ["text", "voice_transcript", "help"] as const) {
    const storage = new MemoryStorage();
    writeFeynmanHandoff(storage, "path-001", kind, "draft", NOW);
    assert.equal(consumeFeynmanHandoff(storage, "path-001", NOW)?.kind, kind);
  }
});

test("key is scoped by the storage prefix", () => {
  assert.ok(feynmanHandoffKey("path-001").startsWith(FEYNMAN_HANDOFF_STORAGE_PREFIX));
  assert.notEqual(feynmanHandoffKey("path-001"), feynmanHandoffKey("path-002"));
});
