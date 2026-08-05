import test from "node:test";
import assert from "node:assert/strict";
import type { KnowledgeCardMutationResult, KnowledgeCardView } from "../lib/knowledge-card-api";
import {
  initialKnowledgeCardState,
  knowledgeCardReducer,
  selectedCard,
} from "../components/learning/knowledgeCardReducer";

function card(id: string, status = "draft"): KnowledgeCardView {
  return {
    card_id: id,
    knowledge_point_id: "kp1",
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

test("CARDS_LOADED stores the owner-scoped collection", () => {
  const s = knowledgeCardReducer(initialKnowledgeCardState, {
    type: "CARDS_LOADED",
    cards: [card("c1"), card("c2")],
  });
  assert.equal(s.status, "ready");
  assert.equal(s.cards.length, 2);
});

test("CARDS_LOAD_FAILED is fatal on non-recoverable errors", () => {
  const s = knowledgeCardReducer(initialKnowledgeCardState, {
    type: "CARDS_LOAD_FAILED",
    error: { kind: "fatal", message: "boom" },
  });
  assert.equal(s.status, "error");
  assert.equal(s.fatalError, "boom");
});

test("OPEN_EDITOR / CLOSE_EDITOR manage the desktop center editor", () => {
  let s = knowledgeCardReducer(initialKnowledgeCardState, { type: "OPEN_EDITOR", cardId: "c1" });
  assert.equal(s.editorOpen, true);
  assert.equal(s.selectedCardId, "c1");
  s = knowledgeCardReducer(s, { type: "CLOSE_EDITOR" });
  assert.equal(s.editorOpen, false);
});

test("OPEN_MOBILE_EDITOR / CLOSE_MOBILE_EDITOR manage the full-screen editor", () => {
  let s = knowledgeCardReducer(initialKnowledgeCardState, { type: "OPEN_MOBILE_EDITOR", cardId: "c1" });
  assert.equal(s.mobileEditorOpen, true);
  assert.equal(s.selectedCardId, "c1");
  s = knowledgeCardReducer(s, { type: "CLOSE_MOBILE_EDITOR" });
  assert.equal(s.mobileEditorOpen, false);
});

test("CARD_UPSERT replaces the card in the collection", () => {
  let s = knowledgeCardReducer(initialKnowledgeCardState, { type: "CARDS_LOADED", cards: [card("c1"), card("c2")] });
  s = knowledgeCardReducer(s, { type: "CARD_UPSERT", card: { ...card("c1"), revision: 2, status: "published" } });
  assert.equal(s.cards.find((c) => c.card_id === "c1")?.revision, 2);
  assert.equal(s.cards.length, 2);
});

test("CARD_MUTATION_MERGE folds a partial projection and keeps full fields", () => {
  const result: KnowledgeCardMutationResult = {
    card_id: "c1",
    status: "published",
    replayed: false,
    revision: 1,
    target_kb_name: "kb",
    document_rel_path: "learning_cards/c1-v1.md",
    document_sha256: "abc",
    publication_key: "key",
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
  let s = knowledgeCardReducer(initialKnowledgeCardState, {
    type: "CARDS_LOADED",
    cards: [card("c1", "draft")],
  });
  s = knowledgeCardReducer(s, {
    type: "CARD_MUTATION_MERGE",
    cardId: "c1",
    result,
  });
  const c = s.cards.find((x) => x.card_id === "c1");
  assert.equal(c?.status, "published");
  assert.equal(c?.knowledge_point_id, "kp1");
  assert.equal(c?.target_kb_name, "kb");
});

test("MUTATION_START/END guard repeated mutations", () => {
  let s = knowledgeCardReducer(initialKnowledgeCardState, { type: "MUTATION_START", key: "publish:c1" });
  assert.equal(s.busy["publish:c1"], true);
  s = knowledgeCardReducer(s, { type: "MUTATION_END", key: "publish:c1" });
  assert.equal(s.busy["publish:c1"], false);
});

test("recoverable MUTATION_FAILED sets recoverableError; fatal sets mutationError", () => {
  let s = knowledgeCardReducer(initialKnowledgeCardState, { type: "MUTATION_START", key: "edit:c1" });
  s = knowledgeCardReducer(s, {
    type: "MUTATION_FAILED",
    key: "edit:c1",
    error: { kind: "recoverable", status: 409, message: "card_version_conflict" },
  });
  assert.equal(s.recoverableError?.status, 409);
  assert.equal(s.mutationError, null);

  s = knowledgeCardReducer(initialKnowledgeCardState, { type: "MUTATION_START", key: "publish:c1" });
  s = knowledgeCardReducer(s, {
    type: "MUTATION_FAILED",
    key: "publish:c1",
    error: { kind: "fatal", status: 500, message: "network down" },
  });
  assert.equal(s.recoverableError, null);
  assert.equal(s.mutationError, "network down");
  s = knowledgeCardReducer(s, { type: "MUTATION_ERROR_CLEAR" });
  assert.equal(s.mutationError, null);
});

test("CONFIRM_OPEN / CONFIRM_CLOSE drive the explicit dialog", () => {
  let s = knowledgeCardReducer(initialKnowledgeCardState, {
    type: "CONFIRM_OPEN",
    confirm: { kind: "publish", cardId: "c1", targetKbName: "kb" },
  });
  assert.equal(s.confirm?.kind, "publish");
  assert.equal(s.confirm?.targetKbName, "kb");
  s = knowledgeCardReducer(s, { type: "CONFIRM_CLOSE" });
  assert.equal(s.confirm, null);
});

test("selectedCard resolves the selected card", () => {
  let s = knowledgeCardReducer(initialKnowledgeCardState, { type: "CARDS_LOADED", cards: [card("c1"), card("c2")] });
  s = knowledgeCardReducer(s, { type: "OPEN_EDITOR", cardId: "c2" });
  assert.equal(selectedCard(s)?.card_id, "c2");
  s = knowledgeCardReducer(s, { type: "CLOSE_EDITOR" });
  // Closing the editor keeps the selected card so the panel can continue.
  assert.equal(selectedCard(s)?.card_id, "c2");
});
