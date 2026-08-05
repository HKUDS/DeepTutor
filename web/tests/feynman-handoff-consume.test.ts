import test from "node:test";
import assert from "node:assert/strict";
import {
  feynmanHandoffKey,
  writeFeynmanHandoff,
  type FeynmanHandoff,
  type StorageLike,
} from "../lib/feynman-learning-handoff";
import {
  createFeynmanHandoffConsumer,
  type FeynmanHandoffConsumeCallbacks,
  type FeynmanHandoffConsumer,
} from "../lib/feynman-handoff-consume";

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

  has(key: string): boolean {
    return this.map.has(key);
  }
}

const NOW = 1_000_000_000_000;

interface SchedulerEntry {
  cancelled: boolean;
  ran: boolean;
  fn: () => void;
}

/**
 * Deterministic in-test scheduler. `flush()` runs exactly the retries that are
 * currently pending — the analogue of the browser advancing one 50ms tick — so
 * the unit regression never depends on real time. A retry scheduled while a
 * flush is running waits for the next flush.
 */
function makeScheduler() {
  const queue: SchedulerEntry[] = [];
  return {
    schedule: (fn: () => void) => {
      const entry: SchedulerEntry = { cancelled: false, ran: false, fn };
      queue.push(entry);
      return entry;
    },
    cancelSchedule: (handle: unknown) => {
      (handle as SchedulerEntry).cancelled = true;
    },
    flush: () => {
      const due = queue.filter((e) => !e.cancelled && !e.ran);
      for (const entry of due) {
        entry.ran = true;
        entry.fn();
      }
    },
    pendingCount: () => queue.filter((e) => !e.cancelled && !e.ran).length,
    /** The most recently scheduled entry — lets a test fire an orphaned retry
     *  out of band, simulating a timer already queued when the effect cleanup
     *  ran. */
    lastScheduled: () => queue[queue.length - 1],
    /** Fire a specific retry callback directly, bypassing cancellation — the
     *  "timer fires before cleanup" worst case. */
    fireLate: (entry: SchedulerEntry) => {
      entry.ran = true;
      entry.fn();
    },
  };
}

interface Harness {
  storage: MemoryStorage;
  consumer: FeynmanHandoffConsumer;
  scheduler: ReturnType<typeof makeScheduler>;
  ready: boolean;
  published: FeynmanHandoff[];
}

function makeHarness(
  callbacks: Partial<FeynmanHandoffConsumeCallbacks> = {},
): Harness {
  const storage = new MemoryStorage();
  const scheduler = makeScheduler();
  const harness: Harness = {
    storage,
    consumer: null as unknown as FeynmanHandoffConsumer,
    scheduler,
    ready: false,
    published: [],
  };
  harness.consumer = createFeynmanHandoffConsumer(
    storage,
    {
      composerReady: () => harness.ready,
      onHandoff: (handoff) => {
        harness.published.push(handoff);
      },
      ...callbacks,
    },
    {
      schedule: scheduler.schedule,
      cancelSchedule: scheduler.cancelSchedule,
      now: () => NOW,
    },
  );
  return harness;
}

interface ChatPageHarness {
  storage: MemoryStorage;
  scheduler: ReturnType<typeof makeScheduler>;
  ready: boolean;
  published: FeynmanHandoff[];
  /** The shared active-session marker, owned by the layout-phase lifecycle. */
  activePath: { current: string | null };
  /** The path already consumed on this page instance (the effect's exactly-once guard). */
  consumedFor: string | null;
}

/**
 * Harness that models the exact integration ChatPage uses (UI-01): the active-
 * session marker is owned by a layout-phase lifecycle keyed on the route param,
 * and every handoff effect run creates a FRESH consumer bound to the callbacks
 * that render supplied at that moment. A route change commits the next session's
 * layout phase (flipping the marker) BEFORE the previous effect's passive
 * cleanup runs `cancel()`, and that is precisely the window these tests exercise.
 */
function makeChatPageHarness(): ChatPageHarness {
  const storage = new MemoryStorage();
  const scheduler = makeScheduler();
  return {
    storage,
    scheduler,
    ready: false,
    published: [],
    activePath: { current: null },
    consumedFor: null,
  };
}

/**
 * Simulate the layout-phase lifecycle (ChatPage's useLayoutEffect keyed on
 * `sessionIdParam`): when the route changes from A to B, A's layout cleanup
 * invalidates the marker and B's layout setup marks B — both synchronously
 * during commit, before any passive-effect cleanup or browser timer can run.
 * `layoutPhase` captures the marker's state once that commit finishes, which is
 * the only state any timer can observe.
 */
function layoutPhase(h: ChatPageHarness, sid: string | null) {
  h.activePath.current = sid;
}

/**
 * Simulate one handoff effect run: a FRESH consumer bound to the callback the
 * render supplied at that moment, started for `sid`. Production creates the
 * consumer inside the effect, so a re-run (e.g. `handleSelectCapability` changed
 * identity after capability settings / user tool toggles loaded) never reuses a
 * callback captured by an earlier run. Returns the consumer (or null when the
 * exactly-once guard already consumed this session) so a test can cancel it the
 * way the effect cleanup does.
 */
function startEffectRun(
  h: ChatPageHarness,
  sid: string,
  onHandoff: (handoff: FeynmanHandoff) => void,
): FeynmanHandoffConsumer | null {
  if (h.consumedFor === sid) return null;
  const consumer = createFeynmanHandoffConsumer(
    h.storage,
    {
      composerReady: () => h.ready,
      isActive: (pathId) => h.activePath.current === pathId,
      onHandoff: (handoff) => {
        if (h.activePath.current !== handoff.pathId) return;
        h.consumedFor = handoff.pathId;
        onHandoff(handoff);
      },
    },
    {
      schedule: h.scheduler.schedule,
      cancelSchedule: h.scheduler.cancelSchedule,
      now: () => NOW,
    },
  );
  consumer.start(sid);
  return consumer;
}

function writeFor(storage: MemoryStorage, pathId: string, draft: string) {
  writeFeynmanHandoff(storage, pathId, "text", draft, NOW);
}

/* ── Normal single-session consumption ────────────────────────────────── */

test("consumes once the composer bridge is published", () => {
  const h = makeHarness();
  writeFor(h.storage, "path-001", "A-draft");
  const session = h.consumer.start("path-001");
  // Composer not ready yet → retry scheduled, slot still present.
  assert.equal(session.consumed, false);
  assert.equal(h.scheduler.pendingCount(), 1);
  assert.ok(h.storage.has(feynmanHandoffKey("path-001")));

  // Bridge publishes → the pending retry consumes exactly once.
  h.ready = true;
  h.scheduler.flush();
  assert.equal(session.consumed, true);
  assert.equal(h.published.length, 1);
  assert.equal(h.published[0].draft, "A-draft");
  assert.equal(h.storage.has(feynmanHandoffKey("path-001")), false);
  assert.equal(h.scheduler.pendingCount(), 0);
});

test("a session with no handoff consumes nothing", () => {
  const h = makeHarness();
  h.ready = true;
  const session = h.consumer.start("path-001");
  assert.equal(session.consumed, false);
  assert.equal(h.published.length, 0);
});

/* ── Cancellation / effect cleanup ────────────────────────────────────── */

test("cancel() invalidates a pending retry: nothing is ever consumed", () => {
  const h = makeHarness();
  writeFor(h.storage, "path-001", "A-draft");
  const session = h.consumer.start("path-001");
  assert.equal(h.scheduler.pendingCount(), 1);

  // Effect cleanup (unmount / session switch) cancels the consumer.
  h.consumer.cancel();
  assert.equal(session.cancelled, true);
  assert.equal(h.scheduler.pendingCount(), 0);

  // Even if the bridge publishes afterwards, the superseded session is inert.
  h.ready = true;
  h.scheduler.flush();
  assert.equal(session.consumed, false);
  assert.equal(h.published.length, 0);
  // And the slot is untouched — a later visit can still consume it.
  assert.ok(h.storage.has(feynmanHandoffKey("path-001")));
});

test("giving up on the retry cap leaves the slot for a later visit", () => {
  const h = makeHarness();
  writeFor(h.storage, "path-001", "A-draft");
  const consumer = createFeynmanHandoffConsumer(
    h.storage,
    {
      composerReady: () => false,
      onHandoff: () => {},
    },
    {
      schedule: h.scheduler.schedule,
      cancelSchedule: h.scheduler.cancelSchedule,
      now: () => NOW,
      maxAttempts: 2,
    },
  );
  const session = consumer.start("path-001");
  assert.equal(session.consumed, false);
  // The immediate attempt found no bridge, so one retry is pending.
  assert.equal(h.scheduler.pendingCount(), 1);
  // First retry still finds no bridge → schedules the final retry.
  h.scheduler.flush();
  assert.equal(h.scheduler.pendingCount(), 1);
  // Final retry gives up (maxAttempts exhausted).
  h.scheduler.flush();
  assert.equal(session.consumed, false);
  assert.equal(h.published.length, 0);
  assert.equal(h.scheduler.pendingCount(), 0);
  assert.ok(h.storage.has(feynmanHandoffKey("path-001")));
});

/* ── UI-01 regression: rapid /home/A → /home/B while A is still waiting ── */

test("a superseded session A can never consume or prefill into session B", () => {
  const h = makeHarness();
  writeFor(h.storage, "path-A", "A-draft");
  writeFor(h.storage, "path-B", "B-draft");

  // /home/A starts waiting for its composer; the bridge is not yet published.
  const sessionA = h.consumer.start("path-A");
  assert.equal(sessionA.consumed, false);
  assert.equal(h.scheduler.pendingCount(), 1);

  // User navigates to /home/B before the composer publishes. The effect
  // cleanup cancels A's timer and the new session supersedes A entirely.
  const sessionB = h.consumer.start("path-B");
  assert.equal(sessionB.consumed, false);
  // A's pending retry was cancelled; only B's retry is live.
  assert.equal(h.scheduler.pendingCount(), 1);

  // B's composer bridge publishes.
  h.ready = true;
  h.scheduler.flush();

  // B consumed its own draft; A's draft was never prefilled anywhere.
  assert.equal(sessionB.consumed, true);
  assert.equal(sessionA.consumed, false);
  assert.deepEqual(
    h.published.map((p) => p.draft),
    ["B-draft"],
    "A must not leak its draft into B",
  );
  // A's slot is still present for a later visit — it was never consumed.
  assert.ok(h.storage.has(feynmanHandoffKey("path-A")));
  assert.equal(h.storage.has(feynmanHandoffKey("path-B")), false);
});

test("a late A retry that bypasses cancellation is still inert (generation guard)", () => {
  const h = makeHarness();
  writeFor(h.storage, "path-A", "A-draft");
  writeFor(h.storage, "path-B", "B-draft");

  // A starts waiting, then the user navigates to B. Grab A's orphaned retry
  // so we can fire it out of band even though B's start cancelled it — the
  // worst case of a timer already queued when the effect cleanup ran.
  h.consumer.start("path-A");
  const orphanedA = h.scheduler.lastScheduled();
  h.consumer.start("path-B");

  // B's bridge publishes; B's live retry consumes B's draft.
  h.ready = true;
  h.scheduler.flush();
  assert.equal(h.published.length, 1);

  // The orphaned A callback fires late. The generation guard makes it inert:
  // A must never consume its own slot or prefill into B.
  h.scheduler.fireLate(orphanedA);

  assert.deepEqual(
    h.published.map((p) => p.draft),
    ["B-draft"],
    "late A callback must be inert under the new session",
  );
  assert.equal(h.scheduler.pendingCount(), 0);
  assert.ok(h.storage.has(feynmanHandoffKey("path-A")));
});

/* ── UI-01 correction: ChatPage integration pattern ─────────────────────
 *
 * The generation counter above lives inside one consumer. Production creates a
 * FRESH consumer per handoff effect — so every start binds the current
 * handleSelectCapability/composer callbacks — and a route change commits the
 * next session's layout phase (flipping the shared active-session marker)
 * BEFORE the previous effect's passive cleanup runs `cancel()`. In that window
 * A's orphaned retry's own generation has not been bumped yet, so it can only
 * be stopped by the `isActive` guard reading the already-flipped marker. These
 * tests exercise exactly that ordering with separate per-effect A/B consumers
 * sharing the layout-owned route marker.
 * ──────────────────────────────────────────────────────────────────────── */

test("ChatPage pattern: a retry orphaned from A that fires after B's layout phase but before A's passive cleanup is inert", () => {
  const h = makeChatPageHarness();
  writeFor(h.storage, "path-A", "A-draft");
  writeFor(h.storage, "path-B", "B-draft");

  // First mount: /home/A's layout phase marks A, then the handoff effect starts
  // a fresh consumer for A. The composer bridge is not published yet, so A
  // schedules a retry.
  layoutPhase(h, "path-A");
  const consumerA = startEffectRun(h, "path-A", (handoff) => {
    h.published.push(handoff);
  });
  assert.ok(consumerA);
  assert.equal(h.scheduler.pendingCount(), 1);

  // User navigates to /home/B. B's layout phase invalidates A and marks B
  // synchronously during commit, BEFORE any passive-effect cleanup runs — A's
  // timer is still queued and B's composer bridge is already live. This is the
  // exact window a fresh per-effect consumer's generation counter cannot see.
  layoutPhase(h, "path-B");
  h.ready = true;
  const orphanedA = h.scheduler.lastScheduled();

  // A's orphaned retry fires in that window (still before A's passive cleanup).
  // The isActive guard reads the shared marker (now B) right before storage
  // consumption and makes it inert: A's slot stays, nothing is published into B.
  h.scheduler.fireLate(orphanedA);
  assert.equal(h.published.length, 0, "A must never prefill into B");
  assert.ok(h.storage.has(feynmanHandoffKey("path-A")), "A's slot must stay");

  // A's passive-effect cleanup runs, then the new effect run creates a FRESH
  // consumer for B. B consumes its own draft exactly once.
  consumerA?.cancel();
  startEffectRun(h, "path-B", (handoff) => {
    h.published.push(handoff);
  });
  h.scheduler.flush();
  assert.equal(h.published.length, 1);
  assert.equal(h.published[0].draft, "B-draft");
  assert.equal(h.storage.has(feynmanHandoffKey("path-B")), false);
});

test("ChatPage pattern: a retry that loses the race after B's layout phase stops without touching storage", () => {
  const h = makeChatPageHarness();
  writeFor(h.storage, "path-A", "A-draft");
  writeFor(h.storage, "path-B", "B-draft");

  layoutPhase(h, "path-A");
  const consumerA = startEffectRun(h, "path-A", (handoff) => {
    h.published.push(handoff);
  });
  assert.ok(consumerA);
  assert.equal(h.scheduler.pendingCount(), 1);

  // B's layout phase commits; the composer bridge is still not ready, so A's
  // next retry is just a wait — but the marker has already moved to B.
  layoutPhase(h, "path-B");
  h.scheduler.flush();
  // isActive("path-A") is now false: A's attempt returns without re-scheduling,
  // so the pending queue is empty even though the composer never published.
  assert.equal(h.scheduler.pendingCount(), 0);
  assert.equal(h.published.length, 0);
  assert.ok(h.storage.has(feynmanHandoffKey("path-A")));

  // A's passive cleanup runs, then B's fresh effect run consumes its own draft.
  consumerA?.cancel();
  h.ready = true;
  startEffectRun(h, "path-B", (handoff) => {
    h.published.push(handoff);
  });
  h.scheduler.flush();
  assert.equal(h.published.length, 1);
  assert.equal(h.published[0].draft, "B-draft");
});

test("ChatPage pattern: returning to a session re-arms consumption on a fresh effect consumer", () => {
  const h = makeChatPageHarness();
  writeFor(h.storage, "path-A", "A-draft");

  layoutPhase(h, "path-A");
  const consumerA = startEffectRun(h, "path-A", (handoff) => {
    h.published.push(handoff);
  });
  assert.ok(consumerA);
  assert.equal(h.scheduler.pendingCount(), 1);

  // Navigate away to B before A's composer ever publishes: A becomes inert and
  // its slot survives.
  layoutPhase(h, "path-B");
  h.ready = true;
  h.scheduler.flush();
  assert.equal(h.published.length, 0);
  assert.ok(h.storage.has(feynmanHandoffKey("path-A")));

  // A's passive cleanup runs, then B's fresh effect run arms (no handoff for B),
  // and the user comes back to /home/A: the layout marker flips back
  // synchronously and the new effect run re-arms, consuming the still-present
  // A slot with a fresh consumer.
  consumerA?.cancel();
  startEffectRun(h, "path-B", (handoff) => {
    h.published.push(handoff);
  });
  layoutPhase(h, "path-A");
  startEffectRun(h, "path-A", (handoff) => {
    h.published.push(handoff);
  });
  h.scheduler.flush();
  assert.equal(h.published.length, 1);
  assert.equal(h.published[0].draft, "A-draft");
  assert.equal(h.storage.has(feynmanHandoffKey("path-A")), false);
});

test("a later effect run hands off with the newly supplied callback, not the first run's capture", () => {
  const h = makeChatPageHarness();
  writeFor(h.storage, "path-001", "A-draft");

  const applied: string[] = [];
  layoutPhase(h, "path-001");
  // Effect run 1 — the render before capability settings / user tool toggles
  // finished loading. Its onHandoff closure captures that (stale) configuration.
  const consumer1 = startEffectRun(h, "path-001", (handoff) => {
    h.published.push(handoff);
    applied.push("run-1");
  });
  assert.ok(consumer1);
  assert.equal(h.scheduler.pendingCount(), 1);

  // Settings resolve → handleSelectCapability changes identity → the handoff
  // effect re-runs for the same session. The first run's cleanup cancels its
  // timer, and the re-run creates a FRESH consumer bound to the CURRENT
  // callback — it must never reuse the first effect's captured configuration.
  consumer1?.cancel();
  startEffectRun(h, "path-001", (handoff) => {
    h.published.push(handoff);
    applied.push("run-2");
  });

  // Composer publishes; only the second run's callback is applied.
  h.ready = true;
  h.scheduler.flush();
  assert.deepEqual(applied, ["run-2"], "the stale run-1 callback must never fire");
  assert.deepEqual(h.published.map((p) => p.draft), ["A-draft"]);
  assert.equal(h.storage.has(feynmanHandoffKey("path-001")), false);
});

test("consumption is exactly-once per session token", () => {
  const h = makeHarness();
  writeFor(h.storage, "path-001", "once");
  h.ready = true;
  h.consumer.start("path-001");
  h.scheduler.flush();
  assert.equal(h.published.length, 1);

  // A second start for the same path finds the slot already removed.
  h.consumer.start("path-001");
  assert.equal(h.published.length, 1);
  assert.equal(h.storage.has(feynmanHandoffKey("path-001")), false);
});

test("only the three contract kinds flow through the consumer unchanged", () => {
  for (const kind of ["text", "voice_transcript", "help"] as const) {
    const h = makeHarness();
    writeFeynmanHandoff(h.storage, "path-001", kind, "draft", NOW);
    h.ready = true;
    h.consumer.start("path-001");
    h.scheduler.flush();
    assert.equal(h.published.length, 1);
    assert.equal(h.published[0].kind, kind);
  }
});
