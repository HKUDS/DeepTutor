/**
 * What a book is doing right now, as activity rows.
 * ==================================================
 *
 * One pure function turning a book's *durable* state (its pages, its spine,
 * what the sweep found) plus the *live* event stream into the same shape
 * chat's reasoning trace renders: a phase, a clock, and one row per real
 * action.
 *
 * Why both halves
 * ---------------
 *
 * The predecessor derived everything from the WebSocket stream, and the
 * stream's history lives in memory with a 400-event cap. So a reload
 * mid-compile — or any backend restart — left a book whose manifest still
 * said `compiling` with a Pause button and no progress whatsoever. The
 * durable half fixes that: which chapters exist and which are written is a
 * fact on disk, and it is most of what a reader wants to know. The stream
 * only refines it, with the one thing disk cannot answer — which block is
 * being written this second.
 *
 * Why no percentage
 * -----------------
 *
 * The old readout was `completed_stages / 6`, counting a running stage as a
 * half, which is how a book that had just started announced "8%". It tracked
 * neither time nor work, and there is no honest denominator available before
 * the architect has planned each chapter's blocks. So this reports what it
 * actually knows: the phase, the chapter count, and elapsed time — the same
 * three things a chat turn reports.
 */

import type { OrbState } from "@/vendor/thinking-orbs";

import type { ActivityState } from "@/shared/ui/activity-state";

import type { BookProgress, StageId } from "@/lib/book-progress";
import type { Book, GenerationSummary, Page, Spine } from "@/lib/book-types";

export type Translate = (key: string, options?: Record<string, unknown>) => string;

/** Where the book as a whole stands. */
export type BookPhase =
  | StageId
  | "paused"
  /** Says compiling, nothing is compiling it. */
  | "interrupted"
  | "done";

/** One line of the panel. */
export interface BookActivityRow {
  id: string;
  /** Names the action — "Sweep your sources", "01 · Recursive architecture". */
  title: string;
  /** The concrete thing it touched, already formatted. */
  detail: string;
  state: ActivityState;
  /** Chapter rows carry their page so the row can open it. */
  pageId?: string;
  /**
   * Owed work that has not begun. Distinct from `state: "done"`, which a
   * queued chapter also carries — the activity vocabulary has one resting
   * state and cannot tell "finished" from "not started", so the callers that
   * need to (the history layer, which shows only what is finished) get told.
   */
  queued?: boolean;
  /** Second level: the blocks this chapter is made of. */
  blocks?: BookActivityBlock[];
}

export interface BookActivityBlock {
  key: string;
  label: string;
  state: ActivityState;
}

export interface BookActivity {
  phase: BookPhase;
  /** True while work is genuinely in flight. */
  live: boolean;
  /** The header line. */
  label: string;
  orb: OrbState;
  orbSpeed: number;
  /**
   * Epoch ms this run started, or `null` when there is nothing to time.
   *
   * The elapsed *seconds* deliberately are not computed here. This whole
   * value is memoised on the book and the event stream, so a clock derived
   * inside it only advanced when an event happened to land — which is why
   * the timer sat still for the length of every stage and then jumped.
   * Callers read `Date.now()` themselves, on every render they choose to do.
   */
  runStartedAt: number | null;
  /** Preparation rows: plan, sweep, spine, self-review, overview. */
  preparation: BookActivityRow[];
  /** One row per chapter, in reading order. */
  chapters: BookActivityRow[];
  /** Chapters written out of the chapters the spine asked for. */
  chaptersReady: number;
  chaptersTotal: number;
  /** Nothing worth showing — no run, and no book being prepared. */
  empty: boolean;
}

/**
 * Which orb animation stands in for each phase.
 *
 * Semantic, like chat's mapping: the sweep gets the scanning globe, the
 * spine gets the plaiting strands, the concept map gets the constellation
 * wiring itself, and writing chapters gets the undulating sash. A reader who
 * has watched one book learns to read the phase off the motion.
 */
const PHASE_ORB: Record<BookPhase, OrbState> = {
  ideation: "shaping",
  exploration: "searching",
  synthesis: "weaving",
  critique: "solving",
  overview: "connecting",
  compilation: "composing",
  paused: "breathing",
  interrupted: "breathing",
  done: "breathing",
};

/** A settled phase keeps breathing, at half pace: "still here", not "still working". */
const RESTING_SPEED = 0.5;

const PAGE_STATE: Record<string, ActivityState> = {
  ready: "done",
  partial: "error",
  error: "error",
  planning: "running",
  generating: "running",
  pending: "done",
};

/** `mm:ss`, or `h:mm:ss` past an hour — a book compile can run that long. */
export function formatElapsed(total: number): string {
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  const mm = String(minutes).padStart(hours ? 2 : 1, "0");
  const ss = String(secs).padStart(2, "0");
  return hours ? `${hours}:${mm}:${ss}` : `${mm}:${ss}`;
}

/** The reader-facing name of a block type, via the same keys the editor uses. */
function blockLabel(type: string, t: Translate): string {
  return type ? t(type) : "";
}

function countConcepts(spine: Spine | null | undefined): number {
  const nodes = spine?.concept_graph?.nodes;
  return Array.isArray(nodes) ? nodes.length : 0;
}

/**
 * Rows for everything that happens before the first chapter is written.
 *
 * Each row's state comes from durable evidence first (a proposal exists, the
 * sweep left a `source_quality` report, a spine exists) and falls back to the
 * live stage map, so these survive a reload exactly like the chapter rows do.
 */
function preparationRows(
  book: Book | null,
  spine: Spine | null | undefined,
  pages: Page[],
  progress: BookProgress,
  t: Translate,
): BookActivityRow[] {
  const stage = (id: StageId) => progress.stages[id];
  const rows: BookActivityRow[] = [];

  // ── The plan ───────────────────────────────────────────────────────
  const proposal = book?.proposal || null;
  const plannedChapters =
    spine?.chapters?.filter((chapter) => !chapter.auto_overview).length ||
    proposal?.estimated_chapters ||
    0;
  const ideationDone = Boolean(proposal) || stage("ideation").state === "completed";
  rows.push({
    id: "ideation",
    title: t("Draft the plan"),
    detail: plannedChapters
      ? t("{{count}} chapters", { count: plannedChapters })
      : ideationDone
        ? ""
        : t("Reading your intent…"),
    state: ideationDone ? "done" : stage("ideation").state === "error" ? "error" : "running",
  });

  // ── The source sweep ───────────────────────────────────────────────
  const quality = (book?.metadata?.source_quality as
    | { chunk_count?: number; requested_kbs?: string[]; warnings?: string[] }
    | undefined) || undefined;
  const explorationFailed =
    Boolean(book?.metadata?.exploration_failed) || stage("exploration").state === "error";
  const sweepQueries = progress.exploration.queryCount;
  const sweepChunks = progress.exploration.chunkCount || quality?.chunk_count || 0;
  // No sources selected is not a failure and not a silence — it is why the
  // book reads the way it does, so it gets said outright.
  const noSources =
    !!quality &&
    !(quality.requested_kbs || []).length &&
    !sweepChunks &&
    !explorationFailed;
  const sweepDone = Boolean(quality) || stage("exploration").state === "completed";
  if (sweepDone || stage("exploration").state !== "pending" || explorationFailed) {
    rows.push({
      id: "exploration",
      title: t("Sweep your sources"),
      detail: explorationFailed
        ? t("Retrieval failed — written from the plan alone")
        : noSources
          ? t("No sources selected — general knowledge")
          : sweepQueries
            ? t("{{queries}} queries · {{chunks}} chunks", {
                queries: sweepQueries,
                chunks: sweepChunks,
              })
            : sweepChunks
              ? t("{{count}} chunks", { count: sweepChunks })
              : t("Searching your knowledge bases…"),
      state: explorationFailed ? "error" : sweepDone ? "done" : "running",
    });
  }

  // ── The spine ──────────────────────────────────────────────────────
  const spineDone = Boolean(spine?.chapters?.length) || stage("synthesis").state === "completed";
  const concepts = countConcepts(spine) || progress.synthesis.conceptNodes;
  rows.push({
    id: "synthesis",
    title: t("Synthesise the spine"),
    detail: spineDone
      ? concepts
        ? t("{{chapters}} chapters · {{concepts}} concepts", {
            chapters: plannedChapters,
            concepts,
          })
        : t("{{count}} chapters", { count: plannedChapters })
      : progress.synthesis.rounds
        ? t("Round {{count}}", { count: progress.synthesis.rounds })
        : t("Drafting the chapter order…"),
    state: spineDone ? "done" : stage("synthesis").state === "running" ? "running" : "done",
  });

  // ── Self-review, only when it actually ran ─────────────────────────
  if (progress.critique.rounds > 0) {
    rows.push({
      id: "critique",
      title: t("Self-review the spine"),
      // "1 round · 0 issues" reads as a measurement that came up empty. It is
      // the opposite: the review found nothing to change, which is the good
      // outcome and deserves saying so.
      detail: progress.critique.issues
        ? t("{{rounds}} rounds · {{issues}} issues", {
            rounds: progress.critique.rounds,
            issues: progress.critique.issues,
          })
        : t("{{count}} rounds · nothing to change", {
            count: progress.critique.rounds,
          }),
      state: stage("critique").state === "running" ? "running" : "done",
    });
  }

  // ── The overview chapter ───────────────────────────────────────────
  const overview = pages.find((page) => page.content_type === "overview");
  if (overview || stage("overview").state !== "pending") {
    const state: ActivityState = overview
      ? PAGE_STATE[overview.status] || "done"
      : stage("overview").state === "running"
        ? "running"
        : "done";
    rows.push({
      id: "overview",
      title: t("Build the overview"),
      detail:
        overview && overview.status === "ready"
          ? t("Concept map · chapter index")
          : state === "running"
            ? t("Mapping the chapters…")
            : "",
      state,
      pageId: overview?.id,
    });
  }

  return rows;
}

/** One row per chapter: durable status, live block detail. */
function chapterRows(
  pages: Page[],
  progress: BookProgress,
  t: Translate,
): BookActivityRow[] {
  return pages
    .filter((page) => page.content_type !== "overview" && !page.parent_page_id)
    .slice()
    .sort((a, b) => a.order - b.order)
    .map((page, index) => {
      const live = progress.pages[page.id];
      const durableState = PAGE_STATE[page.status] || "done";
      // The stream is ahead of the manifest by design — a chapter reports
      // block-by-block long before its page is saved as ready.
      const state: ActivityState =
        live?.live && durableState !== "error" ? "running" : durableState;
      const blockCount = page.block_count ?? page.blocks.length;
      const planned = live?.planned?.length || 0;

      let detail = "";
      if (state === "error") {
        detail = page.error
          ? page.error.slice(0, 90)
          : t("Some blocks failed");
      } else if (live?.planning) {
        detail = t("Planning the blocks…");
      } else if (state === "running") {
        const written = live?.done ?? 0;
        const current = blockLabel(live?.current || "", t);
        const of = planned
          ? t("{{done}}/{{total}} blocks", { done: written, total: planned })
          : t("{{count}} blocks", { count: written });
        detail = current ? `${t("Writing {{block}}", { block: current })} · ${of}` : of;
      } else if (page.status === "pending") {
        detail = t("Queued");
      } else if (blockCount) {
        detail = t("{{count}} blocks", { count: blockCount });
      }

      // Second level: the blocks the architect planned, with the ones already
      // written marked off. Only worth opening while it is being written —
      // a finished chapter's blocks are the chapter itself, one click away.
      const blocks: BookActivityBlock[] | undefined =
        state === "running" && planned
          ? live!.planned.map((type, position) => ({
              key: `${page.id}:${position}`,
              label: blockLabel(type, t),
              state:
                position < (live!.done ?? 0)
                  ? "done"
                  : type === live!.current
                    ? "running"
                    : "done",
            }))
          : undefined;

      return {
        id: page.id,
        pageId: page.id,
        title: `${String(index + 1).padStart(2, "0")} · ${page.title || t("Untitled")}`,
        detail,
        state,
        queued: state !== "running" && page.status === "pending",
        blocks,
      };
    });
}

/**
 * The whole panel, from durable state plus the live stream.
 *
 * `now` is a parameter so the caller owns the clock (one interval per panel,
 * not one per row) and tests do not have to wait for wall time.
 */
export function buildBookActivity({
  book,
  pages,
  spine,
  generation,
  progress,
  t,
}: {
  book: Book | null;
  pages: Page[];
  spine?: Spine | null;
  /**
   * The backend's own read of the run, from `GET /books/{id}`. It is the only
   * source that can tell "compiling" from "was compiling when the process
   * died", because that answer lives in the runtime table, not on disk.
   */
  generation?: GenerationSummary | null;
  progress: BookProgress;
  t: Translate;
}): BookActivity {
  const status = book?.status;
  const chapters = chapterRows(pages, progress, t);
  const written = pages.filter(
    (page) => page.content_type !== "overview" && page.status === "ready",
  ).length;
  const chaptersTotal = chapters.length;

  const preparation = preparationRows(book || null, spine, pages, progress, t);
  const liveChapter = chapters.find((row) => row.state === "running");
  const runningPrep = preparation.find((row) => row.state === "running");

  // Whether anything is actually in flight. The backend's own answer wins
  // when we have it — it knows whether a worker exists, which is the one
  // question a stored status cannot answer.
  const backendWorking = generation?.working;
  const interrupted = Boolean(generation?.interrupted);
  const streamLive = Boolean(liveChapter || runningPrep);
  const live =
    status === "paused" || interrupted
      ? false
      : backendWorking === undefined
        ? streamLive || status === "compiling"
        : backendWorking || streamLive;

  let phase: BookPhase;
  if (status === "paused") phase = "paused";
  else if (interrupted) phase = "interrupted";
  else if (liveChapter || status === "compiling") phase = "compilation";
  else if (runningPrep) phase = runningPrep.id as StageId;
  else if (status === "ready") phase = "done";
  else phase = "compilation";

  let label: string;
  if (phase === "paused") {
    label = t("Generation paused");
  } else if (phase === "interrupted") {
    label = t("Generation stopped unexpectedly");
  } else if (phase === "done" || (!live && written >= chaptersTotal && chaptersTotal > 0)) {
    label = t("{{count}} chapters written", { count: written });
  } else if (liveChapter) {
    label = t("Writing {{title}}", { title: liveChapter.title.replace(/^\d+ · /, "") });
  } else if (runningPrep) {
    label = runningPrep.title;
  } else if (chaptersTotal) {
    // The chapter counter renders beside this line, so saying "Chapter 1 of
    // 2" here printed the same fact twice on one row. Name the work instead.
    label = t("Writing the remaining chapters");
  } else {
    label = t("Preparing your book");
  }

  const settledPhase = !live;
  /**
   * How long this run has been going.
   *
   * The engine stamps `started_at` when it starts or resumes compiling, so
   * this is the same number for every viewer and survives a reload. Only the
   * ideation stretch — before any book exists to stamp — falls back to the
   * first event this tab saw, which is exactly when that run did start.
   */
  const runStart = generation?.started_at
    ? generation.started_at * 1000
    : // Only when this tab actually watched the run start. The stream replays
      // its recent history on every (re)connect, so on a reload
      // `progress.startedAt` is simply "now" — timing from it would report
      // how long the page had been open and call it the run's duration.
      streamLive
      ? progress.startedAt || 0
      : 0;

  return {
    phase,
    live,
    label,
    orb: PHASE_ORB[phase],
    orbSpeed: settledPhase ? RESTING_SPEED : 1,
    runStartedAt: live && runStart ? runStart : null,
    preparation,
    chapters,
    chaptersReady: written,
    chaptersTotal,
    empty: !chaptersTotal && !book?.proposal && progress.startedAt === 0,
  };
}
