/**
 * Public entry point for chat-history import. The user picks a `.claude` or
 * `.codex` folder; we detect which, scan it for projects/sessions, and (later)
 * parse the chosen sessions into the upload payload. All file reading happens in
 * the browser via the File System Access API — those files live on the user's
 * machine, not the server.
 */

import { parseClaudeSession, scanClaude } from "./claude-code";
import { parseCodexSession, scanCodex } from "./codex";
import { detectSource } from "./detect";
import { projectLabel } from "./shared";
import {
  type AgentScope,
  ImportScanError,
  type ImportSource,
  type NormalizedSession,
  type ScanResult,
  type SelectGroup,
  type SelectionUnit,
  type SessionRef,
} from "./types";

export * from "./types";
export { SOURCE_LABEL, epochMsToISODate, projectLabel } from "./shared";

export function isFileSystemAccessSupported(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.showDirectoryPicker === "function"
  );
}

/** Open the OS folder picker, then scan the chosen directory. */
export async function pickAndScan(): Promise<ScanResult> {
  if (!isFileSystemAccessSupported()) {
    throw new ImportScanError("unsupported_browser");
  }
  let root: FileSystemDirectoryHandle;
  try {
    root = await window.showDirectoryPicker!({
      id: "deeptutor-chat-import",
      mode: "read",
    });
  } catch {
    // User dismissed the picker.
    throw new ImportScanError("aborted");
  }
  return scanDirectory(root);
}

export async function scanDirectory(
  root: FileSystemDirectoryHandle,
): Promise<ScanResult> {
  const source = await detectSource(root);
  if (!source) throw new ImportScanError("not_recognized");
  const projects =
    source === "claude_code" ? await scanClaude(root) : await scanCodex(root);
  return { source, handle: root, projects };
}

/** The dimension a source is sliced by: Codex by day, Claude Code by project. */
export function selectionUnit(source: ImportSource): SelectionUnit {
  return source === "codex" ? "dates" : "projects";
}

/**
 * Flatten a scan's sessions into the togglable units the picker shows — Codex
 * by calendar day, Claude Code by project. Each unit's `key` is exactly what
 * lands in {@link AgentScope}, so the same value drives selection and the
 * later scope filter.
 */
export function buildSelectGroups(scan: ScanResult): SelectGroup[] {
  const refs = scan.projects.flatMap((p) => p.sessions);
  if (selectionUnit(scan.source) === "dates") {
    const byDate = new Map<string, SessionRef[]>();
    for (const ref of refs) {
      const key = ref.date || "(unknown)";
      const arr = byDate.get(key) ?? [];
      arr.push(ref);
      byDate.set(key, arr);
    }
    return Array.from(byDate.entries())
      .sort((a, b) => b[0].localeCompare(a[0]))
      .map(([key, sessions]) => ({ key, label: key, sessions }));
  }
  return scan.projects.map((p) => ({
    key: p.cwd,
    label: p.label || projectLabel(p.cwd),
    sublabel: p.cwd,
    sessions: p.sessions,
  }));
}

/**
 * Keep only the sessions whose selection unit is still in the agent's scope.
 * This is what makes a refresh respect the user's original picks while still
 * pulling in newly-created conversations inside chosen units.
 */
export function filterRefsByScope(
  refs: SessionRef[],
  scope: AgentScope,
): SessionRef[] {
  if (scope.kind === "all") return refs;
  if (scope.kind === "projects") {
    const set = new Set(scope.cwds);
    return refs.filter((r) => set.has(r.cwd));
  }
  const set = new Set(scope.days);
  return refs.filter((r) => set.has(r.date));
}

/** Fully parse the selected sessions; corrupt/unreadable ones are skipped
 *  rather than aborting the batch. */
export async function parseSessions(
  source: ImportSource,
  refs: SessionRef[],
  onProgress?: (done: number, total: number) => void,
): Promise<NormalizedSession[]> {
  const parser =
    source === "claude_code" ? parseClaudeSession : parseCodexSession;
  const out: NormalizedSession[] = [];
  let done = 0;
  for (const ref of refs) {
    try {
      const parsed = await parser(ref);
      if (parsed && parsed.messages.length) out.push(parsed);
    } catch {
      // skip this transcript
    }
    onProgress?.(++done, refs.length);
  }
  return out;
}
