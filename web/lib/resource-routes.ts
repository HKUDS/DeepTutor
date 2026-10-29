function segment(value: string): string {
  return encodeURIComponent(value.trim());
}

/**
 * Decode a dynamic resource route parameter back to its stored identity.
 *
 * Next.js keeps dynamic values URL-encoded in the client router tree, so
 * `useParams()` can return e.g. `%E5%9B%BD...` for a Chinese resource name.
 */
export function decodeResourceSegment(value?: string | null): string | null {
  const candidate = value?.trim();
  if (!candidate) return null;
  try {
    return decodeURIComponent(candidate).trim() || null;
  } catch {
    // Leave malformed external URLs usable instead of crashing the page.
    return candidate;
  }
}

export function notebookRoute(
  notebookId?: string | null,
  recordId?: string | null,
): string {
  const pathname = notebookId?.trim()
    ? `/notebooks/${segment(notebookId)}`
    : "/notebooks";
  const query = [
    recordId?.trim() ? `record=${segment(recordId)}` : "",
  ]
    .filter(Boolean)
    .join("&");
  return query ? `${pathname}?${query}` : pathname;
}

export function knowledgeBaseRoute(name?: string | null): string {
  return name?.trim()
    ? `/knowledge-bases/${segment(name)}`
    : "/knowledge-bases";
}

/** A stable link back to an archived favorite, including after a move. */
export function favoriteRecordRoute(
  collectionId: string,
  recordId: string,
): string {
  return notebookRoute(collectionId, recordId);
}
