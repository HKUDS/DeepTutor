import { apiFetch, apiUrl } from "@/lib/api";

// ── Immersive reading (materials under data/user/workspace/reading) ──
//
// A *material* is a document the user reads in the reader pane. It is cut once
// into **units** and addressed by **locator** — a 1-indexed unit number that
// means page / chapter / slide / section depending on the source format. The
// unit word is carried on the material so the UI can say "page 12" or
// "chapter 3" without ever branching on the file type itself.

export type UnitKind = "page" | "chapter" | "slide" | "section";
export type AnnotationKind = "highlight" | "underline" | "note";
export type ExportFormat = "auto" | "pdf" | "markdown";

/** Palette offered by the annotation toolbar; mirrored server-side. */
export const ANNOTATION_COLORS = [
  "yellow",
  "green",
  "blue",
  "pink",
  "purple",
] as const;
export type AnnotationColor = (typeof ANNOTATION_COLORS)[number];

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

export interface AnnotationItem {
  annotation_id: string;
  locator: number;
  kind: AnnotationKind;
  color: string;
  quote: string;
  note: string;
  rects: NormalisedRect[];
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
}

export interface SupportedFormats {
  extensions: string[];
  max_bytes: number;
  raw_view_extensions: string[];
}

const BASE = "/api/v1/reading";

/** Surface the server's own message — it explains what the user can do next. */
async function unwrap<T>(response: Response): Promise<T> {
  if (response.ok) return (await response.json()) as T;
  let detail = `Request failed: ${response.status}`;
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body?.detail === "string" && body.detail) detail = body.detail;
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

export async function uploadMaterial(file: File): Promise<MaterialDetail> {
  const form = new FormData();
  form.append("file", file, file.name);
  return unwrap(
    await apiFetch(apiUrl(`${BASE}/materials`), { method: "POST", body: form }),
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

/** URL of the original bytes. Served with Range support so pdf.js can stream. */
export function rawMaterialUrl(materialId: string): string {
  return apiUrl(`${BASE}/materials/${materialId}/raw`);
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
