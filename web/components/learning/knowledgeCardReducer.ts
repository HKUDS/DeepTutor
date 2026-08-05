import type {
  KnowledgeCardView,
  KnowledgeCardMutationResult,
} from "@/lib/knowledge-card-api";
import type { KnowledgeBaseSummary } from "@/lib/knowledge-api";
import type { MediaArtifact } from "@/lib/media-types";
import type { ContractError } from "./contract";
import { classifyKbs, mergeMutationResult, type KbOption } from "./knowledgeCard";

/* ────────────────────────────────────────────────────────────────────────
 * Knowledge-card review/publication state (UI-02).
 *
 * Pure reducer so node tests exercise every transition: load, owner-scoped
 * card collection, KB classification, editor open/close (desktop center vs
 * mobile full-screen), post-mutation upsert/refresh, and the explicit
 * publish/retract/discard confirmation dialogs.
 * ──────────────────────────────────────────────────────────────────────── */

export interface CardConfirmation {
  kind: "publish" | "retract" | "discard";
  cardId: string;
  targetKbName?: string;
}

export interface KnowledgeCardState {
  status: "idle" | "loading" | "ready" | "error";
  cards: KnowledgeCardView[];
  kbs: KbOption[];
  artifacts: MediaArtifact[];
  selectedCardId: string | null;
  /** Desktop center-column editor (§13.5). */
  editorOpen: boolean;
  /** Mobile full-screen editor (§13.5, r9 390px). */
  mobileEditorOpen: boolean;
  busy: Record<string, boolean>;
  recoverableError: ContractError | null;
  /** Non-conflict mutation failure (e.g. network, 5xx) — inline, dismissable. */
  mutationError: string | null;
  fatalError: string | null;
  confirm: CardConfirmation | null;
  expandedIds: Record<string, boolean>;
}

export const initialKnowledgeCardState: KnowledgeCardState = {
  status: "idle",
  cards: [],
  kbs: [],
  artifacts: [],
  selectedCardId: null,
  editorOpen: false,
  mobileEditorOpen: false,
  busy: {},
  recoverableError: null,
  mutationError: null,
  fatalError: null,
  confirm: null,
  expandedIds: {},
};

export type KnowledgeCardAction =
  | { type: "CARDS_LOADING" }
  | { type: "CARDS_LOADED"; cards: KnowledgeCardView[] }
  | { type: "CARDS_LOAD_FAILED"; error: ContractError }
  | { type: "KBS_LOADED"; kbs: KbOption[] }
  | { type: "ARTIFACTS_LOADED"; artifacts: MediaArtifact[] }
  | { type: "SELECT_CARD"; cardId: string | null }
  | { type: "OPEN_EDITOR"; cardId: string }
  | { type: "CLOSE_EDITOR" }
  | { type: "OPEN_MOBILE_EDITOR"; cardId: string }
  | { type: "CLOSE_MOBILE_EDITOR" }
  | { type: "CARD_UPSERT"; card: KnowledgeCardView }
  | { type: "CARD_MUTATION_MERGE"; cardId: string; result: KnowledgeCardMutationResult }
  | { type: "MUTATION_START"; key: string }
  | { type: "MUTATION_END"; key: string }
  | { type: "MUTATION_FAILED"; key: string; error: ContractError }
  | { type: "MUTATION_ERROR_CLEAR" }
  | { type: "CONFIRM_OPEN"; confirm: CardConfirmation }
  | { type: "CONFIRM_CLOSE" }
  | { type: "RECOVER" }
  | { type: "TOGGLE_EXPANDED"; id: string }
  /**
   * A new learning path became active. Transient state scoped to the previous
   * path (card collection, selected card, editors, confirmation dialog, busy
   * keys, errors) is cleared so an old path's in-flight work can never leak
   * into the new path. KB options and artifacts are user/global supplements and
   * are intentionally retained until the new path's load refreshes them.
   */
  | { type: "RESET_FOR_PATH" };

function upsertCard(cards: KnowledgeCardView[], card: KnowledgeCardView): KnowledgeCardView[] {
  const idx = cards.findIndex((c) => c.card_id === card.card_id);
  if (idx === -1) return [...cards, card];
  const next = [...cards];
  next[idx] = card;
  return next;
}

export function knowledgeCardReducer(
  state: KnowledgeCardState,
  action: KnowledgeCardAction,
): KnowledgeCardState {
  switch (action.type) {
    case "CARDS_LOADING":
      return { ...state, status: "loading", recoverableError: null };

    case "CARDS_LOADED":
      return {
        ...state,
        status: "ready",
        cards: action.cards,
        recoverableError: null,
        mutationError: null,
        fatalError: null,
      };

    case "CARDS_LOAD_FAILED":
      if (action.error.kind === "recoverable") {
        return { ...state, status: "ready", recoverableError: action.error };
      }
      return { ...state, status: "error", fatalError: action.error.message };

    case "KBS_LOADED":
      return { ...state, kbs: action.kbs };

    case "ARTIFACTS_LOADED":
      return { ...state, artifacts: action.artifacts };

    case "SELECT_CARD":
      return { ...state, selectedCardId: action.cardId };

    case "OPEN_EDITOR":
      return { ...state, editorOpen: true, selectedCardId: action.cardId };

    case "CLOSE_EDITOR":
      return { ...state, editorOpen: false, selectedCardId: state.selectedCardId };

    case "OPEN_MOBILE_EDITOR":
      return { ...state, mobileEditorOpen: true, selectedCardId: action.cardId };

    case "CLOSE_MOBILE_EDITOR":
      return { ...state, mobileEditorOpen: false, selectedCardId: state.selectedCardId };

    case "CARD_UPSERT":
      return { ...state, cards: upsertCard(state.cards, action.card) };

    case "CARD_MUTATION_MERGE":
      return {
        ...state,
        cards: state.cards.map((card) =>
          card.card_id === action.cardId
            ? mergeMutationResult(card, action.result)
            : card,
        ),
      };

    case "MUTATION_START":
      return {
        ...state,
        busy: { ...state.busy, [action.key]: true },
        recoverableError: null,
        mutationError: null,
      };

    case "MUTATION_END":
      return { ...state, busy: { ...state.busy, [action.key]: false } };

    case "MUTATION_FAILED":
      return {
        ...state,
        busy: { ...state.busy, [action.key]: false },
        recoverableError: action.error.kind === "recoverable" ? action.error : state.recoverableError,
        mutationError:
          action.error.kind === "recoverable"
            ? state.mutationError
            : action.error.message,
      };

    case "MUTATION_ERROR_CLEAR":
      return { ...state, mutationError: null };

    case "CONFIRM_OPEN":
      return { ...state, confirm: action.confirm };

    case "CONFIRM_CLOSE":
      return { ...state, confirm: null };

    case "RECOVER":
      return { ...state, recoverableError: null };

    case "TOGGLE_EXPANDED":
      return {
        ...state,
        expandedIds: { ...state.expandedIds, [action.id]: !state.expandedIds[action.id] },
      };

    case "RESET_FOR_PATH":
      return {
        ...state,
        status: "idle",
        cards: [],
        selectedCardId: null,
        editorOpen: false,
        mobileEditorOpen: false,
        busy: {},
        recoverableError: null,
        mutationError: null,
        fatalError: null,
        confirm: null,
      };

    default:
      return state;
  }
}

/* ── selectors ─────────────────────────────────────────────────────────── */

export function selectedCard(state: KnowledgeCardState): KnowledgeCardView | null {
  if (!state.selectedCardId) return null;
  return state.cards.find((c) => c.card_id === state.selectedCardId) ?? null;
}

export function classifyKbsFromSummaries(
  kbs: KnowledgeBaseSummary[],
): KbOption[] {
  return classifyKbs(kbs);
}

export function kbOptionsFromState(state: KnowledgeCardState): KbOption[] {
  return state.kbs;
}
