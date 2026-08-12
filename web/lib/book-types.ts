// Type definitions mirroring deeptutor.book.models on the backend.
// Kept loose (Record<string, unknown>) where the payload is block-type
// specific so we don't have to keep these in lock-step.

export type BookStatus =
  | "draft"
  | "spine_ready"
  | "compiling"
  | "ready"
  | "error"
  | "archived";

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
  blocks: Block[];
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

export interface Book {
  id: string;
  title: string;
  description: string;
  status: BookStatus;
  proposal: BookProposal | null;
  knowledge_bases: string[];
  language: string;
  page_count: number;
  chapter_count: number;
  created_at: number;
  updated_at: number;
  metadata: Record<string, unknown> & {
    page_chat_sessions?: Record<string, string>;
  };
}

export interface Progress {
  book_id: string;
  current_page_id: string;
  visited_page_ids: string[];
  bookmarked_page_ids: string[];
  quiz_attempts: Array<{
    block_id: string;
    page_id: string;
    question_id: string;
    user_answer: string;
    is_correct: boolean;
    timestamp: number;
  }>;
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
