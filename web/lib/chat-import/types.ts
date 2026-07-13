/**
 * Shared types for importing external coding-CLI chat histories.
 *
 * The pipeline is two passes: a cheap **scan** that lists projects/sessions for
 * selection, and a full **parse** of only the chosen sessions into the
 * {@link NormalizedSession} shape that mirrors the backend Pydantic models.
 */

/** Provider whose on-disk chat history we know how to read. */
export type ImportSource = "claude_code" | "codex";

/**
 * A conversation discovered during the scan pass — enough metadata to list and
 * select it without a full parse. `handle` is read again at import time.
 */
export interface SessionRef {
  externalId: string;
  provisionalTitle: string;
  cwd: string;
  /** Local calendar day `YYYY-MM-DD`. Claude Code derives it from the file
   *  mtime; Codex reads it from the `sessions/YYYY/MM/DD` directory path. This
   *  is the selection unit for Codex (see {@link AgentScope}). */
  date: string;
  /** epoch milliseconds (File.lastModified). */
  lastModified: number;
  sizeBytes: number;
  handle: FileSystemFileHandle;
}

/** Sessions sharing one working directory — what the UI presents as a project. */
export interface ProjectGroup {
  cwd: string;
  label: string;
  sessions: SessionRef[];
}

/**
 * What an agent "owns" — the set of selection units the user picked at import.
 * Sync re-scans the folder but keeps only sessions whose unit is still in
 * scope, so new conversations inside chosen units flow in while everything
 * else stays out. `all` is the legacy / unrestricted scope (no filtering).
 */
export type AgentScope =
  | { kind: "all" }
  | { kind: "projects"; cwds: string[] }
  | { kind: "dates"; days: string[] };

/** The dimension a source is sliced by when picking what an agent imports. */
export type SelectionUnit = "projects" | "dates";

/** One togglable unit in the import/scope picker (a project or a day). */
export interface SelectGroup {
  /** Matches the value stored in {@link AgentScope} (a cwd or a `YYYY-MM-DD`). */
  key: string;
  label: string;
  sublabel?: string;
  sessions: SessionRef[];
}

export interface ScanResult {
  source: ImportSource;
  /** The picked directory handle — persisted so the agent can be re-synced. */
  handle: FileSystemDirectoryHandle;
  projects: ProjectGroup[];
}

/** One message in the normalized upload payload (mirrors the backend model). */
export interface NormalizedMessage {
  role: "user" | "assistant";
  content: string;
  /** epoch seconds; omitted when the source row carried no timestamp. */
  created_at?: number;
  metadata?: Record<string, unknown>;
}

/** A conversation ready to POST to `/api/v1/imports/chat-history`. */
export interface NormalizedSession {
  external_id: string;
  title: string;
  source_cwd: string;
  /** epoch seconds. */
  created_at: number;
  updated_at: number;
  messages: NormalizedMessage[];
}

export type ImportScanErrorCode =
  | "unsupported_browser"
  | "not_recognized"
  | "aborted";

export class ImportScanError extends Error {
  code: ImportScanErrorCode;
  constructor(code: ImportScanErrorCode, message?: string) {
    super(message ?? code);
    this.name = "ImportScanError";
    this.code = code;
  }
}
