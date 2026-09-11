export interface MasteryDraftRouteGuard {
  routeKey: string;
  previousSessionId: string | null;
}

/**
 * A draft route starts while UnifiedChatContext may still expose the session
 * that was visible on the previous page. Only promote the URL after the
 * backend has bound a different session to this draft.
 */
export function isMasteryDraftSessionReady({
  guard,
  routeKey,
  sessionId,
  masteryPathId,
  pathId,
}: {
  guard: MasteryDraftRouteGuard | null;
  routeKey: string;
  sessionId: string | null;
  masteryPathId: string | null;
  pathId: string;
}): boolean {
  return Boolean(
    guard &&
    guard.routeKey === routeKey &&
    sessionId &&
    sessionId !== guard.previousSessionId &&
    masteryPathId === pathId,
  );
}

/** Sending the first turn requires a committed local draft, not a server ID. */
export function isMasteryDraftSendReady(input: {
  binding: { routeKey: string; draftKey: string } | null;
  routeKey: string;
  sessionKey: string;
  workspaceMode: string | null;
  masteryPathId: string | null;
  pathId: string;
  masterySessionMode: string | null;
  requestedMode: string;
}): boolean {
  return Boolean(
    input.binding &&
    input.binding.routeKey === input.routeKey &&
    input.binding.draftKey === input.sessionKey &&
    input.workspaceMode === "mastery_path" &&
    input.masteryPathId === input.pathId &&
    input.masterySessionMode === input.requestedMode,
  );
}
