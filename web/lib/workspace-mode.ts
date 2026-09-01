export type WorkspaceMode = "immersive_reading" | "mastery_path";

export const READING_WORKSPACE_MODE = "immersive_reading" as const;
export const MASTERY_WORKSPACE_MODE = "mastery_path" as const;

const CONFIGURED_WORKSPACE_ACTIONS = new Set([
  "deep_question",
  "visualize",
  "deep_research",
]);

/** Actions whose prompt must wait for the learner to confirm their settings. */
export function workspaceActionNeedsConfiguration(
  value: string | null | undefined,
): boolean {
  return CONFIGURED_WORKSPACE_ACTIONS.has(value ?? "");
}

export function normalizeWorkspaceMode(
  value: unknown,
  legacyCapability?: unknown,
): WorkspaceMode | null {
  if (value === READING_WORKSPACE_MODE || value === MASTERY_WORKSPACE_MODE) {
    return value;
  }
  if (
    legacyCapability === READING_WORKSPACE_MODE ||
    legacyCapability === MASTERY_WORKSPACE_MODE
  ) {
    return legacyCapability;
  }
  return null;
}
