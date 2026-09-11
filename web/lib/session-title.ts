const DEFAULT_SESSION_TITLE = "New conversation";

export function isPlaceholderSessionTitle(
  title: string | null | undefined,
): boolean {
  const value = (title ?? "").trim();
  return value === "" || value === DEFAULT_SESSION_TITLE;
}

/**
 * Swap the backend sentinel (or empty title) for a localized sidebar label.
 * Real user/LLM titles pass through unchanged.
 */
export function displaySessionTitle(
  title: string | null | undefined,
  placeholderLabel: string,
): string {
  if (isPlaceholderSessionTitle(title)) return placeholderLabel;
  return (title ?? "").trim();
}
