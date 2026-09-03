import test from "node:test";
import assert from "node:assert/strict";

import { buildBookActivity, formatElapsed } from "../lib/book-activity";
import {
  emptyBookProgress,
  reduceBookEvent,
  type BookProgress,
} from "../lib/book-progress";
import type { BookWsEvent } from "../lib/book-api";
import type { Book, GenerationSummary, Page } from "../lib/book-types";

/** Keys through unchanged, so assertions read as the source strings. */
const t = (key: string, options?: Record<string, unknown>) => {
  if (!options) return key;
  return key.replace(/\{\{(\w+)\}\}/g, (_, name) =>
    String(options[name] ?? `{{${name}}}`),
  );
};

function book(overrides: Partial<Book> = {}): Book {
  return {
    id: "bk_1",
    revision: 1,
    title: "A book",
    description: "",
    status: "compiling",
    proposal: {
      title: "A book",
      description: "",
      scope: "",
      target_level: "intermediate",
      estimated_chapters: 2,
      rationale: "",
    },
    knowledge_bases: [],
    language: "en",
    page_count: 2,
    chapter_count: 2,
    created_at: 1_700_000_000,
    updated_at: 1_700_000_000,
    metadata: {},
    ...overrides,
  } as Book;
}

function page(overrides: Partial<Page> = {}): Page {
  return {
    id: "pg_1",
    book_id: "bk_1",
    chapter_id: "ch_1",
    title: "Chapter one",
    learning_objectives: [],
    content_type: "theory",
    status: "pending",
    order: 0,
    blocks: [],
    links: [],
    parent_page_id: "",
    error: "",
    created_at: 1_700_000_000,
    updated_at: 1_700_000_000,
    ...overrides,
  } as Page;
}

function generation(overrides: Partial<GenerationSummary> = {}): GenerationSummary {
  return {
    book_id: "bk_1",
    status: "compiling",
    can_resume: false,
    pause_reason: "",
    source_quality: null,
    working: true,
    interrupted: false,
    pages: { total: 2 },
    failed_blocks: 0,
    retryable_pages: 0,
    failure_categories: {},
    ...overrides,
  } as GenerationSummary;
}

function feed(events: Array<Partial<BookWsEvent> & { metadata?: unknown }>): BookProgress {
  return events.reduce(
    (state, event) => reduceBookEvent(state, event as BookWsEvent),
    emptyBookProgress(),
  );
}

test("formatElapsed spells out minutes, and hours once a compile runs that long", () => {
  assert.equal(formatElapsed(9), "0:09");
  assert.equal(formatElapsed(134), "2:14");
  assert.equal(formatElapsed(3671), "1:01:11");
});

test("a queued chapter reads as queued, not as finished or broken", () => {
  const activity = buildBookActivity({
    book: book(),
    pages: [page({ id: "pg_a", status: "ready", block_count: 4 }), page({ id: "pg_b", order: 1 })],
    generation: generation(),
    progress: emptyBookProgress(),
    t,
  });

  assert.equal(activity.chapters.length, 2);
  assert.equal(activity.chapters[0].detail, "4 blocks");
  assert.equal(activity.chapters[1].detail, "Queued");
  assert.equal(activity.chaptersReady, 1);
  assert.equal(activity.chaptersTotal, 2);
});

test("the live stream names the block being written, over the durable status", () => {
  // Exactly the sequence the compiler emits, in order.
  const progress = feed([
    { type: "progress", metadata: { kind: "page_compile_started", page_id: "pg_b", title: "Chapter two" } },
    { type: "progress", metadata: { kind: "page_planning", page_id: "pg_b" } },
    { type: "progress", metadata: { kind: "page_planned", page_id: "pg_b", block_types: ["text", "quiz", "figure"] } },
    { type: "progress", metadata: { kind: "block_ready", page_id: "pg_b", block_type: "text" } },
    { type: "progress", metadata: { kind: "block_started", page_id: "pg_b", block_type: "quiz" } },
  ]);

  const activity = buildBookActivity({
    // The manifest still says pending: the stream is ahead of it by design.
    book: book(),
    pages: [page({ id: "pg_b", title: "Chapter two", status: "pending" })],
    generation: generation(),
    progress,
    t,
  });

  const row = activity.chapters[0];
  assert.equal(row.state, "running");
  assert.equal(row.detail, "Writing quiz · 1/3 blocks");
  assert.equal(row.blocks?.length, 3);
  assert.equal(row.blocks?.[1].state, "running");
  assert.equal(activity.phase, "compilation");
  assert.equal(activity.live, true);
});

test("pausing stops every chapter reporting live work", () => {
  const progress = feed([
    { type: "progress", metadata: { kind: "page_compile_started", page_id: "pg_b" } },
    { type: "progress", metadata: { kind: "block_started", page_id: "pg_b", block_type: "text" } },
    { type: "progress", metadata: { kind: "compilation_paused", page_id: "", book_id: "bk_1" } },
  ]);

  assert.equal(progress.pages["pg_b"].live, false);
  assert.equal(progress.pages["pg_b"].current, "");

  const activity = buildBookActivity({
    book: book({ status: "paused" }),
    pages: [page({ id: "pg_b" })],
    generation: generation({ status: "paused", working: false, can_resume: true }),
    progress,
    t,
  });
  assert.equal(activity.phase, "paused");
  assert.equal(activity.live, false);
  assert.equal(activity.label, "Generation paused");
  assert.equal(activity.runStartedAt, null);
});

test("a compile the backend lost reads as stopped, not as still working", () => {
  const activity = buildBookActivity({
    book: book({ status: "compiling" }),
    pages: [page({ id: "pg_b" })],
    generation: generation({ working: false, interrupted: true, retryable_pages: 1 }),
    progress: emptyBookProgress(),
    t,
  });

  assert.equal(activity.phase, "interrupted");
  assert.equal(activity.live, false);
  assert.equal(activity.label, "Generation stopped unexpectedly");
});

test("the run clock comes from the engine, so a reload does not restart it", () => {
  const startedAt = Date.now() / 1000 - 134;
  const activity = buildBookActivity({
    book: book(),
    pages: [page({ id: "pg_b", status: "generating" })],
    // No events at all: this is the state right after a reload.
    generation: generation({ started_at: startedAt }),
    progress: emptyBookProgress(),
    t,
  });

  assert.equal(activity.live, true);
  // The builder hands back *when* the run started; the elapsed seconds are
  // the caller's to derive, on its own clock, so the strip's timer keeps
  // ticking between events instead of stalling until the next one lands.
  assert.ok(activity.runStartedAt !== null, "expected a run start");
  const elapsed = Math.round((Date.now() - activity.runStartedAt!) / 1000);
  assert.ok(Math.abs(elapsed - 134) <= 1, `expected ~134s, got ${elapsed}`);
});

test("preparation rows survive with no stream at all — they come from the book", () => {
  const activity = buildBookActivity({
    book: book({
      metadata: { source_quality: { status: "ready", requested_kbs: [], chunk_count: 0, warnings: [] } },
    }),
    pages: [
      page({ id: "pg_ov", content_type: "overview", status: "ready" }),
      page({ id: "pg_b", order: 1 }),
    ],
    spine: {
      book_id: "bk_1",
      chapters: [
        { id: "ch_ov", title: "Overview", learning_objectives: [], content_type: "overview", source_anchors: [], prerequisites: [], page_ids: ["pg_ov"], summary: "", order: 0, auto_overview: true },
        { id: "ch_1", title: "Chapter one", learning_objectives: [], content_type: "theory", source_anchors: [], prerequisites: [], page_ids: ["pg_b"], summary: "", order: 1 },
      ],
      version: 1,
      updated_at: 0,
    },
    generation: generation(),
    progress: emptyBookProgress(),
    t,
  });

  const ids = activity.preparation.map((row) => row.id);
  assert.deepEqual(ids, ["ideation", "exploration", "synthesis", "overview"]);
  // "No sources selected" is why the book reads the way it does, so it is said
  // outright rather than left as an empty row.
  const sweep = activity.preparation.find((row) => row.id === "exploration");
  assert.equal(sweep?.detail, "No sources selected — general knowledge");
  assert.equal(sweep?.state, "done");
  // The overview chapter is not one of the reader's chapters.
  assert.equal(activity.chapters.length, 1);
});

test("a failed sweep is reported as failed, not silently skipped", () => {
  const activity = buildBookActivity({
    book: book({ metadata: { exploration_failed: true } }),
    pages: [page()],
    generation: generation(),
    progress: emptyBookProgress(),
    t,
  });

  const sweep = activity.preparation.find((row) => row.id === "exploration");
  assert.equal(sweep?.state, "error");
  assert.equal(sweep?.detail, "Retrieval failed — written from the plan alone");
});
