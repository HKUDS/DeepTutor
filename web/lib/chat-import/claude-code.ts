/**
 * Claude Code adapter. Sessions live at
 * `~/.claude/projects/<encoded-cwd>/<session-uuid>.jsonl`, already organized by
 * project. Each line is one event; we keep only human-readable user/assistant
 * text and drop tool calls, tool results, thinking, images, and sub-agent
 * (`isSidechain`) branches so the import is a clean conversation.
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

interface ClaudeRecord {
  type?: string;
  timestamp?: string;
  cwd?: string;
  isSidechain?: boolean;
  isMeta?: boolean;
  aiTitle?: string;
  message?: { role?: string; content?: unknown };
}

/** Lossy fallback: `/`, `.`, and literal `-` all encode to `-`, so this is only
 *  used as a cwd/label hint when no record carries the real `cwd`. */
function decodeProjectDir(name: string): string {
  return name.replace(/-/g, "/");
}

function flattenContent(content: unknown): {
  text: string;
  hadImages: boolean;
} {
  if (typeof content === "string") return { text: content, hadImages: false };
  if (!Array.isArray(content)) return { text: "", hadImages: false };
  const parts: string[] = [];
  let hadImages = false;
  for (const block of content) {
    if (!block || typeof block !== "object") continue;
    const b = block as Record<string, unknown>;
    if (b.type === "text" && typeof b.text === "string") parts.push(b.text);
    else if (b.type === "image") hadImages = true;
    // tool_use / tool_result / thinking are intentionally dropped.
  }
  return { text: parts.join("\n").trim(), hadImages };
}

function toMessage(rec: ClaudeRecord): NormalizedMessage | null {
  // Sub-agent branches and harness-injected meta turns aren't human dialogue.
  if (rec.isSidechain || rec.isMeta) return null;
  const role = rec.message?.role;
  if (role !== "user" && role !== "assistant") return null;
  const { text, hadImages } = flattenContent(rec.message?.content);
  const content = cleanText(text);
  if (!content) return null;
  const created = isoToEpochSeconds(rec.timestamp, 0);
  return {
    role,
    content,
    created_at: created || undefined,
    metadata: hadImages ? { had_images: true } : undefined,
  };
}

export async function scanClaude(
  root: FileSystemDirectoryHandle,
): Promise<ProjectGroup[]> {
  const projectsDir = await root.getDirectoryHandle("projects");
  const groups: ProjectGroup[] = [];

  for await (const entry of projectsDir.values()) {
    if (entry.kind !== "directory") continue;
    const dir = entry as FileSystemDirectoryHandle;
    const sessions: SessionRef[] = [];

    for await (const fileEntry of dir.values()) {
      if (fileEntry.kind !== "file" || !fileEntry.name.endsWith(".jsonl")) {
        continue;
      }
      const handle = fileEntry as FileSystemFileHandle;
      const file = await handle.getFile();
      const head = parseJsonl(
        await readHead(file, SCAN_HEAD_BYTES),
      ) as ClaudeRecord[];
      const cwd =
        head.find((r) => typeof r.cwd === "string")?.cwd ??
        decodeProjectDir(dir.name);
      const aiTitle = head.find(
        (r) => r.type === "ai-title" && r.aiTitle,
      )?.aiTitle;
      const firstUser = head.map(toMessage).find((m) => m?.role === "user");
      sessions.push({
        externalId: handle.name.replace(/\.jsonl$/, ""),
        provisionalTitle:
          aiTitle || (firstUser ? deriveTitle(firstUser.content) : ""),
        cwd,
        date: epochMsToISODate(file.lastModified),
        lastModified: file.lastModified,
        sizeBytes: file.size,
        handle,
      });
    }

    if (!sessions.length) continue;
    sessions.sort((a, b) => b.lastModified - a.lastModified);
    // Pin every session to the group's resolved cwd so the project key the
    // scope filter matches on is identical to each session's `cwd`.
    const groupCwd = sessions[0].cwd;
    for (const s of sessions) s.cwd = groupCwd;
    groups.push({
      cwd: groupCwd,
      label: projectLabel(groupCwd),
      sessions,
    });
  }

  groups.sort(
    (a, b) =>
      (b.sessions[0]?.lastModified ?? 0) - (a.sessions[0]?.lastModified ?? 0),
  );
  return groups;
}

export async function parseClaudeSession(
  ref: SessionRef,
): Promise<NormalizedSession | null> {
  const file = await ref.handle.getFile();
  const messages: NormalizedMessage[] = [];
  let cwd = ref.cwd;
  let aiTitle = "";

  for await (const line of iterLines(file)) {
    let rec: ClaudeRecord;
    try {
      rec = JSON.parse(line) as ClaudeRecord;
    } catch {
      continue;
    }
    if (rec.type === "ai-title" && typeof rec.aiTitle === "string") {
      aiTitle = rec.aiTitle;
      continue;
    }
    if (!cwd && typeof rec.cwd === "string") cwd = rec.cwd;
    const msg = toMessage(rec);
    if (msg) messages.push(msg);
  }

  if (!messages.length) return null;
  const fallbackTs = file.lastModified / 1000;
  const firstTs = messages.find((m) => m.created_at)?.created_at ?? fallbackTs;
  const lastTs =
    [...messages].reverse().find((m) => m.created_at)?.created_at ?? fallbackTs;
  return {
    external_id: ref.externalId,
    title: aiTitle || ref.provisionalTitle || deriveTitle(messages[0].content),
    source_cwd: cwd,
    created_at: firstTs,
    updated_at: lastTs,
    messages,
  };
}
