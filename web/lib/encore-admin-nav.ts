export const ENCORE_ADMIN_ONLY_NAV = [
  "/partners",
  "/agents",
  "/co-writer",
  "/book",
  "/mastery",
  "/reading",
  "/space",
  "/memory",
  "/knowledge",
] as const;

/**
 * Sidebar stays hidden, but typing the URL (and any subpath) still opens the
 * page. Memory and Knowledge Center are configured this way by non-admins.
 */
const ENCORE_DIRECT_URL_PATHS = ["/memory", "/knowledge"] as const;

/** Personal settings any signed-in user may open. */
export const ENCORE_USER_SETTINGS_HREF = "/settings/appearance";

export type EncoreAdminOnlyHref = (typeof ENCORE_ADMIN_ONLY_NAV)[number];

export function isEncoreAdminOnlyNavHref(href: string): boolean {
  return (ENCORE_ADMIN_ONLY_NAV as readonly string[]).includes(href);
}

export function isEncoreUserSettingsPath(pathname: string): boolean {
  return pathname === ENCORE_USER_SETTINGS_HREF;
}

export function isEncoreAdminOnlyPath(pathname: string): boolean {
  if (isEncoreUserSettingsPath(pathname)) return false;
  if (pathname === "/settings" || pathname.startsWith("/settings/")) return true;
  return ENCORE_ADMIN_ONLY_NAV.some((prefix) => {
    if ((ENCORE_DIRECT_URL_PATHS as readonly string[]).includes(prefix)) {
      return false;
    }
    return pathname === prefix || pathname.startsWith(`${prefix}/`);
  });
}

export function encoreBlockedRedirect(pathname: string): string {
  if (pathname === "/settings" || pathname.startsWith("/settings/")) {
    return ENCORE_USER_SETTINGS_HREF;
  }
  return "/home";
}

export function showEncoreAdminNav(opts: {
  loading: boolean;
  enabled: boolean;
  isAdmin: boolean;
}): boolean {
  if (opts.loading) return false;
  return !opts.enabled || opts.isAdmin;
}
