/** Fixed L3 documents under server-owned grants; arguments cannot choose paths. */
import { constants } from "node:fs";
import { open, realpath } from "node:fs/promises";
import { join, relative, isAbsolute, sep } from "node:path";
import type { NativeInput, ToolResult } from "../native/types.js";
import { result } from "./workspace.js";

const slots = ["recent", "profile", "scope", "preferences"];
async function layer(root: string, signal: AbortSignal): Promise<string> {
  const parts: string[] = [];
  for (const slot of slots) {
    signal.throwIfAborted();
    let file;
    try {
      const base = await realpath(root),
        folder = await realpath(join(base, "L3"));
      const rel = relative(base, folder);
      if (isAbsolute(rel) || rel === ".." || rel.startsWith(`..${sep}`))
        throw new Error("Memory path leaves its admitted root");
      file = await open(
        join(folder, `${slot}.md`),
        constants.O_RDONLY | constants.O_NOFOLLOW,
      );
      const info = await file.stat();
      if (!info.isFile() || info.size > 2 * 1024 * 1024)
        throw new Error("Memory document exceeds the 2 MiB read limit");
      const body = (await file.readFile({ encoding: "utf8", signal })).trim();
      if (body) parts.push(body);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    } finally {
      await file?.close();
    }
  }
  return parts.join("\n\n---\n\n");
}
export async function readMemory(
  name: string,
  input: NativeInput,
  signal: AbortSignal,
): Promise<ToolResult> {
  const roots = input.toolRuntime?.[name]?.memoryRoots;
  const required = name === "partner_read" ? 2 : 1;
  if (!roots || roots.length !== required)
    throw new Error("Missing admitted memory scope");
  const values = await Promise.all(roots.map((root) => layer(root, signal)));
  if (name === "partner_read") {
    const [shared, own] = values;
    const text = `## Shared memory (the owner's — read-only)\n\n${shared || "(none yet)"}\n\n## Your own memory\n\n${own || "(none yet — use partner_memorize to add)"}`;
    return result(text, {
      char_count: [...text].length,
      has_shared: !!shared,
      has_own: !!own,
    });
  }
  const text = values[0]
    ? values[0] + "\n"
    : "(No memory available — interact with DeepTutor and update from the Memory page to build one.)";
  return result(text, { char_count: [...text].length });
}
