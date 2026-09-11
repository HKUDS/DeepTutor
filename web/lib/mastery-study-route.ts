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
