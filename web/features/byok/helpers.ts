/**
 * Convert a FastAPI-style error response into a displayable message without
 * forcing every BYOK client to implement its own JSON parsing branch.
 */
export async function readApiError(
  response: Response,
  fallback: string,
): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (!body || typeof body !== "object") return fallback;

    const detail = (body as { detail?: unknown }).detail;
    if (typeof detail === "string" && detail.trim()) return detail;
    if (Array.isArray(detail)) {
      const messages = detail
        .map((item) => {
          if (typeof item === "string") return item.trim();
          if (item && typeof item === "object" && "msg" in item) {
            const message = (item as { msg?: unknown }).msg;
            return typeof message === "string" ? message.trim() : "";
          }
          return "";
        })
        .filter(Boolean);
      if (messages.length) return messages.join("; ");
    }
  } catch {
    // The fallback is intentional for non-JSON responses and empty bodies.
  }
  return fallback;
}

/**
 * Parse the administrator's newline-delimited allowlist only when saving.
 * Keeping the textarea's draft text separate lets an admin finish typing an
 * endpoint without React normalising or dropping the in-progress line.
 */
export function parseEndpointAllowlist(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((value) => value.trim())
    .filter(Boolean);
}
