import { apiFetch, apiUrl } from "@/lib/api";

const BASE = "/api/reading";

export type ReadingSourceKind =
  | "file"
  | "web"
  | "video"
  | "youtube"
  | "bilibili"
  | "audio";
export type ReadingIngestionStatus =
  | "queued"
  | "processing"
  | "ready"
  | "failed";

export interface ReadingLibraryMaterial {
  material_id: string;
  content_id: string;
  filename: string;
  title: string;
  source_kind: ReadingSourceKind;
  source_url: string;
  mime: string;
  render_mode: "text" | "pdf" | "epub" | "video" | "audio";
  cover_url: string;
  duration_seconds: number;
  status: ReadingIngestionStatus;
  progress: number;
  error_code: string;
  error_detail: string;
  created_at: number;
  updated_at: number;
  last_opened_at: number;
  /** Stored source size; 0 until the material is ready. */
  size_bytes?: number;
  /** Extracted units — pages for a PDF, sections for a web page. */
  unit_count?: number;
  /** Every collection holding this material; empty means unassigned. */
  collections?: ReadingMaterialCollection[];
}

export interface ReadingMaterialCollection {
  workspace_id: string;
  title: string;
}

export type ReadingLibraryFilter =
  | "all"
  | "unassigned"
  | "processing"
  | "failed";

export interface ReadingLibraryCounts {
  all: number;
  unassigned: number;
  processing: number;
  failed: number;
  by_kind: Record<string, number>;
}

export interface ReadingDuplicateMatch {
  query: { filename?: string; url?: string };
  kind: "same_content" | "same_name";
  material: ReadingLibraryMaterial;
  collections: ReadingMaterialCollection[];
}

export interface ReadingWorkspaceTab {
  material: ReadingLibraryMaterial;
  tab_order: number;
  pinned: boolean;
  opened: boolean;
  added_at: number;
}

export interface ReadingWorkspace {
  workspace_id: string;
  title: string;
  description: string;
  active_material_id: string | null;
  created_at: number;
  updated_at: number;
  tabs: ReadingWorkspaceTab[];
}

export interface ReadingConversation {
  workspace_id: string;
  session_id: string;
  title: string;
  active_material_id: string | null;
  created_at: number;
  updated_at: number;
  linked_session_ids?: string[];
}

export interface OrganizedReadingNotes {
  workspace_id: string;
  title: string;
  markdown: string;
  material_ids: string[];
  annotation_count: number;
}

async function unwrap<T>(response: Response): Promise<T> {
  if (response.ok) return (await response.json()) as T;
  let message = `Request failed: ${response.status}`;
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") message = body.detail;
  } catch {
    // Keep the HTTP status for proxy/non-JSON responses.
  }
  throw new Error(message);
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  return unwrap(
    await apiFetch(apiUrl(`${BASE}${path}`), {
      cache: "no-store",
      ...init,
      headers: init?.body
        ? { "Content-Type": "application/json", ...init.headers }
        : init?.headers,
    }),
  );
}

export async function listReadingLibraryMaterials(
  search = "",
  filter: ReadingLibraryFilter = "all",
): Promise<{
  materials: ReadingLibraryMaterial[];
  counts: ReadingLibraryCounts | null;
}> {
  const params = new URLSearchParams();
  if (search) params.set("search", search);
  if (filter !== "all") params.set("filter", filter);
  const payload = await json<{
    materials: ReadingLibraryMaterial[];
    counts?: ReadingLibraryCounts;
  }>(`/library/materials${params.size ? `?${params}` : ""}`);
  return { materials: payload.materials ?? [], counts: payload.counts ?? null };
}

/**
 * Content id the server would derive for these bytes — sha256 truncated to 16
 * hex chars, matching `deeptutor.reading.store.content_hash`. Hashing happens
 * before the upload so a duplicate is caught while the user can still choose,
 * which means reading the whole file into memory: past the ceiling we fall back
 * to name-only matching rather than freezing the tab on a 500 MB lecture.
 */
const CONTENT_HASH_CEILING = 96 * 1024 * 1024;

export async function readingContentId(file: File): Promise<string> {
  if (file.size > CONTENT_HASH_CEILING) return "";
  if (!globalThis.crypto?.subtle) return "";
  try {
    const digest = await crypto.subtle.digest(
      "SHA-256",
      await file.arrayBuffer(),
    );
    return Array.from(new Uint8Array(digest))
      .map((byte) => byte.toString(16).padStart(2, "0"))
      .join("")
      .slice(0, 16);
  } catch {
    return "";
  }
}

export async function checkReadingDuplicates(payload: {
  files?: { filename: string; content_id?: string; size_bytes?: number }[];
  urls?: string[];
}): Promise<ReadingDuplicateMatch[]> {
  const result = await json<{ matches: ReadingDuplicateMatch[] }>(
    "/library/duplicate-check",
    { method: "POST", body: JSON.stringify(payload) },
  );
  return result.matches ?? [];
}

export async function deleteReadingMaterial(
  materialId: string,
): Promise<ReadingMaterialCollection[]> {
  const result = await json<{ removed_from?: ReadingMaterialCollection[] }>(
    `/materials/${materialId}`,
    { method: "DELETE" },
  );
  return result.removed_from ?? [];
}

export async function listReadingWorkspaces(filters?: {
  search?: string;
}): Promise<ReadingWorkspace[]> {
  const params = new URLSearchParams();
  if (filters?.search) params.set("search", filters.search);
  const payload = await json<{ workspaces: ReadingWorkspace[] }>(
    `/workspaces${params.size ? `?${params}` : ""}`,
  );
  return payload.workspaces ?? [];
}

export async function getReadingWorkspace(workspaceId: string): Promise<{
  workspace: ReadingWorkspace;
  sessions: ReadingConversation[];
}> {
  return json(`/workspaces/${workspaceId}`);
}

export async function createReadingWorkspace(payload: {
  title: string;
  description?: string;
  material_ids?: string[];
}): Promise<ReadingWorkspace> {
  const result = await json<{ workspace: ReadingWorkspace }>("/workspaces", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return result.workspace;
}

export async function updateReadingWorkspace(
  workspaceId: string,
  patch: { title?: string; description?: string },
): Promise<ReadingWorkspace> {
  const result = await json<{ workspace: ReadingWorkspace }>(
    `/workspaces/${workspaceId}`,
    { method: "PATCH", body: JSON.stringify(patch) },
  );
  return result.workspace;
}

export async function deleteReadingWorkspace(
  workspaceId: string,
): Promise<void> {
  await json(`/workspaces/${workspaceId}`, { method: "DELETE" });
}

export async function importReadingUrls(payload: {
  urls: string[];
  workspace_id?: string;
  workspace_title?: string;
  reuse?: boolean;
}): Promise<{
  materials: ReadingLibraryMaterial[];
  workspace: ReadingWorkspace;
}> {
  return json("/library/import-urls", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function retryReadingMaterial(
  materialId: string,
): Promise<ReadingLibraryMaterial> {
  const result = await json<{ material: ReadingLibraryMaterial }>(
    `/materials/${materialId}/retry`,
    { method: "POST" },
  );
  return result.material;
}

export async function addReadingWorkspaceMaterial(
  workspaceId: string,
  materialId: string,
  makeActive = false,
): Promise<ReadingWorkspace> {
  const result = await json<{ workspace: ReadingWorkspace }>(
    `/workspaces/${workspaceId}/materials`,
    {
      method: "POST",
      body: JSON.stringify({
        material_id: materialId,
        make_active: makeActive,
      }),
    },
  );
  return result.workspace;
}

export async function activateReadingMaterial(
  workspaceId: string,
  materialId: string,
): Promise<ReadingWorkspace> {
  const result = await json<{ workspace: ReadingWorkspace }>(
    `/workspaces/${workspaceId}/materials/${materialId}/active`,
    { method: "PUT" },
  );
  return result.workspace;
}

export async function removeReadingWorkspaceMaterial(
  workspaceId: string,
  materialId: string,
): Promise<ReadingWorkspace> {
  const result = await json<{ workspace: ReadingWorkspace }>(
    `/workspaces/${workspaceId}/materials/${materialId}`,
    { method: "DELETE" },
  );
  return result.workspace;
}

export async function createReadingConversation(
  workspaceId: string,
  title = "New reading conversation",
  activeMaterialId = "",
): Promise<ReadingConversation> {
  return (
    await json<{ session: ReadingConversation }>(
      `/workspaces/${workspaceId}/sessions`,
      {
        method: "POST",
        body: JSON.stringify({
          title,
          active_material_id: activeMaterialId,
        }),
      },
    )
  ).session;
}

/**
 * One question the learner could ask about what they are reading right now.
 *
 * Written by the task model against the open material, the passage in view
 * and the last exchange — a prompt for *their* next question, never an
 * answer. Returns "" whenever there is nothing worth offering (cold model,
 * timeout, a sentence that came back looking like an answer), and the
 * composer then keeps the static placeholder it has always had.
 */
export async function fetchReadingAskHint(
  workspaceId: string,
  params: { sessionId?: string; locator?: number; selection?: string } = {},
  init?: RequestInit,
): Promise<string> {
  const query = new URLSearchParams();
  if (params.sessionId) query.set("session_id", params.sessionId);
  if (params.locator && params.locator > 0)
    query.set("locator", String(params.locator));
  if (params.selection) query.set("selection", params.selection);
  const suffix = query.toString() ? `?${query}` : "";
  try {
    const result = await json<{ hint?: string }>(
      `/workspaces/${workspaceId}/ask-hint${suffix}`,
      init,
    );
    return typeof result.hint === "string" ? result.hint : "";
  } catch {
    // A missing hint is not a failure the reader should ever see.
    return "";
  }
}

/** Just enough to name a collection. See ``fetchReadingCollectionIndex``. */
export interface ReadingCollectionLabel {
  workspace_id: string;
  title: string;
}

/**
 * The id → title map, without each collection's tab list.
 *
 * The sidebar files reading conversations under their collection and reloads
 * on every stream end, so it wants the labels and nothing else; the full
 * listing ships every material, cover and unit count to render a heading.
 */
export async function fetchReadingCollectionIndex(
  init?: RequestInit,
): Promise<ReadingCollectionLabel[]> {
  try {
    const result = await json<{ collections?: ReadingCollectionLabel[] }>(
      "/workspaces/index",
      init,
    );
    return Array.isArray(result.collections) ? result.collections : [];
  } catch {
    // A sidebar that cannot name a collection still lists its conversations.
    return [];
  }
}

/**
 * Three things the learner could open this material with.
 *
 * Written against the material itself, so they name a claim it makes or a
 * section it has rather than being true of every document. An empty array
 * means the panel keeps its own generic lines — this is a nicety, and an
 * empty conversation must never be an empty panel.
 */
export async function fetchReadingOpeners(
  workspaceId: string,
  locator?: number,
  init?: RequestInit,
): Promise<string[]> {
  const suffix = locator && locator > 0 ? `?locator=${locator}` : "";
  try {
    const result = await json<{ suggestions?: string[] }>(
      `/workspaces/${workspaceId}/openers${suffix}`,
      init,
    );
    return Array.isArray(result.suggestions) ? result.suggestions : [];
  } catch {
    return [];
  }
}

export async function listReadingConversations(
  workspaceId: string,
): Promise<ReadingConversation[]> {
  return (
    (
      await json<{ sessions: ReadingConversation[] }>(
        `/workspaces/${workspaceId}/sessions`,
      )
    ).sessions ?? []
  );
}

export async function renameReadingConversation(
  workspaceId: string,
  sessionId: string,
  title: string,
): Promise<ReadingConversation> {
  return (
    await json<{ session: ReadingConversation }>(
      `/workspaces/${workspaceId}/sessions/${sessionId}`,
      { method: "PATCH", body: JSON.stringify({ title }) },
    )
  ).session;
}

export async function deleteReadingConversation(
  workspaceId: string,
  sessionId: string,
): Promise<void> {
  await json(`/workspaces/${workspaceId}/sessions/${sessionId}`, {
    method: "DELETE",
  });
}

export async function linkReadingConversation(
  workspaceId: string,
  sessionId: string,
  targetSessionId: string,
): Promise<string[]> {
  return (
    await json<{ linked_session_ids: string[] }>(
      `/workspaces/${workspaceId}/sessions/${sessionId}/links`,
      {
        method: "POST",
        body: JSON.stringify({ target_session_id: targetSessionId }),
      },
    )
  ).linked_session_ids;
}

export async function unlinkReadingConversation(
  workspaceId: string,
  sessionId: string,
  targetSessionId: string,
): Promise<string[]> {
  return (
    await json<{ linked_session_ids: string[] }>(
      `/workspaces/${workspaceId}/sessions/${sessionId}/links/${targetSessionId}`,
      { method: "DELETE" },
    )
  ).linked_session_ids;
}

export async function organizeReadingNotes(
  workspaceId: string,
  materialIds: string[] = [],
): Promise<OrganizedReadingNotes> {
  return (
    await json<{ notes: OrganizedReadingNotes }>(
      `/workspaces/${workspaceId}/notes/organize`,
      { method: "POST", body: JSON.stringify({ material_ids: materialIds }) },
    )
  ).notes;
}

export async function sendReadingToNotebook(
  workspaceId: string,
  notebookIds: string[],
  materialIds: string[] = [],
): Promise<Record<string, unknown>> {
  return json(`/workspaces/${workspaceId}/notebooks`, {
    method: "POST",
    body: JSON.stringify({
      notebook_ids: notebookIds,
      material_ids: materialIds,
    }),
  });
}

export async function generateMasteryPathFromReading(
  workspaceId: string,
  bookId: string,
  materialIds: string[] = [],
): Promise<Record<string, unknown>> {
  return unwrap(
    await apiFetch(
      apiUrl(
        `/api/mastery-paths/progress/${encodeURIComponent(bookId)}/generate-from-reading`,
      ),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          workspace_id: workspaceId,
          material_ids: materialIds,
        }),
      },
    ),
  );
}
