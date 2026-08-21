export const ENCORE_ADMIN_ONLY_NAV = [
  "/partners",
  "/agents",
  "/co-writer",
  "/book",
  "/space",
  "/memory",
  "/knowledge",
  "/settings",
] as const;

export type EncoreAdminOnlyHref = (typeof ENCORE_ADMIN_ONLY_NAV)[number];

export function isEncoreAdminOnlyNavHref(href: string): boolean {
  return (ENCORE_ADMIN_ONLY_NAV as readonly string[]).includes(href);
}

export function isEncoreAdminOnlyPath(pathname: string): boolean {
  return ENCORE_ADMIN_ONLY_NAV.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}

export function showEncoreAdminNav(opts: {
  loading: boolean;
  enabled: boolean;
  isAdmin: boolean;
}): boolean {
  if (opts.loading) return false;
  return !opts.enabled || opts.isAdmin;
}
