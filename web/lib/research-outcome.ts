export type ResearchOutcome = Record<string, unknown> & {
  outcome: "completed" | "partial" | "failed";
};

export type ResearchOutcomeAction =
  | { kind: "retry"; strategy: "failed_blocks" | "report_only" | "full_research"; label: string }
  | { kind: "settings"; label: string }
  | { kind: "none"; label: string };

export function researchOutcomeAction(outcome: ResearchOutcome): ResearchOutcomeAction {
  const failure = (outcome.failure || {}) as Record<string, unknown>;
  const code = String(failure.code || "");
  if (code === "model_protocol_error" || code === "research_planning_failed") return { kind: "settings", label: "Open model settings" };
  if (code === "model_output_incomplete") return { kind: "retry", strategy: "full_research", label: "Retry with higher budget" };
  if (code === "model_provider_failed" || code === "model_transport_transient" || code === "model_provider_transient") return { kind: "retry", strategy: "full_research", label: "Retry research" };
  if (code === "model_output_empty") return { kind: "settings", label: "Review model settings" };
  if (code === "research_all_blocks_failed" || code === "tool_stage_failed") return { kind: "retry", strategy: "failed_blocks", label: "Retry failed parts" };
  if (code === "report_generation_failed") return { kind: "retry", strategy: "report_only", label: "Retry report" };
  if (outcome.outcome === "partial") return { kind: "retry", strategy: "failed_blocks", label: "Retry failed parts" };
  return { kind: "none", label: "" };
}

type ResultLike = { type?: string; metadata?: unknown };

/** Read the capability result envelope without treating its transport fields as outcome data. */
export function extractResearchOutcome(metadata: unknown): ResearchOutcome | null {
  if (!metadata || typeof metadata !== "object") return null;
  const outer = metadata as Record<string, unknown>;
  const nested = outer.metadata;
  if (nested && typeof nested === "object" && typeof (nested as Record<string, unknown>).outcome === "string") {
    return nested as ResearchOutcome;
  }
  return typeof outer.outcome === "string" ? outer as ResearchOutcome : null;
}

export function researchOutlineStatus(outcome: ResearchOutcome | null): "done" | "partial" | "failed" | undefined {
  if (!outcome) return undefined;
  return outcome.outcome === "completed" ? "done" : outcome.outcome;
}

export function shouldShowResearchBody(
  hasOutline: boolean,
  outlineStatus: string | undefined,
  outcome: ResearchOutcome | null,
  content: string | undefined,
): boolean {
  if (!hasOutline || !String(content || "").trim()) return false;
  if (outcome) {
    return outcome.outcome === "completed"
      || outcome.outcome === "partial"
      || outcome.outcome === "failed";
  }
  return outlineStatus === "researching" || outlineStatus === "done";
}

export function researchOutcomeSurface(outcome: ResearchOutcome): {
  showReason: boolean;
  showAction: boolean;
  showDiagnostics: boolean;
} {
  const complete = outcome.outcome === "completed";
  return {
    showReason: !complete,
    showAction: !complete && researchOutcomeAction(outcome).kind !== "none",
    showDiagnostics: !complete,
  };
}

/** Suppress only the terminal error already represented by the failed result. */
export function suppressTerminalErrorForResearch(events: readonly ResultLike[] | undefined): boolean {
  const failed = (events ?? []).flatMap((event) => {
    if (event.type !== "result") return [];
    const outcome = extractResearchOutcome(event.metadata);
    if (!outcome || outcome.outcome !== "failed") return [];
    const failure = (outcome.failure || {}) as Record<string, unknown>;
    const failureCode = String(failure.code || "");
    const attemptId = String(outcome.attempt_id || "");
    return failureCode && attemptId ? [{ failureCode, attemptId }] : [];
  });
  return (events ?? []).some((event) => {
    if (event.type !== "error" || !event.metadata || typeof event.metadata !== "object") return false;
    const metadata = event.metadata as Record<string, unknown>;
    if (metadata.error_type !== "ResearchTerminalError") return false;
    return failed.some(
      ({ failureCode, attemptId }) => metadata.failure_code === failureCode
        && metadata.attempt_id === attemptId,
    );
  });
}

/** Split a merged research timeline into its planning result and terminal outcome. */
export function selectResearchResults(events: readonly ResultLike[] | undefined): {
  outlineResult: ResultLike | null;
  terminalOutcomeResult: ResultLike | null;
} {
  const results = (events ?? []).filter((event) => event.type === "result");
  const outlineResult = results.find((event) => {
    const metadata = event.metadata;
    return Boolean(metadata && typeof metadata === "object" && (metadata as Record<string, unknown>).outline_preview);
  }) ?? null;
  const terminalOutcomeResult = [...results].reverse().find(
    (event) => extractResearchOutcome(event.metadata) !== null,
  ) ?? null;
  return { outlineResult, terminalOutcomeResult };
}
