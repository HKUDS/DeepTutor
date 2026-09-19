/**
 * Keep a deep book route at book level until its requested resource is ready.
 *
 * The route parameter is available on the first render, while the book detail
 * is loaded by an effect. Treating the default list view as authoritative in
 * between would briefly expose the parent library for a child resource URL.
 */
export function isBookRouteLoading(
  requestedBookId: string | null,
  loadedBookId: string | null
): boolean {
  return requestedBookId !== null && requestedBookId !== loadedBookId
}
