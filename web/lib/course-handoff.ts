import type { StreamEvent } from "@/features/chat/model/protocol";
import { toolResultPayload } from "@/lib/tool-event";

/**
 * Reading the `course_study` capability's hand-off signals off a turn's stream.
 *
 * Course Study does not teach. It reads the course's state, says what is worth
 * doing next, and hands the learner to the surface that actually does it — with
 * the opening message already written. That hand-off arrives as
 * `course_handoff` on a tool result's metadata and becomes a card.
 *
 * A card rather than an automatic redirect on purpose: the learner may still be
 * reading the paragraph that explains *why*, and a page that changes underneath
 * them reads as a malfunction. The card also makes the reasoning inspectable
 * and the suggestion refusable.
 *
 * Mirrors the metadata written by `deeptutor/capabilities/course_study/tools.py`.
 * Kept as pure functions, apart from the component that renders them, for the
 * same reason `lib/setup-signals.ts` is.
 */

/**
 * Where a hand-off may point.
 *
 * A closed set, not a free-form path: the target is resolved against the route
 * table below, so a malformed or hostile value cannot turn the card into an
 * open redirect. Same reasoning as the `/settings` prefix check in
 * `lib/setup-signals.ts`.
 */
export const COURSE_HANDOFF_TARGETS = [
  "immersive_reading",
  "mastery_path",
  "question_bank",
  "notebook",
  "chat",
] as const;

export type CourseHandoffTarget = (typeof COURSE_HANDOFF_TARGETS)[number];

export interface CourseHandoffPayload {
  target: CourseHandoffTarget;
  /** The opening message to hand the destination. May be empty. */
  prompt: string;
  /** Why this is worth doing now — shown on the card, never sent. */
  reason: string;
  /** Which resource to open there (workspace id, path id). May be empty. */
  ref_id: string;
  /** Display name of the destination resource. */
  label: string;
  /**
   * The course this hand-off belongs to.
   *
   * Supplied by the tool rather than re-derived here: the capability only runs
   * with a course bound, so the server already knows it, and threading it down
   * the message-component props would make every layer in between carry a
   * value only this card uses.
   */
  course_id: string;
}

/**
 * Targets that have a composer to receive an opening line.
 *
 * The question bank and notebook surfaces are lists — they have nothing to type
 * into. Handing them a prepared prompt writes it into a slot nobody reads, so
 * the card must not offer one, and a request phrased as a question ("walk me
 * through these") belongs in chat instead.
 */
const TARGETS_WITH_COMPOSER: ReadonlySet<CourseHandoffTarget> = new Set([
  "immersive_reading",
  "mastery_path",
  "chat",
]);

/**
 * Targets whose composer only exists once a specific resource is named.
 *
 * `/mastery/<id>/sessions` and `/reading/<id>` have somewhere to type; the
 * `/mastery` and `/reading` indexes they fall back to when the course has no
 * such resource yet do not. Storing a prompt for those is worse than useless:
 * `setPendingPrompt` is scoped per destination and consumed on arrival, so an
 * opening line left behind by a card the learner never took resurfaces in
 * whichever path or workspace they open next, weeks later, about a subject they
 * were not studying.
 */
const TARGETS_NEEDING_REF: ReadonlySet<CourseHandoffTarget> = new Set([
  "immersive_reading",
  "mastery_path",
]);

export function targetAcceptsPrompt(
  target: CourseHandoffTarget,
  refId = "",
): boolean {
  if (!TARGETS_WITH_COMPOSER.has(target)) return false;
  return Boolean(refId.trim()) || !TARGETS_NEEDING_REF.has(target);
}

function isTarget(value: unknown): value is CourseHandoffTarget {
  return (
    typeof value === "string" &&
    (COURSE_HANDOFF_TARGETS as readonly string[]).includes(value)
  );
}

/**
 * Extract a hand-off from one stream event, or null.
 *
 * A tool's own `ToolResult.metadata` does not arrive at the top level of the
 * event: the dispatcher nests it under `tool_metadata` (see
 * `core/agentic/tool_dispatch.py`). Reading only the top level looks right and
 * type-checks fine, but silently finds nothing. The top level is still checked
 * as a fallback for callers that emit the event directly.
 */
export function courseHandoffFrom(event: {
  type?: string;
  metadata?: unknown;
}): CourseHandoffPayload | null {
  if (event?.type !== "tool_result") return null;
  const metadata = event.metadata;
  if (!metadata || typeof metadata !== "object") return null;

  const raw = toolResultPayload(metadata, "course_handoff");
  if (!raw || typeof raw !== "object") return null;
  const payload = raw as Record<string, unknown>;
  if (!isTarget(payload.target)) return null;

  return {
    target: payload.target,
    prompt: String(payload.prompt ?? ""),
    reason: String(payload.reason ?? ""),
    ref_id: String(payload.ref_id ?? ""),
    label: String(payload.label ?? ""),
    course_id: String(payload.course_id ?? ""),
  };
}

/**
 * Every hand-off in a message, de-duplicated by target and ref.
 *
 * A turn may legitimately suggest two different next steps ("finish the
 * reading, then drill the quiz"), so all of them are kept — but a model that
 * calls the tool twice for one destination should still produce one card.
 */
export function extractCourseHandoffs(
  events: StreamEvent[] | undefined,
): CourseHandoffPayload[] {
  if (!events || events.length === 0) return [];
  const seen = new Set<string>();
  const handoffs: CourseHandoffPayload[] = [];
  for (const event of events) {
    const payload = courseHandoffFrom(event);
    if (!payload) continue;
    const key = `${payload.target}:${payload.ref_id}`;
    if (seen.has(key)) continue;
    seen.add(key);
    handoffs.push(payload);
  }
  return handoffs;
}

/**
 * Resolve a hand-off to an in-app route.
 *
 * The course is carried into the query string so the destination can scope
 * itself — the question bank and notebook surfaces are global otherwise, and
 * arriving at an unfiltered list defeats the point of being sent there.
 */
export function courseHandoffHref(payload: CourseHandoffPayload): string {
  const course = encodeURIComponent(payload.course_id);
  const ref = encodeURIComponent(payload.ref_id);
  switch (payload.target) {
    case "immersive_reading":
      // Every branch stays course-scoped: an existing workspace still opens a
      // conversation that belongs to this course, rather than only the empty
      // index honouring the context that sent the learner here.
      return payload.ref_id
        ? `/reading/${ref}?course=${course}`
        : `/reading?course=${course}`;
    case "mastery_path":
      // The study route, not the path overview: the overview has no composer,
      // so a prepared opening line would have nowhere to land.
      return payload.ref_id
        ? `/mastery/${ref}/sessions?course=${course}`
        : `/mastery?course=${course}`;
    case "question_bank":
      return `/space/questions?course=${course}`;
    case "notebook":
      return `/notebooks?course=${course}`;
    case "chat":
      return `/chat?course=${course}`;
  }
}

/**
 * Remove a hand-off payload the model also printed as prose.
 *
 * Some models emit a tool call twice — once properly, and once as literal JSON
 * in the answer text. The call works and the card renders; the learner is just
 * shown the raw arguments above it, reading the same recommendation twice, the
 * second time as machine output. Only applied to a message that really did
 * produce a hand-off, and only to an object carrying this tool's own required
 * keys, so ordinary JSON a learner asked about is never touched.
 *
 * The payload has no nested objects, which is what makes the brace-free inner
 * match both sufficient and safe against runaway matching.
 */
const LEAKED_HANDOFF = new RegExp(
  String.raw`(?:^|\n)[ \t]*(?:` +
    String.raw`\x60\x60\x60(?:json)?[ \t]*\n)?[ \t]*` +
    String.raw`\{[^{}]*?"target"[ \t]*:[ \t]*"(?:` +
    COURSE_HANDOFF_TARGETS.join("|") +
    String.raw`)"[^{}]*?"reason"[ \t]*:[^{}]*\}` +
    String.raw`(?:[ \t]*\n\x60\x60\x60)?[ \t]*(?=\n|$)`,
  "g",
);

export function stripLeakedHandoffJson(content: string): string {
  if (!content.includes('"target"')) return content;
  return content
    .replace(LEAKED_HANDOFF, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}
