import type { ImportSource } from "./types";

async function hasDir(
  root: FileSystemDirectoryHandle,
  name: string,
): Promise<boolean> {
  try {
    await root.getDirectoryHandle(name);
    return true;
  } catch {
    return false;
  }
}

/**
 * Identify whether the picked folder is a `.claude` or `.codex` home. The
 * folder name is the primary hint; directory structure is the fallback so a
 * renamed or copied folder still resolves. Returns `null` when neither shape
 * matches (the wizard surfaces a friendly "pick the right folder" message).
 */
export async function detectSource(
  root: FileSystemDirectoryHandle,
): Promise<ImportSource | null> {
  const name = root.name.toLowerCase();
  if (name === ".claude") return "claude_code";
  if (name === ".codex") return "codex";

  const [hasProjects, hasSessions] = await Promise.all([
    hasDir(root, "projects"),
    hasDir(root, "sessions"),
  ]);
  if (hasProjects && !hasSessions) return "claude_code";
  if (hasSessions && !hasProjects) return "codex";
  return null;
}
