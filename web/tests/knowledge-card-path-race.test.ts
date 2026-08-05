import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import type { KnowledgeCardMutationResult, KnowledgeCardView } from "../lib/knowledge-card-api";
import { createPathEpoch, type PathSnapshot } from "../components/learning/pathGuard";
import {
  initialKnowledgeCardState,
  knowledgeCardReducer,
  type KnowledgeCardAction,
  type KnowledgeCardState,
} from "../components/learning/knowledgeCardReducer";

/**
 * UI-02 round-1 cross-path async race.
 *
 * ``useKnowledgeCards`` guards every dispatch that originates from async work
 * with a per-render epoch snapshot (see ``pathGuard``). These tests drive the
 * real epoch guard + real reducer deterministically: a publish/reconcile that
 * starts on path A and resolves after the learner has navigated to path B must
 * not overwrite path B's cards, errors or busy keys.
 */

function card(id: string, status = "draft", kpId = "kp1"): KnowledgeCardView {
  return {
    card_id: id,
    knowledge_point_id: kpId,
    status,
    revision: 1,
    version: 0,
    generation_locked_by_user_edit: false,
    draft_generation_status: "queued",
    title: "",
    body: "",
    content_hash: "h",
    source_snapshot_ids: [],
    evidence_ids: [],
    artifact_ids: [],
    source_count: 0,
    evidence_count: 0,
    artifact_count: 0,
    stable_assessment_id: "ra1",
    stable_assessment_sequence: 1,
    target_kb_name: null,
    document_rel_path: null,
    document_sha256: null,
    publication_key: null,
    quarantine_rel_path: null,
    retraction_request_id: null,
    retraction_operation_id: null,
    cleanup_status: "",
    cleanup_error: null,
    confirmed_at: null,
    published_at: null,
    stale_at: null,
    retracted_at: null,
    error_code: null,
    sanitized_error: null,
    latest_generation_attempt: null,
    model_identity: null,
    sources: [],
    artifacts: [],
    occupies_slot: true,
  };
}

function publishedResult(cardId: string): KnowledgeCardMutationResult {
  return {
    card_id: cardId,
    status: "published",
    replayed: false,
    revision: 2,
    target_kb_name: "我的学习知识库",
    document_rel_path: `learning_cards/${cardId}-v2.md`,
    document_sha256: "sha",
    publication_key: `key-${cardId}`,
    quarantine_rel_path: null,
    retraction_request_id: null,
    retraction_operation_id: null,
    confirmed_at: null,
    published_at: 123,
    retracted_at: null,
    cleanup_status: "",
    cleanup_error: null,
    error_code: null,
    sanitized_error: null,
  };
}

/** Mirrors the hook's ``mutate`` guarded dispatch: drop the action when the
 *  snapshot is stale, apply it otherwise. */
function guarded(
  epoch: ReturnType<typeof createPathEpoch>,
  snapshot: PathSnapshot,
  state: KnowledgeCardState,
  action: KnowledgeCardAction,
): KnowledgeCardState {
  return epoch.isCurrent(snapshot) ? knowledgeCardReducer(state, action) : state;
}

/** Drive a full load: RESET_FOR_PATH -> CARDS_LOADING -> CARDS_LOADED. */
function loadCards(state: KnowledgeCardState, cards: KnowledgeCardView[]): KnowledgeCardState {
  let next = knowledgeCardReducer(state, { type: "RESET_FOR_PATH" });
  next = knowledgeCardReducer(next, { type: "CARDS_LOADING" });
  return knowledgeCardReducer(next, { type: "CARDS_LOADED", cards });
}

/* ── epoch guard semantics ─────────────────────────────────────────────── */

test("createPathEpoch bumps the epoch on path change and rejects stale snapshots", () => {
  const epoch = createPathEpoch();
  epoch.set("path-A");
  const onA = epoch.snapshot();
  assert.equal(onA.pathId, "path-A");
  assert.equal(onA.epoch, 1);
  assert.equal(epoch.isCurrent(onA), true);

  epoch.set("path-B");
  assert.equal(epoch.pathIdOf(), "path-B");
  assert.equal(epoch.isCurrent(onA), false);
  assert.equal(epoch.isCurrent(epoch.snapshot()), true);
});

test("createPathEpoch is idempotent when the path does not change", () => {
  const epoch = createPathEpoch();
  epoch.set("path-A");
  const snap = epoch.snapshot();
  epoch.set("path-A"); // same render path — no epoch bump
  assert.equal(epoch.isCurrent(snap), true);
});

/* ── RESET_FOR_PATH clears old-path transient state ────────────────────── */

test("RESET_FOR_PATH clears cards, busy keys, editors, dialog and errors", () => {
  let state = loadCards(initialKnowledgeCardState, [card("cA", "draft")]);
  state = knowledgeCardReducer(state, { type: "OPEN_EDITOR", cardId: "cA" });
  state = knowledgeCardReducer(state, { type: "MUTATION_START", key: "publish:cA" });
  state = knowledgeCardReducer(state, {
    type: "MUTATION_FAILED",
    key: "publish:cA",
    error: { kind: "recoverable", status: 409, message: "card_version_conflict" },
  });
  state = knowledgeCardReducer(state, {
    type: "CONFIRM_OPEN",
    confirm: { kind: "publish", cardId: "cA", targetKbName: "kb" },
  });
  state = knowledgeCardReducer(state, {
    type: "CARDS_LOAD_FAILED",
    error: { kind: "fatal", message: "boom" },
  });

  const next = knowledgeCardReducer(state, { type: "RESET_FOR_PATH" });
  assert.equal(next.cards.length, 0);
  assert.deepEqual(next.busy, {});
  assert.equal(next.editorOpen, false);
  assert.equal(next.selectedCardId, null);
  assert.equal(next.confirm, null);
  assert.equal(next.recoverableError, null);
  assert.equal(next.mutationError, null);
  assert.equal(next.fatalError, null);
});

/* ── path A -> path B while a publish mutation is in flight ────────────── */

test("publish started on A cannot overwrite path B cards/busy after navigation", () => {
  const epoch = createPathEpoch();
  epoch.set("path-A");
  const publishOnA = epoch.snapshot();

  // Path A: draft card cA loaded, user starts a publish mutation (busy set).
  let state = loadCards(initialKnowledgeCardState, [card("cA", "draft", "kp-a")]);
  state = knowledgeCardReducer(state, { type: "MUTATION_START", key: "publish:cA" });
  assert.equal(state.busy["publish:cA"], true);

  // Navigate to path B: the reducer resets transient state and loads B's cards.
  epoch.set("path-B");
  state = loadCards(state, [card("cB", "draft", "kp-b")]);
  assert.equal(state.busy["publish:cA"], undefined);
  assert.deepEqual(state.cards.map((c) => c.card_id), ["cB"]);

  // A's publish resolves: merge, MUTATION_END and post-mutation refresh are all
  // dropped because they carry the stale path-A snapshot.
  const merge = publishedResult("cA");
  let after = guarded(epoch, publishOnA, state, { type: "CARD_MUTATION_MERGE", cardId: "cA", result: merge });
  after = guarded(epoch, publishOnA, after, { type: "MUTATION_END", key: "publish:cA" });
  after = guarded(epoch, publishOnA, after, { type: "CARDS_LOADED", cards: [card("cA", "published", "kp-a")] });

  // Path B is completely untouched: cards, busy, no error, no stray card.
  assert.deepEqual(after.cards.map((c) => c.card_id), ["cB"]);
  assert.equal(after.cards.find((c) => c.card_id === "cB")?.status, "draft");
  assert.deepEqual(after.busy, {});
  assert.equal(after.recoverableError, null);
  assert.equal(after.mutationError, null);
  assert.equal(after.status, "ready");
});

test("publish that completes on the SAME path still applies (guard is not over-blocking)", () => {
  const epoch = createPathEpoch();
  epoch.set("path-A");
  const publishOnA = epoch.snapshot();

  let state = loadCards(initialKnowledgeCardState, [card("cA", "draft", "kp-a")]);
  state = knowledgeCardReducer(state, { type: "MUTATION_START", key: "publish:cA" });

  // No navigation: the snapshot is still current, so the merge applies.
  const merge = publishedResult("cA");
  state = guarded(epoch, publishOnA, state, { type: "CARD_MUTATION_MERGE", cardId: "cA", result: merge });
  state = guarded(epoch, publishOnA, state, { type: "MUTATION_END", key: "publish:cA" });
  assert.equal(state.cards.find((c) => c.card_id === "cA")?.status, "published");
  // The same-path completion terminates its own busy key normally.
  assert.equal(state.busy["publish:cA"], false);
});

/* ── path A -> path B while a reconcile/refresh is in flight ───────────── */

test("reconcile started on A cannot overwrite path B cards or busy after navigation", () => {
  const epoch = createPathEpoch();
  epoch.set("path-A");
  const reconcileOnA = epoch.snapshot();

  // Path A: a reconcile_required card, reconcile mutation in flight.
  let state = loadCards(initialKnowledgeCardState, [
    card("cA-reconcile", "reconcile_required", "kp-a"),
  ]);
  state = knowledgeCardReducer(state, { type: "MUTATION_START", key: "reconcile-pub:cA-reconcile" });
  assert.equal(state.busy["reconcile-pub:cA-reconcile"], true);

  // Navigate to path B and load B's cards.
  epoch.set("path-B");
  state = loadCards(state, [card("cB", "published", "kp-b")]);
  assert.equal(state.busy["reconcile-pub:cA-reconcile"], undefined);

  // A's reconcile resolves with a published projection; merge + refresh dropped.
  const merge = publishedResult("cA-reconcile");
  let after = guarded(epoch, reconcileOnA, state, { type: "CARD_MUTATION_MERGE", cardId: "cA-reconcile", result: merge });
  after = guarded(epoch, reconcileOnA, after, { type: "MUTATION_END", key: "reconcile-pub:cA-reconcile" });
  after = guarded(epoch, reconcileOnA, after, { type: "CARDS_LOADED", cards: [card("cA-reconcile", "published", "kp-a")] });
  after = guarded(epoch, reconcileOnA, after, {
    type: "CARDS_LOAD_FAILED",
    error: { kind: "fatal", message: "old path refresh failed" },
  });

  // Path B is untouched — the old refresh cannot even set an error.
  assert.deepEqual(after.cards.map((c) => c.card_id), ["cB"]);
  assert.equal(after.cards.find((c) => c.card_id === "cB")?.status, "published");
  assert.deepEqual(after.busy, {});
  assert.equal(after.recoverableError, null);
  assert.equal(after.fatalError, null);
});

/* ── stale invocation of a mutation closure after navigation ───────────── */

test("a stale mutation closure fired after navigation cannot set a busy key on the new path", () => {
  const epoch = createPathEpoch();
  epoch.set("path-A");
  const snapshotOnA = epoch.snapshot();

  // Switch to B first — the closure was created for path A but fires now.
  epoch.set("path-B");
  let state = loadCards(initialKnowledgeCardState, [card("cB", "draft", "kp-b")]);

  // The hook rejects the mutation before MUTATION_START when the intended path
  // no longer matches the active path.
  const intendedPathA = "path-A";
  const current = epoch.snapshot();
  const accepted = intendedPathA === current.pathId && epoch.isCurrent(snapshotOnA);
  assert.equal(accepted, false);

  if (accepted) {
    state = knowledgeCardReducer(state, { type: "MUTATION_START", key: "publish:stale" });
  }
  assert.deepEqual(state.busy, {});
  assert.deepEqual(state.cards.map((c) => c.card_id), ["cB"]);
});

/* ── epoch sync happens at commit, not only in a passive effect ─────────── */

test("epoch sync is a commit-phase layout effect, not only a passive effect", () => {
  const sourcePath = path.join(
    process.cwd(),
    "components",
    "learning",
    "useKnowledgeCards.ts",
  );
  const source = fs.readFileSync(sourcePath, "utf8");

  // The guard must be advanced at commit via an isomorphic layout effect. The
  // module still imports React's layout effect so the browser bundle resolves
  // the binding to the commit-phase effect (SSR resolves it to useEffect).
  assert.match(
    source,
    /\buseLayoutEffect\b/,
    "useKnowledgeCards must import useLayoutEffect for commit-time epoch sync",
  );
  assert.match(
    source,
    /const\s+useCommitLayoutEffect\s*=\s*typeof\s+window\s*===\s*"undefined"\s*\?\s*useEffect\s*:\s*useLayoutEffect/,
    "useCommitLayoutEffect must resolve to useLayoutEffect in the browser and useEffect on the server",
  );

  // The epoch must be advanced through the commit/layout-effect binding, never
  // through a bare passive useEffect. A passive-effect sync leaves the guard on
  // the old path until after paint, so an old path's promise that resolves in
  // the commit→passive-effects window would still see its snapshot as current
  // and dispatch into the new path's UI.
  assert.match(
    source,
    /useCommitLayoutEffect\(\s*\(\s*\)\s*=>\s*\{\s*pathEpoch\.set\(\s*pathId\s*\)\s*;?\s*[,}]/,
    "pathEpoch.set(pathId) must run in the commit-phase layout effect",
  );
  assert.doesNotMatch(
    source,
    /useEffect\(\s*\(\s*\)\s*=>\s*\{\s*pathEpoch\.set\(\s*pathId\s*\)/,
    "epoch sync must not rely on a passive useEffect",
  );
});
