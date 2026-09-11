import type { StreamEvent } from "@/features/chat/model/protocol";

export type DeepResearchFollowupStatus = "researching" | "done" | "failed";

function eventMetadata(event: StreamEvent): Record<string, unknown> {
  return (event.metadata ?? {}) as Record<string, unknown>;
}

export function isConfirmedResearchFollowup(
  events: StreamEvent[] | undefined,
): boolean {
  if (!events?.length) return false;
  if (
    events.some(
      (event) =>
        event.type === "result" &&
        eventMetadata(event).outline_preview === true,
    )
  ) {
    return false;
  }
  return events.some(
    (event) => event.stage === "researching" || event.stage === "reporting",
  );
}

export function researchFollowupStatus(
  events: StreamEvent[] | undefined,
): DeepResearchFollowupStatus {
  const done = [...(events ?? [])]
    .reverse()
    .find((event) => event.type === "done");
  if (!done) return "researching";
  const status = String(eventMetadata(done).status || "completed");
  if (status !== "completed") return "failed";
  const response = authoritativeResearchReport(events, "");
  return isStructurallyCompleteResearchReport(response) ? "done" : "failed";
}

function isStructurallyCompleteResearchReport(content: string): boolean {
  const normalized = normalizeDeepResearchReportFormatting(content).trim();
  if (!normalized) return false;
  // A confirmed outline always has at least one researched section, so a
  // complete report needs introduction + one body section + conclusion.
  const numberedSections = normalized.match(/^##\s+\d+\.\s*\S/gm) ?? [];
  if (numberedSections.length < 3) return false;
  if (normalized.endsWith("</details>")) return true;
  return /[.!?。！？)\]）】]$/.test(normalized);
}

export function normalizeDeepResearchReportFormatting(content: string): string {
  if (!content) return content;
  return content.replace(/^(# [^\r\n]*?)(?=##\s+\d+\.\s*)/, "$1\n\n");
}

export function authoritativeResearchReport(
  events: StreamEvent[] | undefined,
  fallback: string,
): string {
  for (let index = (events?.length ?? 0) - 1; index >= 0; index -= 1) {
    const event = events?.[index];
    if (!event || event.type !== "result") continue;
    const metadata = eventMetadata(event);
    if (metadata.outline_preview === true) continue;
    const response = metadata.response;
    if (typeof response === "string" && response.trim()) {
      return normalizeDeepResearchReportFormatting(response);
    }
  }
  return normalizeDeepResearchReportFormatting(fallback);
}

export function shouldReturnToChatAfterResearch(
  events: StreamEvent[] | undefined,
): boolean {
  if (!isConfirmedResearchFollowup(events)) return false;
  return Boolean(events?.some((event) => event.type === "done"));
}
