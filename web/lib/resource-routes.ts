function segment(value: string): string {
  return encodeURIComponent(value.trim());
}

/**
 * Decode a dynamic resource route parameter back to its stored identity.
 *
 * Next.js keeps dynamic values URL-encoded in the client router tree, so
 * `useParams()` can return e.g. `%E5%9B%BD...` for a Chinese resource name.
 */
export function decodeResourceSegment(
  value?: string | null,
): string | null {
  const candidate = value?.trim();
  if (!candidate) return null;
  try {
    return decodeURIComponent(candidate).trim() || null;
  } catch {
    // Leave malformed external URLs usable instead of crashing the page.
    return candidate;
  }
}

export function bookRoute(bookId?: string | null, pageId?: string | null): string {
  if (!bookId?.trim()) return "/books";
  const book = `/books/${segment(bookId)}`;
  return pageId?.trim() ? `${book}/pages/${segment(pageId)}` : book;
}

export function notebookRoute(
  notebookId?: string | null,
  courseId?: string | null,
): string {
  const pathname = notebookId?.trim()
    ? `/notebooks/${segment(notebookId)}`
    : "/notebooks";
  if (!courseId?.trim()) return pathname;
  return `${pathname}?course=${segment(courseId)}`;
}

export function knowledgeBaseRoute(name?: string | null): string {
  return name?.trim()
    ? `/knowledge-bases/${segment(name)}`
    : "/knowledge-bases";
}
