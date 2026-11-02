/**
 * Reader-language copy for error toasts.
 *
 * Error strings arrive from many layers: lib fallbacks ("Login failed"),
 * generic HTTP failures ("Request failed: 500"), backend `detail` prose and
 * provider bodies. The stable parts get catalog entries (the English sentence
 * is the i18next key, the same convention book-errors.ts established); the
 * status-bearing generic patterns get regex-shaped keys so the status stays
 * data. Anything uncatalogued — a provider's own error body, say — falls
 * back to the exact string it came in as, for every locale.
 */

type Translate = (key: string, options?: Record<string, unknown>) => string;

/** Generic failure shapes: message regex -> catalog key with placeholders. */
const PATTERNS: Array<[RegExp, string]> = [
  [/^Request failed \((\d+)\): (.+)$/s, "Request failed ({{status}}): {{detail}}"],
  [/^Request failed: (\d+)$/, "Request failed: {{status}}"],
  [/^Request failed \((\d+)\)$/, "Request failed ({{status}})"],
];

/** The message a toast should show for `message`, in the reader's language. */
export function errorCopy(message: string, t: Translate): string {
  const direct = t(message);
  if (direct !== message) return direct;
  for (const [pattern, key] of PATTERNS) {
    const match = pattern.exec(message);
    if (!match) continue;
    const options = { status: match[1], detail: match[2] };
    const translated = t(key, options);
    if (translated !== key) return translated;
    // No catalog entry for this locale: rebuild the original shape so an
    // English UI shows exactly what it showed before this helper existed.
    return key
      .replace("{{status}}", String(options.status))
      .replace("{{detail}}", String(options.detail ?? ""));
  }
  return message;
}
