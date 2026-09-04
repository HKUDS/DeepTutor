import { apiFetch, apiUrl } from "@/lib/api";

// ── Immersive reading (materials under data/user/workspace/reading) ──
//
// A *material* is a document the user reads in the reader pane. It is cut once
// into **units** and addressed by **locator** — a 1-indexed unit number that
// means page / chapter / slide / section depending on the source format. The
// unit word is carried on the material so the UI can say "page 12" or
// "chapter 3" without ever branching on the file type itself.

export type UnitKind = "page" | "chapter" | "slide" | "section" | "segment";
export type AnnotationKind = "highlight" | "underline" | "note" | "citation";
export type ExportFormat = "auto" | "pdf" | "markdown";
export type RenderMode = "text" | "pdf" | "epub" | "video" | "audio";
export type ContentFormat = "plain_text" | "web_markdown";

/** Palette offered by the annotation toolbar; mirrored server-side. */
export const ANNOTATION_COLORS = [
  "yellow",
  "green",
  "blue",
  "pink",
  "purple",
] as const;
export type AnnotationColor = (typeof ANNOTATION_COLORS)[number];

/**
 * Swatch for each highlight colour.
 *
 * Deliberately literal rather than themed: a highlight is content — it is
 * written into the exported PDF and has to look the same everywhere the
 * annotation is read back.
 */
export const ANNOTATION_SWATCH: Record<AnnotationColor, string> = {
  yellow: "#facd5a",
  green: "#8cdb94",
  blue: "#7ac0fa",
  pink: "#faa1c7",
  purple: "#c7aefa",
};

export interface MaterialInfo {
  material_id: string;
  filename: string;
  unit: UnitKind;
  unit_count: number;
  mime: string;
  title: string;
  byte_size: number;
  char_count: number;
  created_at: number;
  /** True when the original bytes can be rendered faithfully (PDF today). */
  has_raw_view: boolean;
  render_mode: RenderMode;
  extractor: string;
  content_format?: ContentFormat;
  source_type?: string;
  source_url?: string;
  revision?: number;
  annotation_count: number;
}

export interface OutlineRow {
  locator: number;
  title: string;
  level: number;
  synthesised: boolean;
}

export interface MaterialDetail extends MaterialInfo {
  outline: OutlineRow[];
  outline_text: string;
  unit_refs: UnitReference[];
}

export interface UnitReference {
  locator: number;
  source_href: string;
  title: string;
}

/**
 * A rectangle normalised to its unit box: 0..1, origin top-left, y downwards.
 *
 * Normalised because the reader re-renders at whatever zoom and width the pane
 * happens to have; storing pixels would pin a highlight to one viewport. The
 * same space is what the PDF export expects, so no second transform is needed
 * on the way out.
 */
export type NormalisedRect = [number, number, number, number];

export type ReadingTextSelector =
  | {
      type: "TextQuoteSelector";
      exact: string;
      prefix?: string;
      suffix?: string;
    }
  | {
      type: "TextPositionSelector";
      start: number;
      end: number;
    };

export interface AnnotationItem {
  annotation_id: string;
  locator: number;
  material_revision?: number;
  kind: AnnotationKind;
  color: string;
  quote: string;
  note: string;
  rects: NormalisedRect[];
  source_anchor: string;
  selectors?: ReadingTextSelector[];
  /** "user" or "assistant" — the model can annotate too. */
  author: string;
  created_at: number;
  updated_at: number;
}

export interface AnnotationDraft {
  annotation_id?: string;
  locator: number;
  kind?: AnnotationKind;
  color?: string;
  quote?: string;
  note?: string;
  rects?: NormalisedRect[];
  source_anchor?: string;
  selectors?: ReadingTextSelector[];
}

export interface ReadingPosition {
  locator: number;
  source_anchor: string;
  percentage: number;
  updated_at: number;
}

export function parseReadingPosition(payload: unknown): ReadingPosition {
  if (!payload || typeof payload !== "object") {
    throw new Error("Invalid reading position response");
  }
  const position = payload as Record<string, unknown>;
  if (
    typeof position.locator !== "number" ||
    !Number.isFinite(position.locator) ||
    position.locator < 1 ||
    typeof position.source_anchor !== "string" ||
    typeof position.percentage !== "number" ||
    !Number.isFinite(position.percentage) ||
    typeof position.updated_at !== "number" ||
    !Number.isFinite(position.updated_at)
  ) {
    throw new Error("Invalid reading position response");
  }
  return position as unknown as ReadingPosition;
}

/**
 * A place the reader chose to keep, as opposed to the position above — which
 * is the single automatic "where I got to", overwritten on every move. These
 * are deliberate and plural, and each has its own id.
 */
export interface ReadingBookmark {
  bookmark_id: string;
  locator: number;
  label: string;
  source_anchor: string;
  created_at: number;
}

export interface SupportedFormats {
  extensions: string[];
  max_bytes: number;
  raw_view_extensions: string[];
}

export interface ReadingExtensionAction {
  id: string;
  label: string;
  trigger: "toolbar";
  requires: Array<"selection" | "visible_text">;
}

export interface ReadingExtensionManifest {
  id: string;
  version: string;
  name: string;
  protocol_version: "1";
  actions: ReadingExtensionAction[];
  result_types: Array<"card" | "quiz" | "feedback" | "browser_speech">;
}

export interface ReadingExtensionResult {
  type: "card" | "quiz" | "feedback" | "browser_speech";
  title: string;
  message: string;
  payload: Record<string, unknown>;
}

const BASE = "/api/reading";

/** Surface the server's own message — it explains what the user can do next. */
async function unwrap<T>(response: Response): Promise<T> {
  if (response.ok) return (await response.json()) as T;
  let detail = `Request failed: ${response.status}`;
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body?.detail === "string" && body.detail) detail = body.detail;
    else if (
      typeof body?.detail === "object" &&
      body.detail !== null &&
      "message" in body.detail
    ) {
      detail = String((body.detail as { message: unknown }).message);
    }
  } catch {
    // Non-JSON error body (a proxy page, say) — keep the status line.
  }
  throw new Error(detail);
}

export async function getSupportedFormats(): Promise<SupportedFormats> {
  return unwrap(await apiFetch(apiUrl(`${BASE}/supported-formats`)));
}

export async function listMaterials(): Promise<MaterialInfo[]> {
  return unwrap(
    await apiFetch(apiUrl(`${BASE}/materials`), { cache: "no-store" }),
  );
}

export async function uploadMaterial(
  file: File,
  options?: { reuse?: boolean },
): Promise<MaterialDetail> {
  const form = new FormData();
  form.append("file", file, file.name);
  // reuse=false asks the server to mint a separate material for content it
  // already holds, so a second copy carries its own annotations instead of
  // silently collapsing onto the first upload.
  const query = options?.reuse === false ? "?reuse=false" : "";
  return unwrap(
    await apiFetch(apiUrl(`${BASE}/materials${query}`), {
      method: "POST",
      body: form,
    }),
  );
}

export async function getMaterial(materialId: string): Promise<MaterialDetail> {
  return unwrap(
    await apiFetch(apiUrl(`${BASE}/materials/${materialId}`), {
      cache: "no-store",
    }),
  );
}

export async function deleteMaterial(materialId: string): Promise<void> {
  await unwrap(
    await apiFetch(apiUrl(`${BASE}/materials/${materialId}`), {
      method: "DELETE",
    }),
  );
}

export async function getUnitText(
  materialId: string,
  locator: number,
): Promise<{ locator: number; unit: UnitKind; text: string }> {
  return unwrap(
    await apiFetch(apiUrl(`${BASE}/materials/${materialId}/units/${locator}`), {
      cache: "no-store",
    }),
  );
}

export async function listReadingExtensions(): Promise<
  ReadingExtensionManifest[]
> {
  const payload: unknown = await unwrap(
    await apiFetch(apiUrl(`${BASE}/extensions`), { cache: "no-store" }),
  );
  if (!Array.isArray(payload)) return [];
  return payload.filter(
    (row): row is ReadingExtensionManifest =>
      Boolean(row) &&
      typeof row === "object" &&
      typeof (row as ReadingExtensionManifest).id === "string" &&
      Array.isArray((row as ReadingExtensionManifest).actions),
  );
}

export async function runReadingExtension(
  materialId: string,
  extensionId: string,
  action: string,
  context: {
    locator: number;
    selection?: string;
    locale?: string;
  },
): Promise<ReadingExtensionResult> {
  return unwrap(
    await apiFetch(
      apiUrl(
        `${BASE}/materials/${materialId}/extensions/${extensionId}/actions/${action}`,
      ),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(context),
      },
    ),
  );
}

/** URL of the original bytes. Served with Range support so pdf.js can stream. */
export function rawMaterialUrl(materialId: string): string {
  return apiUrl(`${BASE}/materials/${materialId}/raw`);
}

export async function getReadingPosition(
  materialId: string,
): Promise<ReadingPosition> {
  return parseReadingPosition(
    await unwrap(
      await apiFetch(apiUrl(`${BASE}/materials/${materialId}/position`), {
        cache: "no-store",
      }),
    ),
  );
}

export async function saveReadingPosition(
  materialId: string,
  position: Pick<ReadingPosition, "locator" | "source_anchor" | "percentage">,
): Promise<ReadingPosition> {
  return parseReadingPosition(
    await unwrap(
      await apiFetch(apiUrl(`${BASE}/materials/${materialId}/position`), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(position),
      }),
    ),
  );
}

export async function listBookmarks(
  materialId: string,
): Promise<ReadingBookmark[]> {
  const data = await unwrap<{ bookmarks?: ReadingBookmark[] }>(
    await apiFetch(apiUrl(`${BASE}/materials/${materialId}/bookmarks`), {
      cache: "no-store",
    }),
  );
  return data.bookmarks ?? [];
}

/** Keep a place. Bookmarking an already-kept locator returns that bookmark. */
export async function addBookmark(
  materialId: string,
  locator: number,
  label = "",
): Promise<ReadingBookmark> {
  return unwrap(
    await apiFetch(apiUrl(`${BASE}/materials/${materialId}/bookmarks`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ locator, label }),
    }),
  );
}

export async function deleteBookmark(
  materialId: string,
  bookmarkId: string,
): Promise<void> {
  await unwrap(
    await apiFetch(
      apiUrl(`${BASE}/materials/${materialId}/bookmarks/${bookmarkId}`),
      { method: "DELETE" },
    ),
  );
}

export async function listAnnotations(
  materialId: string,
): Promise<AnnotationItem[]> {
  return unwrap(
    await apiFetch(apiUrl(`${BASE}/materials/${materialId}/annotations`), {
      cache: "no-store",
    }),
  );
}

export async function saveAnnotation(
  materialId: string,
  draft: AnnotationDraft,
): Promise<AnnotationItem> {
  return unwrap(
    await apiFetch(apiUrl(`${BASE}/materials/${materialId}/annotations`), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(draft),
    }),
  );
}

export async function deleteAnnotation(
  materialId: string,
  annotationId: string,
): Promise<void> {
  await unwrap(
    await apiFetch(
      apiUrl(`${BASE}/materials/${materialId}/annotations/${annotationId}`),
      { method: "DELETE" },
    ),
  );
}

/**
 * Fetch the annotated export as a blob.
 *
 * Deliberately a fetch rather than a plain link: the download must carry the
 * session credentials `apiFetch` attaches, and a bare `<a href>` would not.
 */
export async function fetchExport(
  materialId: string,
  fmt: ExportFormat = "auto",
): Promise<{ blob: Blob; filename: string }> {
  const response = await apiFetch(
    apiUrl(`${BASE}/materials/${materialId}/export?fmt=${fmt}`),
  );
  if (!response.ok) {
    await unwrap(response);
    throw new Error(`Export failed: ${response.status}`);
  }
  return {
    blob: await response.blob(),
    filename: filenameFromDisposition(
      response.headers.get("content-disposition"),
    ),
  };
}

/**
 * Parse a filename out of a Content-Disposition header.
 *
 * Prefers the RFC 5987 `filename*` form so non-ASCII titles (a Chinese paper,
 * say) keep their name instead of arriving as the stripped ASCII fallback.
 */
export function filenameFromDisposition(
  header: string | null,
  fallback = "export",
): string {
  if (!header) return fallback;
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(header);
  if (encoded?.[1]) {
    try {
      return decodeURIComponent(encoded[1].trim());
    } catch {
      // Malformed percent-encoding — fall through to the plain form.
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(header);
  return plain?.[1]?.trim() || fallback;
}
