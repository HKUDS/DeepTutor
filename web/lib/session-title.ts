const DEFAULT_SESSION_TITLE = "New conversation";

export function isPlaceholderSessionTitle(
  title: string | null | undefined,
): boolean {
  const value = (title ?? "").trim();
  return value === "" || value === DEFAULT_SESSION_TITLE;
}
