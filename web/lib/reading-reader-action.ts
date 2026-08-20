/**
 * Bridge from a reading tool's result to the reader pane.
 *
 * The reading tools signal UI intent on their `ToolResult.metadata` under
 * `reader_action` — `goto` to move the view, `annotate` to surface a mark the
 * assistant just made. The chat forwards that as a DOM event and the reader pane
 * listens; neither side imports the other, so the chat needs no knowledge of the
 * reader and vice versa (the same seam the visualize-prompt bridge uses).
 *
 * The extraction is defensive because the metadata crosses the wire: anything
 * unrecognised is dropped rather than dispatched.
 */

/** Event name the reader pane listens on. */
export const READER_ACTION_EVENT = "dt:reader-action";
/**
 * Fired once a turn finishes, saying whether it ever moved the reader.
 *
 * The model is asked to call `reader_goto` for each passage it discusses, and
 * mostly does — but not always, and a turn that cites `[p.5]` while the reader
 * sits on page 1 looks broken regardless of whose fault it is. The pane uses
 * this to fall back to the first citation in the answer, so the view follows the
 * *answer* rather than the model's diligence.
 */
export const READER_TURN_END_EVENT = "dt:reader-turn-end";

/** Turns that have already moved the reader, so the fallback stays quiet. */
const movedTurns = new Set<string>();
/** Bound so a long session cannot accumulate ids forever. */
const MAX_TRACKED_TURNS = 64;

function rememberMoved(turnId: string): void {
  if (!turnId) return;
  if (movedTurns.size >= MAX_TRACKED_TURNS) movedTurns.clear();
  movedTurns.add(turnId);
}

export interface ReaderActionPayload {
  material_id?: string;
  reader_action: "goto" | "annotate";
  locator?: number;
  quote?: string;
  annotation?: Record<string, unknown>;
}

/**
 * Extract a reader action from a stream event's metadata, or null.
 *
 * A tool's own `ToolResult.metadata` does not arrive at the top level of the
 * event: the dispatcher nests it under `tool_metadata`, alongside its own trace
 * keys (see `core/agentic/tool_dispatch.py`). Reading the top level only —
 * which looks right and type-checks fine — silently finds nothing, so the
 * reader never moves. The top level is still checked as a fallback in case a
 * caller emits the event directly.
 */
export function readerActionFrom(event: {
  type?: string;
  metadata?: unknown;
}): ReaderActionPayload | null {
  if (event?.type !== "tool_result") return null;
  const metadata = event.metadata;
  if (!metadata || typeof metadata !== "object") return null;

  const outer = metadata as Record<string, unknown>;
  const nested = outer.tool_metadata;
  const raw = (nested && typeof nested === "object" ? nested : outer) as Record<
    string,
    unknown
  >;
  const action = raw.reader_action;
  if (action !== "goto" && action !== "annotate") return null;

  const payload: ReaderActionPayload = { reader_action: action };
  if (typeof raw.material_id === "string" && raw.material_id) {
    payload.material_id = raw.material_id;
  }
  const locator = Number(raw.locator);
  if (Number.isInteger(locator) && locator >= 1) payload.locator = locator;
  if (typeof raw.quote === "string" && raw.quote) payload.quote = raw.quote;
  if (raw.annotation && typeof raw.annotation === "object") {
    payload.annotation = raw.annotation as Record<string, unknown>;
  }
  return payload;
}

/**
 * Dispatch whatever *event* means for the reader.
 *
 * Called for every stream event; almost all of them are neither a reader action
 * nor a turn ending, and cost one string comparison.
 */
export function forwardReaderAction(event: {
  type?: string;
  metadata?: unknown;
  turn_id?: string;
}): void {
  if (typeof window === "undefined") return;
  const turnId = String(event?.turn_id || "");

  const payload = readerActionFrom(event);
  if (payload) {
    if (payload.reader_action === "goto") rememberMoved(turnId);
    window.dispatchEvent(
      new CustomEvent(READER_ACTION_EVENT, { detail: payload }),
    );
    return;
  }

  if (event?.type === "done") {
    const moved = turnId ? movedTurns.has(turnId) : false;
    movedTurns.delete(turnId);
    window.dispatchEvent(
      new CustomEvent(READER_TURN_END_EVENT, { detail: { moved } }),
    );
  }
}

/** Test seam: forget which turns have moved the reader. */
export function resetReaderActionTracking(): void {
  movedTurns.clear();
}
