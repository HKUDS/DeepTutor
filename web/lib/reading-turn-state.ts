/**
 * The reader's live state, read once when a chat turn is sent.
 *
 * Deliberately a module-level cell rather than React state on a shared context.
 * The viewport changes on every scroll tick; if the chat subscribed to it, every
 * pixel of scrolling would re-render the whole message list. Nothing renders
 * from these values — they are only read at send time — so a plain cell is both
 * cheaper and more honest about that.
 *
 * Written by the reader pane; read by the chat's turn builder.
 */

import {
  READING_WORKSPACE_MODE,
  type WorkspaceMode,
} from "@/lib/workspace-mode";

/** Backward-compatible name for callers that still label the old capability. */
export const READING_CAPABILITY = READING_WORKSPACE_MODE;
export { READING_WORKSPACE_MODE };

export interface ReadingTurnState {
  workspaceId: string | null;
  materialId: string | null;
  materialRevision: number | null;
  locator: number;
  selection: string;
  timeSeconds: number | null;
}

const state: ReadingTurnState = {
  workspaceId: null,
  materialId: null,
  materialRevision: null,
  locator: 0,
  selection: "",
  timeSeconds: null,
};

/** Validate persisted/wire material ids before they become reader addresses. */
export function normalizeReadingMaterialId(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const normalized = value.trim().toLowerCase();
  return /^[0-9a-f]{8,64}$/.test(normalized) ? normalized : null;
}

/** Normalize an immutable ReadingStore content revision from wire/storage. */
export function normalizeReadingMaterialRevision(
  value: unknown,
): number | null {
  const revision = typeof value === "number" ? value : Number(value);
  return Number.isSafeInteger(revision) && revision >= 1 ? revision : null;
}

export function setReadingWorkspace(workspaceId: string | null): void {
  state.workspaceId = workspaceId;
  if (!workspaceId) {
    state.materialId = null;
    state.materialRevision = null;
    state.locator = 0;
    state.selection = "";
    state.timeSeconds = null;
  }
}

export function setReadingMaterial(
  materialId: string | null,
  materialRevision: number | null = null,
): void {
  state.materialId = materialId;
  state.materialRevision = materialId
    ? normalizeReadingMaterialRevision(materialRevision)
    : null;
  if (!materialId) {
    // Closing a document must not leave its viewport behind: the next turn
    // would tell the model the user is looking at a page of a closed file.
    state.locator = 0;
    state.selection = "";
    state.timeSeconds = null;
  }
}

export function setReadingViewport(next: {
  locator?: number;
  selection?: string;
  timeSeconds?: number | null;
}): void {
  if (typeof next.locator === "number" && Number.isFinite(next.locator)) {
    state.locator = next.locator > 0 ? Math.floor(next.locator) : 0;
  }
  if (typeof next.selection === "string") {
    state.selection = next.selection;
  }
  if (next.timeSeconds === null) {
    state.timeSeconds = null;
  } else if (
    typeof next.timeSeconds === "number" &&
    Number.isFinite(next.timeSeconds)
  ) {
    state.timeSeconds = Math.max(0, next.timeSeconds);
  }
}

export function getReadingTurnState(): ReadingTurnState {
  return { ...state };
}

/**
 * Turn fields to merge into a `start_turn` payload.
 *
 * Empty unless the conversation belongs to the immersive-reading workspace.
 * The per-turn action is deliberately irrelevant: Research and Visualize need
 * the same open document and viewport that Chat and Solve receive.
 *
 * Both halves of that condition are load-bearing. The open document lives in a
 * provider mounted in the workspace layout so it survives the remount that
 * sending the first message causes, which also means it survives switching modes
 * and starting a new session. Keying only on "is a document open" therefore
 * attached the reader to *every* later turn: a fresh chat session, in Chat mode,
 * would open with "I see you're reading …" and cite pages from a document the
 * user had moved on from.
 */
export function readingTurnFields(
  workspaceMode: WorkspaceMode | null | undefined,
): {
  reading_workspace_id?: string;
  reading_material_id?: string;
  reading_material_revision?: number;
  reading_viewport?: {
    locator?: number;
    selection?: string;
    time_seconds?: number;
  };
} {
  if (workspaceMode !== READING_WORKSPACE_MODE) return {};
  const viewport: {
    locator?: number;
    selection?: string;
    time_seconds?: number;
  } = {};
  if (state.locator > 0) viewport.locator = state.locator;
  if (state.selection) viewport.selection = state.selection;
  if (state.timeSeconds !== null) viewport.time_seconds = state.timeSeconds;
  return {
    ...(state.workspaceId ? { reading_workspace_id: state.workspaceId } : {}),
    ...(state.materialId ? { reading_material_id: state.materialId } : {}),
    ...(state.materialId && state.materialRevision
      ? { reading_material_revision: state.materialRevision }
      : {}),
    ...(Object.keys(viewport).length ? { reading_viewport: viewport } : {}),
  };
}

/** Test seam: reset the cell between cases. */
export function resetReadingTurnState(): void {
  state.workspaceId = null;
  state.materialId = null;
  state.materialRevision = null;
  state.locator = 0;
  state.selection = "";
  state.timeSeconds = null;
}
