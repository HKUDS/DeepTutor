import { open, opendir, realpath, stat } from "node:fs/promises";
import { isAbsolute, join, relative, sep } from "node:path";
import type { JsonRecord, NativeInput, ToolResult } from "../native/types.js";

export function result(
  content: string,
  metadata: JsonRecord = {},
  success = true,
): ToolResult {
  return {
    content,
    metadata,
    success,
    sources: [],
    pause: null,
    terminate: false,
    modelMessage: null,
  };
}
function inside(root: string, path: string): boolean {
  const rel = relative(root, path);
  return (
    rel === "" ||
    (!isAbsolute(rel) && rel !== ".." && !rel.startsWith(`..${sep}`))
  );
}
async function confined(
  root: string,
  raw: string,
  allowRoot = false,
): Promise<string> {
  const value = raw.trim().replaceAll("\\", "/");
  if (
    isAbsolute(value) ||
    /^[A-Za-z]:/.test(value) ||
    value.includes("\0") ||
    value.split("/").some((x) => x === ".." || x === ".deeptutor")
  )
    throw new Error("Workspace path is not allowed");
  if (!allowRoot && (!value || value === "."))
    throw new Error("A relative file path is required");
  const resolvedRoot = await realpath(root),
    path = await realpath(join(resolvedRoot, value || "."));
  if (
    !inside(resolvedRoot, path) ||
    relative(resolvedRoot, path).split(sep).includes(".deeptutor")
  )
    throw new Error("The path leaves the selected workspace");
  return path;
}
const bounded = (x: unknown, fallback: number, maximum: number, minimum = 1) =>
  Math.max(minimum, Math.min(maximum, Math.trunc(Number(x) || fallback)));

async function walk(
  root: string,
  base: string,
  depth: number,
  limit: number,
  signal: AbortSignal,
) {
  const queue: Array<[string, number]> = [[base, 0]];
  const entries: string[] = [];
  let truncated = false;
  for (let index = 0; index < queue.length; index++) {
    const [directory, level] = queue[index]!;
    signal.throwIfAborted();
    let handle;
    try {
      handle = await opendir(directory);
    } catch {
      continue;
    }
    for await (const entry of handle) {
      signal.throwIfAborted();
      if (entry.name === ".deeptutor" || entry.isSymbolicLink()) continue;
      if (entries.length >= limit) {
        truncated = true;
        return { entries, truncated };
      }
      const path = join(directory, entry.name);
      try {
        if (!inside(root, await realpath(path))) continue;
      } catch {
        continue;
      }
      entries.push(path);
      if (entry.isDirectory() && level + 1 < depth)
        queue.push([path, level + 1]);
    }
  }
  return { entries, truncated };
}

async function readPage(
  path: string,
  offset: number,
  limit: number,
  signal: AbortSignal,
) {
  const file = await open(path, "r");
  try {
    if (!(await file.stat()).isFile())
      throw new Error("The path is not a regular file");
    const decoder = new TextDecoder("utf-8", { fatal: true });
    const buffer = Buffer.alloc(65536);
    let total = 0,
      content = "";
    while (true) {
      signal.throwIfAborted();
      const { bytesRead } = await file.read(buffer, 0, buffer.length);
      const chunk = decoder.decode(buffer.subarray(0, bytesRead), {
        stream: bytesRead > 0,
      });
      for (const char of chunk) {
        if (total >= offset && total < offset + limit) content += char;
        total++;
      }
      if (!bytesRead) break;
    }
    return {
      content,
      total_chars: total,
      offset,
      truncated: offset + [...content].length < total,
    };
  } finally {
    await file.close();
  }
}

export async function workspaceTool(
  name: string,
  args: JsonRecord,
  input: NativeInput,
  signal: AbortSignal,
): Promise<ToolResult> {
  if (name === "read_skill") {
    const skill = String(args.name ?? "")
      .trim()
      .toLowerCase();
    const root = input.skillRoots[skill];
    if (!root) throw new Error(`Skill is not admitted: ${skill}`);
    const path = await confined(root, String(args.file || "SKILL.md"));
    const page = await readPage(path, 0, 500_000, signal);
    return result(page.content, {
      skill,
      file: String(args.file || "SKILL.md"),
      char_count: page.total_chars,
      truncated: page.truncated,
    });
  }
  if (!input.workspace) throw new Error("This turn has no admitted workspace");
  const root = await realpath(input.workspace.root),
    raw = String(args.path || ".");
  const base = await confined(root, raw, name !== "workspace_read");
  if (name === "workspace_read") {
    const page = await readPage(
      base,
      bounded(args.offset, 0, Number.MAX_SAFE_INTEGER, 0),
      bounded(args.limit, 20_000, 100_000),
      signal,
    );
    const { content, ...metadata } = page;
    return result(content, {
      workspace_read: {
        path: relative(root, base).split(sep).join("/"),
        ...metadata,
      },
    });
  }
  if (!(await stat(base)).isDirectory())
    throw new Error("The workspace path is not a directory");
  if (name === "workspace_list") {
    const page = await walk(
      root,
      base,
      bounded(args.depth, 1, 5),
      bounded(args.limit, 200, 1000),
      signal,
    );
    const entries: JsonRecord[] = [];
    for (const path of page.entries) {
      try {
        const info = await stat(path),
          rel = relative(root, path).split(sep).join("/");
        entries.push({
          path: rel,
          name: rel.split("/").at(-1),
          kind: info.isDirectory() ? "directory" : "file",
          size_bytes: info.isDirectory() ? null : info.size,
          modified_at: info.mtimeMs / 1000,
        });
      } catch {
        /* A concurrently removed entry does not invalidate the page. */
      }
    }
    const value = {
      entries,
      scanned_entries: page.entries.length,
      truncated: page.truncated,
    };
    return result(JSON.stringify(value, null, 2), {
      workspace_id: input.workspace.id,
      ...value,
    });
  }
  if (name !== "workspace_search")
    throw new Error("Unknown native workspace operation");
  const query = String(args.query ?? "")
    .trim()
    .toLowerCase();
  if (!query) throw new Error("Search requires a query");
  const page = await walk(root, base, Infinity, 10_000, signal),
    matches: JsonRecord[] = [];
  let scanned = 0;
  for (const path of page.entries) {
    signal.throwIfAborted();
    scanned++;
    try {
      const info = await stat(path);
      if (!info.isFile()) continue;
      const rel = relative(root, path).split(sep).join("/"),
        filename = rel.split("/").at(-1)!;
      if (filename.toLowerCase().includes(query))
        matches.push({ path: rel, line: null, preview: filename });
      else if (info.size <= 2_000_000) {
        const text = (await readPage(path, 0, 2_000_000, signal)).content;
        const lines = text.split(/\r?\n/),
          index = lines.findIndex((line) => line.toLowerCase().includes(query));
        if (index >= 0)
          matches.push({
            path: rel,
            line: index + 1,
            preview: lines[index]!.slice(0, 500),
          });
      }
    } catch (error) {
      signal.throwIfAborted(); /* Binary/deleted entries are skipped. */
    }
    if (matches.length >= bounded(args.limit, 50, 200)) break;
  }
  const value = {
    matches,
    scanned_entries: scanned,
    truncated: page.truncated || scanned < page.entries.length,
  };
  return result(JSON.stringify(value, null, 2), {
    workspace_id: input.workspace.id,
    ...value,
  });
}
