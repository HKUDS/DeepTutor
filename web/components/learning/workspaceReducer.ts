import type {
  AttemptDetail,
  FeynmanMapPayload,
  ReviewsPayload,
} from "@/lib/feynman-learning";
import type {
  ConversationItem,
  ContractError,
  StageState,
  WorkspaceConflict,
} from "./contract";
import { deriveStages } from "./contract";

/* ────────────────────────────────────────────────────────────────────────
 * Feynman workspace reducer (UI-01).
 *
 * Owns the render state of the vertical learning workspace: knowledge map +
 * sources, Teach-Back conversation and confirmed-transcript boundary, stage
 * bar, Evidence Panel, review queue, model identity and mobile tabs. Pure
 * and React-free so node tests exercise every transition.
 * ──────────────────────────────────────────────────────────────────────── */

export type WorkspaceTab = "map" | "chat" | "evidence";

export type LoadStatus = "loading" | "ready" | "empty" | "error";

export type TranscriptState = "idle" | "editing";

export interface WorkspaceState {
  pathId: string;
  loadStatus: LoadStatus;
  map: FeynmanMapPayload | null;
  reviews: ReviewsPayload | null;
  selectedKpId: string;
  attempt: AttemptDetail | null;
  activeTab: WorkspaceTab;
  composerText: string;
  transcriptText: string;
  transcriptState: TranscriptState;
  helpLevel: string | null;
  usedFullExplanation: boolean;
  recoverableError: ContractError | null;
  fatalError: string | null;
  /** The server's aggregate version used for the next guarded mutation. */
  refreshMeta: { attemptVersion: number; mapVersion: number } | null;
  busy: Record<string, boolean>;
  resolvedConflictIds: string[];
  reopenedConflictIds: string[];
  /** Expandable full-value tooltips for long model/source identifiers. */
  expandedIds: Record<string, boolean>;
}

export const initialState: WorkspaceState = {
  pathId: "",
  loadStatus: "loading",
  map: null,
  reviews: null,
  selectedKpId: "",
  attempt: null,
  activeTab: "chat",
  composerText: "",
  transcriptText: "",
  transcriptState: "idle",
  helpLevel: null,
  usedFullExplanation: false,
  recoverableError: null,
  fatalError: null,
  refreshMeta: null,
  busy: {},
  resolvedConflictIds: [],
  reopenedConflictIds: [],
  expandedIds: {},
};

export type WorkspaceAction =
  | { type: "INIT"; pathId: string }
  | { type: "MAP_LOADED"; map: FeynmanMapPayload; reviews: ReviewsPayload }
  | { type: "MAP_EMPTY" }
  | { type: "MAP_LOAD_FAILED"; error: ContractError }
  | { type: "ATTEMPT_LOADED"; attempt: AttemptDetail | null }
  | { type: "ATTEMPT_LOAD_FAILED"; error: ContractError }
  | { type: "SELECT_KP"; kpId: string }
  | { type: "RESUME_STARTED" }
  | { type: "RESUME_SUCCEEDED"; attempt: AttemptDetail; refreshMeta: { attemptVersion: number; mapVersion: number } }
  | { type: "RESUME_FAILED"; error: ContractError }
  | { type: "COMPOSER_CHANGED"; text: string }
  | { type: "TRANSCRIPT_START" }
  | { type: "TRANSCRIPT_CHANGED"; text: string }
  | { type: "TRANSCRIPT_CANCEL" }
  | { type: "TAB_CHANGED"; tab: WorkspaceTab }
  | { type: "CHALLENGE_REQUESTED" }
  | { type: "CHALLENGE_SUCCEEDED"; attemptVersion: number }
  | { type: "CHALLENGE_FAILED"; error: ContractError }
  | { type: "CONFLICT_RESOLVED"; conflictId: string }
  | { type: "CONFLICT_REOPENED"; conflictId: string }
  | { type: "RECOVER" }
  | { type: "SET_REFRESH_META"; attemptVersion: number; mapVersion: number }
  | { type: "TOGGLE_EXPANDED"; id: string };

function nextKpId(
  map: FeynmanMapPayload,
  attempt: AttemptDetail | null,
  current: string,
): string {
  if (attempt && attempt.attempt.knowledge_point_id) return attempt.attempt.knowledge_point_id;
  if (current && map.map.modules.some((m) => m.knowledge_points.some((k) => k.id === current))) {
    return current;
  }
  const active = Object.keys(map.active_attempts)[0];
  if (active) return active;
  if (map.next.knowledge_point_id) return map.next.knowledge_point_id;
  for (const mod of map.map.modules) {
    if (mod.knowledge_points.length) return mod.knowledge_points[0].id;
  }
  return "";
}

function attemptHasAnyEvidence(attempt: AttemptDetail | null): boolean {
  return !!attempt && attempt.evidence.length > 0;
}

export function workspaceReducer(
  state: WorkspaceState,
  action: WorkspaceAction,
): WorkspaceState {
  switch (action.type) {
    case "INIT":
      return { ...initialState, pathId: action.pathId };

    case "MAP_LOADED": {
      const selectedKpId = nextKpId(action.map, null, state.selectedKpId);
      return {
        ...state,
        loadStatus: action.map.map.modules.length === 0 ? "empty" : "ready",
        map: action.map,
        reviews: action.reviews,
        selectedKpId,
        recoverableError: null,
        fatalError: null,
        refreshMeta: {
          attemptVersion: 0,
          mapVersion: action.map.map_version,
        },
      };
    }

    case "MAP_EMPTY":
      return { ...state, loadStatus: "empty", map: null, reviews: null };

    case "MAP_LOAD_FAILED":
      return { ...state, loadStatus: "error", fatalError: action.error.message };

    case "ATTEMPT_LOADED": {
      if (!action.attempt) {
        return { ...state, attempt: null, helpLevel: null };
      }
      const selectedKpId = nextKpId(state.map!, action.attempt, state.selectedKpId);
      const maxHelp = action.attempt.attempt.max_help_level;
      return {
        ...state,
        attempt: action.attempt,
        selectedKpId,
        helpLevel: maxHelp !== "question" ? maxHelp : null,
        usedFullExplanation:
          action.attempt.assessments.some(
            (a) => a.server_gate_result.used_full_explanation,
          ) || maxHelp === "full_explanation",
        recoverableError: null,
      };
    }

    case "ATTEMPT_LOAD_FAILED": {
      if (action.error.kind === "recoverable") {
        return { ...state, recoverableError: action.error };
      }
      return { ...state, fatalError: action.error.message };
    }

    case "SELECT_KP":
      return { ...state, selectedKpId: action.kpId, attempt: null };

    case "RESUME_STARTED":
      return { ...state, busy: { ...state.busy, resume: true }, recoverableError: null };

    case "RESUME_SUCCEEDED":
      return {
        ...state,
        busy: { ...state.busy, resume: false },
        attempt: action.attempt,
        refreshMeta: action.refreshMeta,
        recoverableError: null,
      };

    case "RESUME_FAILED":
      return {
        ...state,
        busy: { ...state.busy, resume: false },
        recoverableError: action.error,
      };

    case "COMPOSER_CHANGED":
      return { ...state, composerText: action.text };

    case "TRANSCRIPT_START":
      return { ...state, transcriptState: "editing" };

    case "TRANSCRIPT_CHANGED":
      return { ...state, transcriptText: action.text };

    case "TRANSCRIPT_CANCEL":
      return { ...state, transcriptState: "idle", transcriptText: "" };

    case "TAB_CHANGED":
      return { ...state, activeTab: action.tab };

    case "CHALLENGE_REQUESTED":
      return { ...state, busy: { ...state.busy, challenge: true } };

    case "CHALLENGE_SUCCEEDED":
      return {
        ...state,
        busy: { ...state.busy, challenge: false },
        refreshMeta: state.refreshMeta
          ? { ...state.refreshMeta, attemptVersion: action.attemptVersion }
          : null,
        recoverableError: null,
      };

    case "CHALLENGE_FAILED":
      return { ...state, busy: { ...state.busy, challenge: false }, recoverableError: action.error };

    case "CONFLICT_RESOLVED":
      return {
        ...state,
        resolvedConflictIds: [...state.resolvedConflictIds, action.conflictId],
        reopenedConflictIds: state.reopenedConflictIds.filter((id) => id !== action.conflictId),
      };

    case "CONFLICT_REOPENED":
      return {
        ...state,
        reopenedConflictIds: [...state.reopenedConflictIds, action.conflictId],
        resolvedConflictIds: state.resolvedConflictIds.filter((id) => id !== action.conflictId),
      };

    case "RECOVER":
      return { ...state, recoverableError: null };

    case "SET_REFRESH_META":
      return {
        ...state,
        refreshMeta: { attemptVersion: action.attemptVersion, mapVersion: action.mapVersion },
      };

    case "TOGGLE_EXPANDED":
      return {
        ...state,
        expandedIds: { ...state.expandedIds, [action.id]: !state.expandedIds[action.id] },
      };

    default:
      return state;
  }
}

/* ── Selectors (pure, tested) ──────────────────────────────────────────── */

export function visibleConversation(state: WorkspaceState): ConversationItem[] {
  // The workspace renders only server-returned evidence (LRN-03 read APIs).
  // Drafts the learner is composing live in the composer, never in this stream;
  // they become evidence only after the real chat round-trip persists them.
  return evidenceItems(state.attempt);
}

export function evidenceItems(attempt: AttemptDetail | null): ConversationItem[] {
  if (!attemptHasAnyEvidence(attempt)) return [];
  return attempt!.evidence.map((e) => ({
    key: e.id,
    role:
      e.kind === "probe_question" || e.kind === "transfer_question"
        ? ("assistant" as const)
        : e.kind === "reteach" || e.kind === "source_reference"
          ? ("system" as const)
          : ("user" as const),
    labelKey: e.kind,
    kind: e.kind,
    content: e.content_snapshot,
    inputMode: e.input_mode === "voice_transcript" ? "voice_transcript" : "text",
    transcriptConfirmed: e.transcript_confirmed,
    helpLevel: e.help_level,
    createdAt: e.created_at,
  }));
}

export function openConflictsFor(state: WorkspaceState): WorkspaceConflict[] {
  if (!state.map) return [];
  const byId = new Map(state.map.source_snapshots.map((s) => [s.id, s]));
  return state.map.conflicts
    .filter((c) => c.status === "open")
    .map((conflict) => ({
      conflict,
      sides: conflict.source_snapshot_ids
        .map((id) => {
          const snapshot = byId.get(id);
          return snapshot
            ? { snapshot: { id: snapshot.id, title: snapshot.title, locator: snapshot.locator }, anchors: conflict.citation_anchors }
            : null;
        })
        .filter((s): s is WorkspaceConflict["sides"][number] => s !== null),
      acceptedSideId: conflict.accepted_snapshot_id,
    }));
}

export function stagesFor(state: WorkspaceState): StageState[] {
  // Derived in one place so the view and tests share the exact same rule.
  return deriveStages(
    state.attempt?.evidence ?? [],
    state.attempt?.assessments ?? [],
    state.usedFullExplanation,
  );
}
