/**
 * The client-side half of knowledge-base name validation.
 *
 * The backend is the authority — `deeptutor/knowledge/naming.py` rejects the
 * same set, and every `register_*` method calls it, so nothing depends on
 * this file being reached. It exists so the rule arrives as a hint under the
 * field the user is typing in, instead of as an English 400 after they press
 * Create.
 *
 * Keep the set in step with `_FORBIDDEN_CHARS` in that module.
 */
export const KB_NAME_FORBIDDEN_CHARS = '<>:"/\\|?*#%';

export const KB_NAME_MAX_LENGTH = 120;

/**
 * Returns the offending characters, in the order the backend reports them, or
 * an empty array when the name is acceptable.
 */
export function forbiddenKbNameChars(name: string): string[] {
  const found = new Set(
    [...name].filter((ch) => KB_NAME_FORBIDDEN_CHARS.includes(ch)),
  );
  return [...found].sort();
}

export function isValidKbName(name: string): boolean {
  const trimmed = name.trim();
  if (!trimmed || trimmed === "." || trimmed === "..") return false;
  if (trimmed.length > KB_NAME_MAX_LENGTH) return false;
  return forbiddenKbNameChars(trimmed).length === 0;
}
