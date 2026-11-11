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

/**
 * Whether the chat adapter is showing the session in the URL.
 *
 * Clicking a knowledge point changes the route first. Until the adapter
 * finishes loading that conversation, it still holds the previous one —
 * another point's questions, or a mode handoff that would bounce the page
 * back. The outline already highlights the requested point; the rest of
 * the study surface must wait.
 */
export function isRoutedStudySessionReady(input: {
  routeSessionId?: string;
  adapterSessionId: string | null;
  sessionLoading: boolean;
}): boolean {
  if (input.sessionLoading) return false;
  const route = (input.routeSessionId || "").trim();
  const adapter = (input.adapterSessionId || "").trim();
  if (!adapter) return false;
  return !route || adapter === route;
}

/**
 * Which knowledge point the mode switch above the transcript opens.
 *
 * It is the point already on screen, whichever mode is chosen. A path holds
 * one study conversation and one review conversation *per knowledge point*,
 * and the two are separate transcripts; switching modes is how the learner
 * moves between them, not how they move between points. Moving points is the
 * outline's job.
 *
 * This used to re-pick the target by mastery status — review only accepted a
 * mastered point, study only an unmastered one — and the result was that a
 * learner reading an unmastered point's study conversation and pressing
 * "review" was silently moved to some *other* point's review, because the
 * bound point had been filtered out of the eligible set. Two conversations
 * that belong to different objectives then looked like one objective's two
 * modes.
 */
export function modeSwitchTarget(
  points: readonly { id: string }[],
  bound: string,
  nextPointId: string,
): string {
  const boundId = bound.trim();
  if (boundId && points.some((point) => point.id === boundId)) return boundId;
  if (boundId) return boundId;
  // No conversation is bound yet, so this is the path's first sitting: start
  // at the frontier the outline is already pointing at.
  return points.find((point) => point.id === nextPointId)?.id || points[0]?.id || "";
}

/**
 * Whether the mode switch offers review for the point on screen.
 *
 * Review re-tests work the learner has already proven, so the control that
 * opens it should not exist before there is anything to consolidate. Showing
 * it earlier offered a conversation the tutor refuses to teach in — the
 * learner pressed "review" on an unmastered point and got either a different
 * point's transcript or a refusal.
 *
 * A conversation already in review keeps the control regardless of the
 * point's current status, so a learner can always see and leave the mode they
 * are in.
 *
 * The lecture is the other half of the gate. Review is the lecture beside a
 * re-test, so it waits for the lecture to be *confirmed*, not merely drafted:
 * a draft the learner is still shaping is not yet the document they review
 * from. ``hasLecture`` is whether a confirmed lecture exists; a live review
 * conversation stays available either way so the learner can leave it.
 */
export function isReviewAvailable(input: {
  modules: readonly {
    knowledge_points: readonly { id: string; status: string }[];
  }[];
  pointId: string;
  sessionMode: string;
  /** Whether the point has a *confirmed* lecture. */
  hasLecture: boolean;
}): boolean {
  if (input.sessionMode === "review") return true;
  const pointId = input.pointId.trim();
  if (!pointId) return false;
  if (!input.hasLecture) return false;
  for (const region of input.modules) {
    const point = region.knowledge_points.find((item) => item.id === pointId);
    if (point) return point.status === "mastered";
  }
  return false;
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
