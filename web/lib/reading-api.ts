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
export type RenderMode = "text" | "pdf" | "epub";
export type ContentFormat = "plain_text" | "markdown" | "pdf" | "epub";

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
  render_mode: RenderMode;
  annotation_count: number;
  source_type?:
    | "upload"
    | "url_snapshot"
    | "kb_file"
    | "kb_web_tutorial"
    | "derived_epub";
  source_ref?: string;
  source_url?: string;
  kb_name?: string;
  kb_path?: string;
  revision_id?: string;
  captured_at?: number;
  previous_revision_id?: string;
  tutorial_available?: boolean;
  navigation_kind?: string;
  content_format?: ContentFormat;
  bilingual_available?: boolean;
  bilingual_languages?: string[];
  bilingual_pairing_ids?: string[];
}

export interface OutlineRow {
  locator: number;
  title: string;
  level: number;
  synthesised: boolean;
  source_url?: string;
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
  revision_id?: string;
  migration_status?: "native" | "migrated" | "needs_review";
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

export interface BilingualGroup {
  group_id: string;
  locator: number;
  source_markdown: string;
  translation_markdown: string;
  source_language: string;
  target_language: string;
  confidence: number;
  low_confidence: boolean;
}

export interface EpubPairingCandidate {
  material_id: string;
  title: string;
  filename: string;
  language: string;
  author: string;
  score: number;
  reasons: Record<string, number | boolean>;
}

export interface SupportedFormats {
  extensions: string[];
  max_bytes: number;
  raw_view_extensions: string[];
}

export interface ReadingExtensionAction {
  id: string;
  label: string;
  trigger: string;
  requires: string[];
}

export interface ReadingExtensionManifest {
  id: string;
  version: string;
  name: string;
  protocol_version: string;
  actions: ReadingExtensionAction[];
  result_types: string[];
}

export interface ReadingExtensionResult {
  type: "browser_speech" | "card" | "quiz" | "feedback" | string;
  interaction_id: string;
  title: string;
  message: string;
  payload: Record<string, unknown>;
  event_id?: string;
}

const BASE = "/api/v1/reading";

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
    ) detail = String((body.detail as { message: unknown }).message);
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

export async function createMaterialFromUrl(
  url: string,
  options?: { whole_tutorial?: boolean; max_depth?: number; max_pages?: number },
): Promise<MaterialDetail> {
  return unwrap(
    await apiFetch(apiUrl(`${BASE}/materials/from-url`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, ...options }),
    }),
  );
}

export async function createMaterialFromKb(input: {
  kb_name: string;
  file_path?: string;
  web_source_id?: string;
}): Promise<MaterialDetail> {
  return unwrap(
    await apiFetch(apiUrl(`${BASE}/materials/from-kb`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }),
  );
}

export async function listMaterialRevisions(materialId: string): Promise<MaterialInfo[]> {
  return unwrap(
    await apiFetch(apiUrl(`${BASE}/materials/${materialId}/revisions`), {
      cache: "no-store",
    }),
  );
}

export async function activateMaterialRevision(
  materialId: string,
  revisionId: string,
): Promise<MaterialDetail> {
  return unwrap(
    await apiFetch(
      apiUrl(`${BASE}/materials/${materialId}/revisions/${revisionId}/activate`),
      { method: "POST" },
    ),
  );
}

export async function saveMaterialToKb(
  materialId: string,
  kbName: string,
): Promise<MaterialDetail> {
  return unwrap(
    await apiFetch(apiUrl(`${BASE}/materials/${materialId}/save-to-kb`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kb_name: kbName }),
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

export async function getBilingualUnit(
  materialId: string,
  locator: number,
): Promise<{ locator: number; groups: BilingualGroup[] }> {
  return unwrap(
    await apiFetch(
      apiUrl(`${BASE}/materials/${materialId}/units/${locator}/bilingual`),
      { cache: "no-store" },
    ),
  );
}

export async function repairLegacyEpub(materialId: string): Promise<MaterialDetail> {
  return unwrap(
    await apiFetch(apiUrl(`${BASE}/materials/${materialId}/repair-epub`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    }),
  );
}

export async function listEpubPairingCandidates(
  materialId: string,
): Promise<EpubPairingCandidate[]> {
  return unwrap(
    await apiFetch(
      apiUrl(`${BASE}/materials/${materialId}/epub-pairing-candidates`),
      { cache: "no-store" },
    ),
  );
}

export async function createEpubPairing(
  englishMaterialId: string,
  chineseMaterialId: string,
): Promise<{ pairing: Record<string, unknown>; material: MaterialDetail }> {
  return unwrap(
    await apiFetch(apiUrl(`${BASE}/epub-pairings`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        english_material_id: englishMaterialId,
        chinese_material_id: chineseMaterialId,
      }),
    }),
  );
}

export async function listReadingExtensions(): Promise<ReadingExtensionManifest[]> {
  return unwrap(
    await apiFetch(apiUrl(`${BASE}/extensions`), { cache: "no-store" }),
  );
}

export async function runReadingExtension(
  materialId: string,
  extensionId: string,
  action: string,
  context: {
    locator: number;
    source_anchor?: string;
    selection?: string;
    visible_text?: string;
    locale?: string;
  },
): Promise<ReadingExtensionResult> {
  return unwrap(
    await apiFetch(
      apiUrl(
        `${BASE}/materials/${encodeURIComponent(materialId)}/extensions/${encodeURIComponent(extensionId)}/actions/${encodeURIComponent(action)}`,
      ),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(context),
      },
    ),
  );
}

export async function submitReadingInteraction(
  materialId: string,
  extensionId: string,
  interactionId: string,
  values: Record<string, unknown>,
): Promise<ReadingExtensionResult> {
  return unwrap(
    await apiFetch(
      apiUrl(
        `${BASE}/materials/${encodeURIComponent(materialId)}/extensions/${encodeURIComponent(extensionId)}/interactions/${encodeURIComponent(interactionId)}/submit`,
      ),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ values }),
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
  return unwrap(
    await apiFetch(apiUrl(`${BASE}/materials/${materialId}/position`), {
      cache: "no-store",
    }),
  );
}

export async function saveReadingPosition(
  materialId: string,
  position: Pick<ReadingPosition, "locator" | "source_anchor" | "percentage">,
): Promise<ReadingPosition> {
  return unwrap(
    await apiFetch(apiUrl(`${BASE}/materials/${materialId}/position`), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(position),
    }),
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
