import {
  MCP_ADMIN_BASE_PATH,
  MCP_ALL_TRANSPORTS,
  MCP_REMOTE_TRANSPORTS,
  MCP_SPACE_BASE_PATH,
  deleteSpaceMcpServer,
  getMcpSettings,
  getSpaceMcpState,
  putSpaceMcpServer,
  testMcpServer,
  testSpaceMcpServer,
  updateMcpSettings,
  type McpServerConfig,
  type McpStoreState,
  type McpTestResult,
  type McpTransport,
} from "@/lib/mcp-api";

/**
 * Everything that differs between the places MCP servers can be managed: the
 * deployment-global admin registry and the per-user one.
 *
 * The components take this object instead of an `isAdmin` flag so the two
 * surfaces differ in one declaration rather than in conditionals sprinkled
 * through the JSX — and so a new surface is a new constant, not a new branch.
 */
export interface McpSurface {
  /** API base path the request helpers below hang their routes off. */
  basePath: string;
  /** Transports offered by the form's picker, in menu order. */
  transports: readonly McpTransport[];
  /**
   * How a write is addressed. `"registry"` PUTs the whole map at `basePath`;
   * `"per-server"` writes one server at a time under `basePath/servers/{name}`.
   * The two APIs are genuinely different shapes, so the read/write helpers in
   * this module dispatch on it and the callers stay shape-agnostic.
   */
  writes: McpWriteStyle;
}

export type McpWriteStyle = "registry" | "per-server";

/**
 * Deployment-global registry. stdio is selectable: a stdio `command` runs on
 * the host as the app user, which is exactly why this surface is admin-gated.
 */
export const ADMIN_MCP_SURFACE: McpSurface = {
  basePath: MCP_ADMIN_BASE_PATH,
  transports: MCP_ALL_TRANSPORTS,
  writes: "registry",
};

/**
 * A single account's own servers. Remote transports only, permanently: stdio is
 * a command executed on the host as the application user, and no per-user flag
 * makes that safe to hand out.
 */
export const SPACE_MCP_SURFACE: McpSurface = {
  basePath: MCP_SPACE_BASE_PATH,
  transports: MCP_REMOTE_TRANSPORTS,
  writes: "per-server",
};

export function surfaceAllows(
  surface: McpSurface,
  transport: McpTransport,
): boolean {
  return surface.transports.includes(transport);
}

/**
 * Delete one server by name, bypassing the whole-map diff.
 *
 * Needed for an entry the backend lists but will not connect (a hand-edited
 * stdio server): it never appears in the servers map, so a diff-based write has
 * nothing to remove.
 */
export async function deleteMcpSurfaceServer(
  surface: McpSurface,
  name: string,
): Promise<McpStoreState> {
  if (surface.writes !== "per-server") {
    throw new Error("Direct deletion is only available on a per-server surface");
  }
  return deleteSpaceMcpServer(surface.basePath, name);
}

export async function loadMcpSurface(
  surface: McpSurface,
): Promise<McpStoreState> {
  if (surface.writes === "per-server") {
    return getSpaceMcpState(surface.basePath);
  }
  return { ...(await getMcpSettings(surface.basePath)), user: null };
}

/**
 * Apply a whole-map intent to *surface*, and answer with the resulting state.
 *
 * A per-server surface has no whole-map write, so the intent is diffed against
 * `previous`. Upserts run before deletions on purpose: a rename is one add plus
 * one remove, and doing it the other way round would delete the old server
 * first — then lose it for good if the add were refused (e.g. at the per-account
 * cap). This order fails closed instead.
 */
export async function writeMcpSurface(
  surface: McpSurface,
  previous: Record<string, McpServerConfig>,
  next: Record<string, McpServerConfig>,
): Promise<McpStoreState> {
  if (surface.writes === "registry") {
    const status = await updateMcpSettings(surface.basePath, next);
    return { servers: next, status, user: null };
  }

  let state: McpStoreState | null = null;
  for (const [name, cfg] of Object.entries(next)) {
    if (isSameServer(previous[name], cfg)) continue;
    state = await putSpaceMcpServer(surface.basePath, name, cfg);
  }
  for (const name of Object.keys(previous)) {
    if (name in next) continue;
    state = await deleteSpaceMcpServer(surface.basePath, name);
  }
  // No diff at all (a toggle re-applied to the same value): the caller still
  // expects fresh state, and re-reading is cheaper than a redundant write.
  return state ?? loadMcpSurface(surface);
}

/**
 * Probe one definition before saving it.
 *
 * The per-user route is `POST /servers/{name}/test` — it runs under the caller's
 * own owner id so the probe obeys the same address policy and stored
 * credentials the real connection will. An unnamed draft borrows a name that no
 * real server can hold (the backend's name rule rejects a leading underscore),
 * so testing before naming cannot touch another server's stored credentials.
 */
export async function testMcpSurfaceServer(
  surface: McpSurface,
  name: string,
  cfg: McpServerConfig,
  secrets: Record<string, string> = {},
): Promise<McpTestResult> {
  if (surface.writes === "per-server") {
    return testSpaceMcpServer(
      surface.basePath,
      name.trim() || "_draft",
      cfg,
      secrets,
    );
  }
  return testMcpServer(surface.basePath, cfg);
}

/**
 * Whether a stored config and an edited one are the same write.
 *
 * Both sides are built by this module's own normalizer / form builder, so key
 * order is stable and a structural compare is enough. It errs towards
 * "changed": a reordered header map costs one idempotent PUT, while a missed
 * change would silently drop the edit.
 */
function isSameServer(
  previous: McpServerConfig | undefined,
  next: McpServerConfig,
): boolean {
  return previous !== undefined && JSON.stringify(previous) === JSON.stringify(next);
}
