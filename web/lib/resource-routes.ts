function segment(value: string): string {
  return encodeURIComponent(value.trim());
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
