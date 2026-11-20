const RETURN_URL_BASE = "https://deeptutor.invalid";

export interface BrowserLocationParts {
  pathname: string;
  search?: string;
  hash?: string;
}

/** Return a same-origin application path or the supplied safe fallback. */
export function normalizeInternalReturnPath(
  raw: string | null | undefined,
  fallback = "/",
): string {
  const candidate = String(raw ?? "").trim();
  if (
    !candidate.startsWith("/") ||
    candidate.startsWith("//") ||
    candidate.includes("\\") ||
    /[\u0000-\u001f\u007f]/.test(candidate)
  ) {
    return fallback;
  }

  try {
    const parsed = new URL(candidate, RETURN_URL_BASE);
    if (parsed.origin !== RETURN_URL_BASE) return fallback;
    const decodedPath = decodeURIComponent(parsed.pathname);
    if (
      decodedPath.startsWith("//") ||
      decodedPath.includes("\\") ||
      /[\u0000-\u001f\u007f]/.test(decodedPath)
    ) {
      return fallback;
    }
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return fallback;
  }
}

export function browserReturnPath(location: BrowserLocationParts): string {
  return normalizeInternalReturnPath(
    `${location.pathname}${location.search ?? ""}${location.hash ?? ""}`,
  );
}

const LOGIN_PAGE = "/login";
const MAX_NEXT_LENGTH = 2000;

export function loginHref(returnPath: string): string {
  const url = new URL(normalizeInternalReturnPath(returnPath), RETURN_URL_BASE);
  // A previous `next` must not be encoded into the new one. That is the loop.
  url.searchParams.delete("next");
  if (url.pathname === LOGIN_PAGE) {
    return LOGIN_PAGE;
  }
  const cleaned = `${url.pathname}${url.search}${url.hash}`;
  const query = new URLSearchParams({
    next: cleaned.length > MAX_NEXT_LENGTH ? "/" : cleaned,
  });
  return `${LOGIN_PAGE}?${query.toString()}`;
}

/**
 * Server redirects cannot read a fragment. Browsers retain it on the login
 * URL, so carry that fragment into a validated destination that lacks one.
 */
export function inheritLoginHash(returnPath: string, loginHash: string): string {
  const safe = normalizeInternalReturnPath(returnPath);
  if (!loginHash || safe.includes("#")) return safe;
  const hash = loginHash.startsWith("#") ? loginHash : `#${loginHash}`;
  return normalizeInternalReturnPath(`${safe}${hash}`);
}
