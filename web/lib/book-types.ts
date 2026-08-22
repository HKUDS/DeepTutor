// Type definitions mirroring deeptutor.book.models on the backend.
// Kept loose (Record<string, unknown>) where the payload is block-type
// specific so we don't have to keep these in lock-step.

export type BookStatus =
  | "draft"
  | "spine_ready"
  | "compiling"
  // Compilation stopped itself after repeated provider failures (quota, keys,
  // outage). Everything generated so far is intact and `resume` continues.
  | "paused"
  | "ready"
  | "error"
  | "archived";

/** How much prose the reader wants per chapter. Scales template word counts. */
export type BookDepth = "brief" | "standard" | "deep";

export type PageStatus =
  | "pending"
  | "planning"
  | "generating"
  | "ready"
  | "partial"
  | "error";

export type BlockStatus =
  | "pending"
  | "generating"
  | "ready"
  | "error"
  | "hidden";

export type BlockType =
  | "text"
  | "callout"
  | "quiz"
  | "user_note"
  | "figure"
  | "interactive"
  | "animation"
  | "code"
  | "timeline"
  | "flash_cards"
  | "deep_dive"
  | "section"
  | "concept_graph";

export type ContentType =
  | "theory"
  | "derivation"
  | "history"
  | "practice"
  | "concept"
  | "overview";

export interface ConceptNode {
  id: string;
  label: string;
  chapter_id: string;
  description: string;
  weight: number;
}

export interface ConceptEdge {
  src: string;
  dst: string;
  relation: "depends_on" | "extends" | "related" | string;
  rationale: string;
}

export interface ConceptGraph {
  nodes: ConceptNode[];
  edges: ConceptEdge[];
}

export interface SourceAnchor {
  kind: string;
  ref: string;
  snippet: string;
}

export interface Block {
  id: string;
  type: BlockType;
  status: BlockStatus;
  title: string;
  params: Record<string, unknown>;
  payload: Record<string, unknown>;
  source_anchors: SourceAnchor[];
  metadata: Record<string, unknown>;
  error: string;
  created_at: number;
  updated_at: number;
}

export interface Page {
  id: string;
  book_id: string;
  chapter_id: string;
  title: string;
  learning_objectives: string[];
  content_type: ContentType;
  status: PageStatus;
  order: number;
  /** Empty when the page was fetched via a summary (`include_blocks=false`). */
  blocks: Block[];
  /** Present on summaries so callers can show a count without the payloads. */
  block_count?: number;
  links: Array<{ target_page_id: string; relation: string; label: string }>;
  parent_page_id: string;
  error: string;
  created_at: number;
  updated_at: number;
}

export interface Chapter {
  id: string;
  title: string;
  learning_objectives: string[];
  content_type: ContentType;
  source_anchors: SourceAnchor[];
  prerequisites: string[];
  page_ids: string[];
  summary: string;
  order: number;
  /** Engine-injected overview chapter — not user-authored. */
  auto_overview?: boolean;
  /** Spawned by a deep dive; lives outside the book's chapter structure. */
  deep_dive?: boolean;
}

export interface Spine {
  book_id: string;
  chapters: Chapter[];
  version: number;
  updated_at: number;
  concept_graph?: ConceptGraph;
  exploration_summary?: string;
}

export interface BookProposal {
  title: string;
  description: string;
  scope: string;
  target_level: string;
  estimated_chapters: number;
  rationale: string;
}

/** How far the reader has got. Attached by the list endpoint. */
export interface ReadingSummary {
  current_page_id: string;
  visited_pages: number;
  total_pages: number;
  percent: number;
}

export interface Book {
  id: string;
  title: string;
  description: string;
  status: BookStatus;
  proposal: BookProposal | null;
  knowledge_bases: string[];
  language: string;
  depth?: BookDepth;
  page_count: number;
  chapter_count: number;
  created_at: number;
  updated_at: number;
  metadata: Record<string, unknown> & {
    page_chat_sessions?: Record<string, string>;
    /** Why compilation paused — set alongside `status: "paused"`. */
    pause_reason?: string;
  };
  /** Present on list responses only. */
  reading?: ReadingSummary;
}

export interface QuizAttempt {
  block_id: string;
  page_id: string;
  question_id: string;
  user_answer: string;
  /** `null` when a written answer was revealed but never self-graded. */
  is_correct: boolean | null;
  timestamp: number;
}

export type LearningCaptureStatus =
  | "captured"
  | "drafted"
  | "pending_confirmation"
  | "approved"
  | "delivered"
  | "imported"
  | "rejected";

export interface LearningCapture {
  id: string;
  book_id: string;
  page_id: string;
  block_id: string;
  capture_type: string;
  source_text: string;
  context_before: string;
  context_after: string;
  source_locator: string;
  book_title: string;
  chapter_title: string;
  user_note: string;
  content_hash: string;
  status: LearningCaptureStatus;
  version: number;
  rejected_reason: string;
  created_at: number;
  updated_at: number;
}

export interface Progress {
  book_id: string;
  current_page_id: string;
  visited_page_ids: string[];
  bookmarked_page_ids: string[];
  quiz_attempts: QuizAttempt[];
  weak_chapters: string[];
  score: number;
  updated_at: number;
}

export interface BookDetail {
  book: Book;
  spine: Spine | null;
  pages: Page[];
  progress: Progress;
}
