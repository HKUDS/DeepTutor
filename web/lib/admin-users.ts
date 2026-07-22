/**
 * Case-insensitive username filter backing the admin Users search box.
 * An empty / whitespace-only query returns the input list unchanged.
 *
 * Generic over `{ username }` (rather than importing UserRecord) so the
 * module stays alias-free and loadable by the node unit tests.
 */
export function filterUsersByQuery<T extends { username: string }>(
  users: T[],
  query: string,
): T[] {
  const normalized = query.trim().toLowerCase();
  if (!normalized) return users;
  return users.filter((user) =>
    user.username.toLowerCase().includes(normalized),
  );
}
