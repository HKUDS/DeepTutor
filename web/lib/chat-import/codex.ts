/**
 * Codex adapter. Sessions live at
 * `~/.codex/sessions/YYYY/MM/DD/rollout-<ts>-<uuid>.jsonl`, partitioned by date
 * rather than project, so we read each file's `session_meta.cwd` and group by
 * it ourselves. We use the clean `event_msg` layer (user_message / agent_message)
 * for the transcript and skip the lower-level response items, reasoning, and
 * sub-agent (`thread_source: "subagent"`) sessions.
 */

import { iterLines, parseJsonl, readHead } from "./streaming";
import {
  cleanText,
  deriveTitle,
  epochMsToISODate,
  isoToEpochSeconds,
  projectLabel,
} from "./shared";
import type {
  NormalizedMessage,
  NormalizedSession,
  ProjectGroup,
  SessionRef,
} from "./types";

const SCAN_HEAD_BYTES = 64 * 1024;

interface CodexLine {
  timestamp?: string;
  type?: string;
  payload?: Record<string, unknown>;
}

function readMeta(lines: CodexLine[]): {
  cwd: string;
  id: string;
  isSubagent: boolean;
} {
  const meta = lines.find((l) => l.type === "session_meta")?.payload ?? {};
  return {
    cwd: typeof meta.cwd === "string" ? meta.cwd : "",
    id: typeof meta.id === "string" ? meta.id : "",
    isSubagent: meta.thread_source === "subagent",
  };
}

function eventMessage(line: CodexLine): NormalizedMessage | null {
  if (line.type !== "event_msg") return null;
  const p = line.payload ?? {};
  let role: "user" | "assistant";
  if (p.type === "user_message") role = "user";
  else if (p.type === "agent_message") role = "assistant";
  else return null;
  const content = cleanText(typeof p.message === "string" ? p.message : "");
  if (!content) return null;
  const created = isoToEpochSeconds(line.timestamp, 0);
  return { role, content, created_at: created || undefined };
}

/** A scanned file plus the `YYYY-MM-DD` recovered from its directory trail. */
interface CodexFile {
  handle: FileSystemFileHandle;
  date: string;
}

/** Turn a `sessions/2026/06/14` directory trail into `2026-06-14`. */
function dateFromTrail(trail: string[]): string {
  const nums = trail.filter((seg) => /^\d+$/.test(seg));
  if (nums.length < 3) return "";
  const [y, m, d] = nums;
  return `${y}-${m.padStart(2, "0")}-${d.padStart(2, "0")}`;
}

async function walkJsonl(
  dir: FileSystemDirectoryHandle,
  out: CodexFile[],
  trail: string[] = [],
): Promise<void> {
  for await (const entry of dir.values()) {
    if (entry.kind === "directory") {
      await walkJsonl(entry as FileSystemDirectoryHandle, out, [
        ...trail,
        entry.name,
      ]);
    } else if (entry.name.endsWith(".jsonl")) {
      out.push({
        handle: entry as FileSystemFileHandle,
        date: dateFromTrail(trail),
      });
    }
  }
}

export async function scanCodex(
  root: FileSystemDirectoryHandle,
): Promise<ProjectGroup[]> {
  const sessionsDir = await root.getDirectoryHandle("sessions");
  const files: CodexFile[] = [];
  await walkJsonl(sessionsDir, files);

  const byCwd = new Map<string, SessionRef[]>();
  for (const { handle, date } of files) {
    const file = await handle.getFile();
    const head = parseJsonl(
      await readHead(file, SCAN_HEAD_BYTES),
    ) as CodexLine[];
    const meta = readMeta(head);
    if (meta.isSubagent) continue;
    const cwd = meta.cwd || "(unknown)";
    const firstUser = head.map(eventMessage).find((m) => m?.role === "user");
    const ref: SessionRef = {
      externalId: meta.id || handle.name.replace(/\.jsonl$/, ""),
      provisionalTitle: firstUser ? deriveTitle(firstUser.content) : "",
      cwd,
      date: date || epochMsToISODate(file.lastModified),
      lastModified: file.lastModified,
      sizeBytes: file.size,
      handle,
    };
    const arr = byCwd.get(cwd) ?? [];
    arr.push(ref);
    byCwd.set(cwd, arr);
  }

  const groups: ProjectGroup[] = [];
  for (const [cwd, sessions] of byCwd) {
    sessions.sort((a, b) => b.lastModified - a.lastModified);
    groups.push({ cwd, label: projectLabel(cwd), sessions });
  }
  groups.sort(
    (a, b) =>
      (b.sessions[0]?.lastModified ?? 0) - (a.sessions[0]?.lastModified ?? 0),
  );
  return groups;
}

export async function parseCodexSession(
  ref: SessionRef,
): Promise<NormalizedSession | null> {
  const file = await ref.handle.getFile();
  const messages: NormalizedMessage[] = [];
  let cwd = ref.cwd;
  let isSubagent = false;

  for await (const line of iterLines(file)) {
    let rec: CodexLine;
    try {
      rec = JSON.parse(line) as CodexLine;
    } catch {
      continue;
    }
    if (rec.type === "session_meta") {
      const p = rec.payload ?? {};
      if (typeof p.cwd === "string") cwd = p.cwd;
      if (p.thread_source === "subagent") isSubagent = true;
      continue;
    }
    const msg = eventMessage(rec);
    if (msg) messages.push(msg);
  }

  if (isSubagent || !messages.length) return null;
  const fallbackTs = file.lastModified / 1000;
  const firstTs = messages.find((m) => m.created_at)?.created_at ?? fallbackTs;
  const lastTs =
    [...messages].reverse().find((m) => m.created_at)?.created_at ?? fallbackTs;
  return {
    external_id: ref.externalId,
    title: ref.provisionalTitle || deriveTitle(messages[0].content),
    source_cwd: cwd,
    created_at: firstTs,
    updated_at: lastTs,
    messages,
  };
}
