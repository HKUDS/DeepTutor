/**
 * Book Engine progress model
 * ==========================
 *
 * A pure reducer that turns the raw `BookWsEvent` stream coming out of the
 * BookEngine into a cleaned-up `BookProgress` snapshot. The `BookProgressTimeline`
 * component renders this snapshot — the reducer keeps the UI presentational.
 *
 * Stage order matches the actual pipeline:
 *
 *   ideation → exploration → synthesis (with critique sub-rounds) →
 *   overview (engine-injected) → compilation (per-page block stream)
 */

import type { BookWsEvent } from "@/lib/book-api";

export type StageId =
  | "ideation"
  | "exploration"
  | "synthesis"
  | "critique"
  | "overview"
  | "compilation";

export type StageState = "pending" | "running" | "completed" | "error";

export interface StageView {
  id: StageId;
  label: string;
  description: string;
  state: StageState;
  detail?: string;
  startedAt?: number;
  endedAt?: number;
}

export interface BookProgress {
  bookId: string | null;
  stages: Record<StageId, StageView>;
  ordered: StageId[];
  // Aggregated counters
  exploration: {
    queryCount: number;
    chunkCount: number;
    candidateConcepts: number;
    summary: string;
  };
  synthesis: {
    rounds: number;
    chapterCount: number;
    conceptNodes: number;
    conceptEdges: number;
    lastVerdict: string;
  };
  critique: {
    rounds: number;
    issues: number;
  };
  compilation: {
    pagesPlanned: number;
    pagesReady: number;
    blocksReady: number;
    blocksError: number;
  };
  // Latest progress message — useful as a single-line live caption.
  message: string;
  updatedAt: number;
}

export const STAGE_ORDER: StageId[] = [
  "ideation",
  "exploration",
  "synthesis",
  "critique",
  "overview",
  "compilation",
];

const STAGE_LABELS: Record<StageId, { label: string; description: string }> = {
  ideation: {
    label: "Ideation",
    description: "Drafting the proposal from your inputs.",
  },
  exploration: {
    label: "Source sweep",
    description: "Parallel multi-query retrieval across your KBs.",
  },
  synthesis: {
    label: "Synthesis",
    description: "Spine + concept graph (draft → revise).",
  },
  critique: {
    label: "Critique",
    description: "Self-review rounds tightening the spine.",
  },
  overview: {
    label: "Overview chapter",
    description: "Auto-built table of contents + concept map.",
  },
  compilation: {
    label: "Compilation",
    description: "Per-page block planning + generation.",
  },
};

export function emptyBookProgress(): BookProgress {
  const stages = Object.fromEntries(
    STAGE_ORDER.map((id) => [
      id,
      {
        id,
        label: STAGE_LABELS[id].label,
        description: STAGE_LABELS[id].description,
        state: "pending" as StageState,
      },
    ]),
  ) as Record<StageId, StageView>;
  return {
    bookId: null,
    stages,
    ordered: STAGE_ORDER,
    exploration: {
      queryCount: 0,
      chunkCount: 0,
      candidateConcepts: 0,
      summary: "",
    },
    synthesis: {
      rounds: 0,
      chapterCount: 0,
      conceptNodes: 0,
      conceptEdges: 0,
      lastVerdict: "",
    },
    critique: { rounds: 0, issues: 0 },
    compilation: {
      pagesPlanned: 0,
      pagesReady: 0,
      blocksReady: 0,
      blocksError: 0,
    },
    message: "",
    updatedAt: 0,
  };
}

function patchStage(
  state: BookProgress,
  id: StageId,
  patch: Partial<StageView>,
): BookProgress {
  const next = { ...state.stages[id], ...patch };
  return {
    ...state,
    stages: { ...state.stages, [id]: next },
  };
}

function startStage(state: BookProgress, id: StageId): BookProgress {
  // Mark earlier stages completed if they're still pending/running so the
  // timeline always reads left-to-right cleanly even when we miss an event.
  let next = state;
  for (const sid of STAGE_ORDER) {
    if (sid === id) break;
    const s = next.stages[sid];
    if (s.state === "pending" || s.state === "running") {
      next = patchStage(next, sid, { state: "completed", endedAt: Date.now() });
    }
  }
  return patchStage(next, id, {
    state: "running",
    startedAt: next.stages[id].startedAt ?? Date.now(),
  });
}

function completeStage(state: BookProgress, id: StageId): BookProgress {
  // A stage that already reported a failure stays failed: the pipeline still
  // emits stage_end on its way out of the `async with`, and letting that
  // overwrite the error would show a green tick for a sweep that found nothing.
  if (state.stages[id]?.state === "error") return state;
  return patchStage(state, id, { state: "completed", endedAt: Date.now() });
}

function errorStage(
  state: BookProgress,
  id: StageId,
  detail?: string,
): BookProgress {
  return patchStage(state, id, {
    state: "error",
    detail: detail || undefined,
    endedAt: Date.now(),
  });
}

function asNumber(value: unknown): number {
  if (typeof value === "number") return value;
  if (Array.isArray(value)) return value.length;
  if (value && typeof value === "object") return Object.keys(value).length;
  return 0;
}

function asString(value: unknown): string {
  return value == null ? "" : String(value);
}

/** Reducer: ingest a single WS event and return the next snapshot. */
export const RESET_BOOK_PROGRESS = { type: "__reset" } as const;

export function reduceBookEvent(
  state: BookProgress,
  event: BookWsEvent,
): BookProgress {
  const meta = (event.metadata as Record<string, unknown> | undefined) || {};
  const stage = String((event as { stage?: string }).stage || "");
  const rawKind = String(
    (event.content as string) || (meta.kind as string) || "",
  );
  const eventType = String(event.type || "");

  // Explicit reset — the timeline belongs to one book's run. Selecting another
  // book (or starting a new one) must not inherit the previous book's stages.
  if (eventType === "__reset") {
    return emptyBookProgress();
  }

  // A book id that contradicts the one we're tracking means the stream moved
  // on; start clean rather than blending two runs into one timeline.
  const incomingBookId = asString(
    (event.metadata as Record<string, unknown> | undefined)?.book_id,
  );
  if (incomingBookId && state.bookId && incomingBookId !== state.bookId) {
    state = emptyBookProgress();
  }

  // Track book id once.
  let next: BookProgress = { ...state, updatedAt: Date.now() };
  const bookIdFromMeta = asString(meta.book_id);
  if (bookIdFromMeta && next.bookId == null) {
    next = { ...next, bookId: bookIdFromMeta };
  }

  // Pick up STAGE_BEGIN / STAGE_END from generic stream events.
  if (eventType === "stage_start" && stage) {
    if ((STAGE_ORDER as string[]).includes(stage)) {
      next = startStage(next, stage as StageId);
    }
  }
  if (eventType === "stage_end" && stage) {
    if ((STAGE_ORDER as string[]).includes(stage)) {
      next = completeStage(next, stage as StageId);
    }
  }

  // Generic progress message for the live caption.
  if (eventType === "progress" && typeof event.content === "string") {
    next = { ...next, message: event.content as string };
  }

  // Book-specific kinds.
  switch (rawKind) {
    case "proposal_ready": {
      next = startStage(next, "ideation");
      next = completeStage(next, "ideation");
      next = { ...next, message: "Proposal ready" };
      break;
    }
    case "exploration_ready": {
      const queries = asNumber(meta.queries);
      const coverage = meta.coverage as Record<string, unknown> | undefined;
      const chunkCount = coverage
        ? Object.values(coverage).reduce<number>(
            (acc, v) => acc + asNumber(v),
            0,
          )
        : 0;
      next = startStage(next, "exploration");
      next = completeStage(next, "exploration");
      next = {
        ...next,
        exploration: {
          queryCount: queries,
          chunkCount,
          candidateConcepts: asNumber(meta.candidate_concepts),
          summary: asString(meta.summary).slice(0, 220),
        },
        message: `Source sweep done — ${queries} queries, ${chunkCount} chunks`,
      };
      next = patchStage(next, "exploration", {
        detail: `${queries} queries · ${chunkCount} chunks`,
      });
      break;
    }
    case "exploration_failed": {
      // The stage still emits stage_end afterwards; errorStage wins so the
      // timeline does not claim the sweep succeeded.
      next = errorStage(next, "exploration", asString(meta.reason));
      next = { ...next, message: "Source sweep failed" };
      break;
    }
    case "spine_round": {
      const round = asString(meta.round);
      const isCritique = round.startsWith("critique");
      const targetStage: StageId = isCritique ? "critique" : "synthesis";
      next = startStage(next, targetStage);
      const issueCount = asNumber(meta.issue_count);
      const chapterCount = asNumber(meta.chapter_count);
      const verdict = asString(meta.verdict);
      if (isCritique) {
        next = {
          ...next,
          critique: {
            rounds: next.critique.rounds + 1,
            issues: issueCount,
          },
        };
        next = patchStage(next, "critique", {
          detail: `${next.critique.rounds} round${
            next.critique.rounds === 1 ? "" : "s"
          } · ${issueCount} issue${issueCount === 1 ? "" : "s"}`,
        });
      } else {
        next = {
          ...next,
          synthesis: {
            ...next.synthesis,
            rounds: next.synthesis.rounds + 1,
            chapterCount: chapterCount || next.synthesis.chapterCount,
            lastVerdict: verdict,
          },
        };
        next = patchStage(next, "synthesis", {
          detail: `${next.synthesis.rounds} round${
            next.synthesis.rounds === 1 ? "" : "s"
          } · ${next.synthesis.chapterCount || 0} chapter${
            next.synthesis.chapterCount === 1 ? "" : "s"
          }`,
        });
      }
      next = {
        ...next,
        message: `${round}${verdict ? ` · ${verdict}` : ""}`,
      };
      break;
    }
    case "spine_ready": {
      const chapterCount = asNumber(meta.chapter_count);
      const nodes = asNumber(meta.concept_node_count);
      const edges = asNumber(meta.concept_edge_count);
      // Both synthesis + critique are done when the spine is ready.
      next = startStage(next, "synthesis");
      next = completeStage(next, "synthesis");
      if (next.critique.rounds > 0) {
        next = completeStage(next, "critique");
      } else {
        next = patchStage(next, "critique", { state: "completed" });
      }
      next = {
        ...next,
        synthesis: {
          ...next.synthesis,
          chapterCount,
          conceptNodes: nodes,
          conceptEdges: edges,
        },
        message: `Spine ready — ${chapterCount} chapters · ${nodes} concepts`,
      };
      next = patchStage(next, "synthesis", {
        detail: `${chapterCount} chapters · ${nodes} concepts`,
      });
      break;
    }
    case "page_planning": {
      next = startStage(next, "compilation");
      next = {
        ...next,
        compilation: {
          ...next.compilation,
          pagesPlanned: next.compilation.pagesPlanned + 1,
        },
      };
      break;
    }
    case "page_planned":
      next = startStage(next, "compilation");
      break;
    case "block_ready": {
      next = {
        ...next,
        compilation: {
          ...next.compilation,
          blocksReady: next.compilation.blocksReady + 1,
        },
      };
      break;
    }
    case "block_error": {
      next = {
        ...next,
        compilation: {
          ...next.compilation,
          blocksError: next.compilation.blocksError + 1,
        },
      };
      break;
    }
    case "page_compiled":
    case "page_ready": {
      next = startStage(next, "compilation");
      next = {
        ...next,
        compilation: {
          ...next.compilation,
          pagesReady: next.compilation.pagesReady + 1,
        },
      };
      next = patchStage(next, "compilation", {
        detail: `${next.compilation.pagesReady} page${
          next.compilation.pagesReady === 1 ? "" : "s"
        } · ${next.compilation.blocksReady} blocks`,
      });
      // Treat the overview as completed once the very first page is ready —
      // the engine pre-materialises the overview before any normal page
      // compilation.
      if (next.stages.overview.state !== "completed") {
        next = patchStage(next, "overview", {
          state: "completed",
          endedAt: Date.now(),
        });
      }
      break;
    }
    case "overview_ready": {
      next = startStage(next, "overview");
      next = completeStage(next, "overview");
      break;
    }
    case "book_ready":
    case "compilation_complete": {
      next = completeStage(next, "compilation");
      next = { ...next, message: "Book compilation complete" };
      break;
    }
    default:
      break;
  }

  // Stream-level error → mark the *currently running* stage as errored.
  if (eventType === "error") {
    const running = STAGE_ORDER.find(
      (id) => next.stages[id].state === "running",
    );
    if (running) {
      next = patchStage(next, running, {
        state: "error",
        detail: asString(event.content) || "error",
      });
    }
  }

  return next;
}

/** True when at least one stage is no longer pending — useful for hiding the
 * timeline on a freshly-loaded existing book where no events arrive. */
export function progressHasActivity(progress: BookProgress): boolean {
  return STAGE_ORDER.some((id) => progress.stages[id].state !== "pending");
}

/** True when every stage is either completed or errored (or skipped). */
export function progressIsTerminal(progress: BookProgress): boolean {
  return STAGE_ORDER.every((id) => {
    const s = progress.stages[id].state;
    return s === "completed" || s === "error" || s === "pending";
  });
}

/** True when generation is fully done — every stage has completed or
 *  errored. Implies activity (compilation must have advanced past pending). */
export function progressIsComplete(progress: BookProgress): boolean {
  if (!progressHasActivity(progress)) return false;
  return STAGE_ORDER.every((id) => {
    const s = progress.stages[id].state;
    return s === "completed" || s === "error";
  });
}
