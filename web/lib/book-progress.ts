/**
 * Book Engine progress model
 * ==========================
 *
 * A pure reducer that turns the raw `BookWsEvent` stream coming out of the
 * BookEngine into a cleaned-up `BookProgress` snapshot. `buildBookActivity`
 * merges that snapshot with the book's durable state and `BookGenerationActivity`
 * renders the result — the reducer keeps the UI presentational.
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

/**
 * Where one pipeline stage stands.
 *
 * Nothing but the state, because nothing but the state is read. The stage
 * used to carry a `label`, a `description` and a formatted `detail`, all of
 * them written for `BookProgressTimeline`'s six chips — and all of them
 * duplicating what `buildBookActivity` now derives from the book itself, in
 * the reader's own vocabulary rather than the pipeline's.
 */
export interface StageView {
  id: StageId;
  state: StageState;
}

/**
 * What the live stream knows about one chapter being written.
 *
 * The engine has always emitted this — `page_planned` carries the block types
 * the architect chose, and every block announces its start and its end. The
 * timeline threw all of it away and kept two running totals, so a reader
 * watching a chapter compile could see a percentage move but never *what* was
 * being written. This is the missing half.
 *
 * Live only, and deliberately so: the durable half (which chapters exist, and
 * which of them are done) comes from the book's own pages, which is why a
 * refresh mid-compile no longer empties the panel.
 */
export interface PageActivity {
  pageId: string;
  /** Block types the architect planned, in order. Empty until `page_planned`. */
  planned: string[];
  /** Blocks finished, successfully or not — the numerator of "3/5 blocks". */
  done: number;
  /** The block type being written right now, `""` between blocks. */
  current: string;
  /** Is the stream still reporting work on this chapter? */
  live: boolean;
  /** True between `page_planning` and `page_planned`. */
  planning: boolean;
}

/**
 * What the live stream has established about this run.
 *
 * Only what something reads. The predecessor also carried a running
 * `message` caption, an `updatedAt`, a `pageOrder`, a copy of `STAGE_ORDER`,
 * and eleven aggregate counters (`pagesPlanned`, `blocksReady`, `conceptEdges`,
 * `lastVerdict`, …) — the tallies `BookProgressTimeline` printed in its
 * footer strip. The chapter rows report their own progress now, so the
 * aggregates had no reader and every event was paying to maintain them.
 */
export interface BookProgress {
  /** Which book this run belongs to — guards against blending two runs. */
  bookId: string | null;
  stages: Record<StageId, StageView>;
  /** Per-chapter live detail, keyed by page id. */
  pages: Record<string, PageActivity>;
  /** When the first event of this run arrived — the run's clock. */
  startedAt: number;
  exploration: { queryCount: number; chunkCount: number };
  synthesis: { rounds: number; conceptNodes: number };
  critique: { rounds: number; issues: number };
}

export const STAGE_ORDER: StageId[] = [
  "ideation",
  "exploration",
  "synthesis",
  "critique",
  "overview",
  "compilation",
];


export function emptyBookProgress(): BookProgress {
  const stages = Object.fromEntries(
    STAGE_ORDER.map((id) => [
      id,
      { id, state: "pending" as StageState },
    ]),
  ) as Record<StageId, StageView>;
  return {
    bookId: null,
    stages,
    pages: {},
    startedAt: 0,
    exploration: { queryCount: 0, chunkCount: 0 },
    synthesis: { rounds: 0, conceptNodes: 0 },
    critique: { rounds: 0, issues: 0 },
  };
}


function patchStage(
  state: BookProgress,
  id: StageId,
  patch: Partial<StageView>,
): BookProgress {
  return {
    ...state,
    stages: { ...state.stages, [id]: { ...state.stages[id], ...patch } },
  };
}

function startStage(state: BookProgress, id: StageId): BookProgress {
  // Close out earlier stages that never reported an end, so the run always
  // reads in order even when an event is missed.
  let next = state;
  for (const sid of STAGE_ORDER) {
    if (sid === id) break;
    const s = next.stages[sid].state;
    if (s === "pending" || s === "running") {
      next = patchStage(next, sid, { state: "completed" });
    }
  }
  return patchStage(next, id, { state: "running" });
}

function completeStage(state: BookProgress, id: StageId): BookProgress {
  // A stage that already reported a failure stays failed: the pipeline still
  // emits stage_end on its way out of the `async with`, and letting that
  // overwrite the error would show a green tick for a sweep that found nothing.
  if (state.stages[id]?.state === "error") return state;
  return patchStage(state, id, { state: "completed" });
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

function asStrings(value: unknown): string[] {
  return Array.isArray(value) ? value.map(asString).filter(Boolean) : [];
}

/** Stop reporting live work on every chapter — the run ended or stopped. */
function settle(
  pages: Record<string, PageActivity>,
): Record<string, PageActivity> {
  const next: Record<string, PageActivity> = {};
  for (const [id, page] of Object.entries(pages)) {
    next[id] = page.live
      ? { ...page, live: false, planning: false, current: "" }
      : page;
  }
  return next;
}

/** Patch one chapter's live slice, registering it on first mention. */
function patchPage(
  state: BookProgress,
  pageId: string,
  patch: Partial<PageActivity>,
): BookProgress {
  if (!pageId) return state;
  const base: PageActivity = state.pages[pageId] ?? {
    pageId,
    planned: [],
    done: 0,
    current: "",
    live: false,
    planning: false,
  };
  return {
    ...state,
    pages: { ...state.pages, [pageId]: { ...base, ...patch } },
  };
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
  if (eventType === "__reset") return emptyBookProgress();

  // A book id that contradicts the one we're tracking means the stream moved
  // on; start clean rather than blending two runs into one timeline.
  const incomingBookId = asString(meta.book_id);
  if (incomingBookId && state.bookId && incomingBookId !== state.bookId) {
    state = emptyBookProgress();
  }

  let next: BookProgress = state;
  if (incomingBookId && next.bookId == null) {
    next = { ...next, bookId: incomingBookId };
  }
  // The run's clock starts at its first event, not at mount: the panel is
  // mounted for books that are not generating at all.
  if (!next.startedAt) next = { ...next, startedAt: Date.now() };
  const pageId = asString(meta.page_id);

  // STAGE_BEGIN / STAGE_END from generic stream events.
  if ((STAGE_ORDER as string[]).includes(stage)) {
    if (eventType === "stage_start") next = startStage(next, stage as StageId);
    if (eventType === "stage_end") next = completeStage(next, stage as StageId);
  }

  switch (rawKind) {
    case "proposal_ready":
      next = completeStage(startStage(next, "ideation"), "ideation");
      break;
    case "exploration_ready": {
      const coverage = meta.coverage as Record<string, unknown> | undefined;
      next = completeStage(startStage(next, "exploration"), "exploration");
      next = {
        ...next,
        exploration: {
          queryCount: asNumber(meta.queries),
          chunkCount: coverage
            ? Object.values(coverage).reduce<number>(
                (total, value) => total + asNumber(value),
                0,
              )
            : 0,
        },
      };
      break;
    }
    case "exploration_failed":
      // The stage still emits stage_end afterwards; the error wins so the
      // panel does not claim the sweep succeeded.
      next = patchStage(next, "exploration", { state: "error" });
      break;
    case "spine_round": {
      const isCritique = asString(meta.round).startsWith("critique");
      next = startStage(next, isCritique ? "critique" : "synthesis");
      next = isCritique
        ? {
            ...next,
            critique: {
              rounds: next.critique.rounds + 1,
              issues: asNumber(meta.issue_count),
            },
          }
        : {
            ...next,
            synthesis: { ...next.synthesis, rounds: next.synthesis.rounds + 1 },
          };
      break;
    }
    case "spine_ready":
      // Both synthesis and critique are done once the spine is ready.
      next = completeStage(startStage(next, "synthesis"), "synthesis");
      next = patchStage(next, "critique", { state: "completed" });
      next = {
        ...next,
        synthesis: {
          ...next.synthesis,
          conceptNodes: asNumber(meta.concept_node_count),
        },
      };
      break;
    case "page_compile_started":
      next = patchPage(startStage(next, "compilation"), pageId, { live: true });
      break;
    case "page_planning":
      next = patchPage(startStage(next, "compilation"), pageId, {
        live: true,
        planning: true,
      });
      break;
    case "page_planned":
      next = patchPage(startStage(next, "compilation"), pageId, {
        planned: asStrings(meta.block_types),
        planning: false,
        live: true,
      });
      break;
    case "block_started":
      next = patchPage(next, pageId, {
        current: asString(meta.block_type),
        live: true,
      });
      break;
    case "block_ready":
    case "block_error":
      // Both advance the count: "3/5 blocks" is how much of the chapter has
      // been attempted. Whether a block failed is the chapter's own status,
      // which the panel reads from the book rather than from the stream.
      next = patchPage(next, pageId, {
        done: (next.pages[pageId]?.done ?? 0) + 1,
        current: "",
      });
      break;
    case "page_compiled":
    case "page_ready":
      next = patchPage(startStage(next, "compilation"), pageId, {
        live: false,
        planning: false,
        current: "",
      });
      // The engine materialises the overview before any normal page, so the
      // first finished chapter also settles that stage.
      if (next.stages.overview.state !== "completed") {
        next = patchStage(next, "overview", { state: "completed" });
      }
      break;
    case "overview_ready":
      next = completeStage(startStage(next, "overview"), "overview");
      break;
    case "book_ready":
    case "compilation_complete":
      next = completeStage(next, "compilation");
      next = { ...next, pages: settle(next.pages) };
      break;
    case "compilation_paused":
      // Nothing is running any more, so no chapter row may keep breathing.
      next = { ...next, pages: settle(next.pages) };
      break;
    default:
      break;
  }

  // Stream-level error → mark whichever stage was running.
  if (eventType === "error") {
    const running = STAGE_ORDER.find(
      (id) => next.stages[id].state === "running",
    );
    if (running) next = patchStage(next, running, { state: "error" });
  }

  return next;
}
