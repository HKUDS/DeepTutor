/**
 * The `/home` launch-URL contract — both ends in one place.
 *
 * Capability shortcuts can open `/home` with query parameters that set up the
 * composer before the learner types. Mastery Path formerly used this contract;
 * its parser remains for forwarding old links to the dedicated product.
 *
 * Parsing is deliberately dependency-free: tool names are returned verbatim
 * and validated by the caller against its own tool registry.
 */

/** Composer setup requested by the URL that opened `/home`. */
export interface ChatLaunchIntent {
  /** Capability to activate. `""` means plain chat; `null` means unspecified. */
  capability: string | null;
  /** Raw `tool` values — the caller filters these against its registry. */
  tools: string[];
  /** Persistent mastery path this conversation should operate on. */
  masteryPathId: string | null;
}

const EMPTY_INTENT: ChatLaunchIntent = {
  capability: null,
  tools: [],
  masteryPathId: null,
};

/** Read the launch intent out of a `location.search` string. */
export function readChatLaunchIntent(search: string): ChatLaunchIntent {
  if (!search) return { ...EMPTY_INTENT };
  const params = new URLSearchParams(search);
  const capability = params.get("capability");
  return {
    capability: capability === null ? null : capability.trim(),
    tools: params.getAll("tool").map((tool) => tool.trim()),
    masteryPathId: params.get("mastery_path_id")?.trim() || null,
  };
}

/** Open a topic on the dedicated Mastery Path product surface. */
export function newMasteryPathChatUrl(masteryPathId: string): string {
  return `/mastery/${encodeURIComponent(masteryPathId)}`;
}
