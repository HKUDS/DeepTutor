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

/** The capability value the composer sends for immersive reading. */
export const READING_CAPABILITY = "immersive_reading";

export interface ReadingTurnState {
  materialId: string | null;
  locator: number;
  selection: string;
}

const state: ReadingTurnState = {
  materialId: null,
  locator: 0,
  selection: "",
};

export function setReadingMaterial(materialId: string | null): void {
  state.materialId = materialId;
  if (!materialId) {
    // Closing a document must not leave its viewport behind: the next turn
    // would tell the model the user is looking at a page of a closed file.
    state.locator = 0;
    state.selection = "";
  }
}

export function setReadingViewport(next: {
  locator?: number;
  selection?: string;
}): void {
  if (typeof next.locator === "number" && Number.isFinite(next.locator)) {
    state.locator = next.locator > 0 ? Math.floor(next.locator) : 0;
  }
  if (typeof next.selection === "string") {
    state.selection = next.selection;
  }
}

export function getReadingTurnState(): ReadingTurnState {
  return { ...state };
}

/**
 * Turn fields to merge into a `start_turn` payload.
 *
 * Empty unless the turn is *actually* an immersive-reading turn — the caller
 * passes the capability it is about to send, and anything else gets nothing.
 *
 * Both halves of that condition are load-bearing. The open document lives in a
 * provider mounted in the workspace layout so it survives the remount that
 * sending the first message causes, which also means it survives switching modes
 * and starting a new session. Keying only on "is a document open" therefore
 * attached the reader to *every* later turn: a fresh chat session, in Chat mode,
 * would open with "I see you're reading …" and cite pages from a document the
 * user had moved on from.
 */
export function readingTurnFields(capability: string | null | undefined): {
  reading_material_id?: string;
  reading_viewport?: { locator?: number; selection?: string };
} {
  if (capability !== READING_CAPABILITY) return {};
  if (!state.materialId) return {};
  const viewport: { locator?: number; selection?: string } = {};
  if (state.locator > 0) viewport.locator = state.locator;
  if (state.selection) viewport.selection = state.selection;
  return {
    reading_material_id: state.materialId,
    ...(Object.keys(viewport).length ? { reading_viewport: viewport } : {}),
  };
}

/** Test seam: reset the cell between cases. */
export function resetReadingTurnState(): void {
  state.materialId = null;
  state.locator = 0;
  state.selection = "";
}
