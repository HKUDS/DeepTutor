import { apiFetch, apiUrl } from "@/lib/api";
import { settingsAnchorHref } from "@/features/settings/navigation/settings-nav";

export const READINESS_STATES = [
  "enabled_verified",
  "available_disabled",
  "unavailable",
  "misconfigured",
  "not_selected",
] as const;

export type ReadinessState = (typeof READINESS_STATES)[number];

/** States in which a capability is running, or one toggle away from it. */
export const USABLE_READINESS_STATES: ReadonlySet<ReadinessState> = new Set([
  "enabled_verified",
  "available_disabled",
]);

/**
 * How loudly a row deserves to be reported.
 *
 * The distinction that matters: an optional capability nobody set up is not a
 * fault. Only something the install *needs*, or something the operator did
 * configure and that now fails, earns a place in the attention list.
 */
export const READINESS_SEVERITIES = [
  "blocker",
  "warning",
  "suggestion",
] as const;

export type ReadinessSeverity = (typeof READINESS_SEVERITIES)[number];

export interface SettingsReadinessRow {
  id: string;
  section: string;
  label: string;
  state: ReadinessState;
  detail_code: string;
  enabled: boolean;
  available: boolean;
  configured: boolean;
  verified: boolean;
  /** Whether the install genuinely depends on this capability. */
  required: boolean;
}

export interface SettingsReadinessNotice {
  code: string;
  row_id: string;
  section: string;
  severity: ReadinessSeverity;
}

export interface SettingsReadinessSnapshot {
  schema_version: "deeptutor.settings-readiness/v2";
  ok: boolean;
  summary: Record<ReadinessState, number>;
  rows: SettingsReadinessRow[];
  notices: SettingsReadinessNotice[];
}

/**
 * Reading order for the matrix: what runs every turn first, infrastructure
 * last. Sections the backend adds later fall in after these, in the order it
 * sent them, rather than disappearing.
 */
export const READINESS_SECTION_ORDER = [
  "catalog",
  "knowledge",
  "document_parsing",
  "tools",
  "visualizers",
  "video_learning",
  "runtime",
] as const;

export function summarizeReadinessRows(
  rows: SettingsReadinessRow[],
): Record<ReadinessState, number> {
  const summary = Object.fromEntries(
    READINESS_STATES.map((state) => [state, 0]),
  ) as Record<ReadinessState, number>;
  for (const row of rows) summary[row.state] += 1;
  return summary;
}

export function groupReadinessRows<Row extends SettingsReadinessRow>(
  rows: Row[],
): Array<[string, Row[]]> {
  const groups = new Map<string, Row[]>();
  for (const row of rows) {
    const group = groups.get(row.section) ?? [];
    group.push(row);
    groups.set(row.section, group);
  }
  const declared = READINESS_SECTION_ORDER as readonly string[];
  return [...groups.entries()].sort(([left], [right]) => {
    const leftRank = declared.indexOf(left);
    const rightRank = declared.indexOf(right);
    if (leftRank === rightRank) return 0;
    if (leftRank === -1) return 1;
    if (rightRank === -1) return -1;
    return leftRank - rightRank;
  });
}

/**
 * Mirrors `deeptutor.services.config.readiness.row_severity`, so the client
 * can grade rows it has refined locally (a service whose last connection test
 * failed in this browser is not something the server knows about).
 */
export function readinessRowSeverity(
  row: Pick<SettingsReadinessRow, "state" | "required">,
): ReadinessSeverity | null {
  if (row.required && !USABLE_READINESS_STATES.has(row.state)) return "blocker";
  if (row.state === "misconfigured") return "warning";
  return null;
}

/** Rows worth showing unfolded: what runs, and what needs a hand. */
export function isProminentReadinessRow(row: SettingsReadinessRow): boolean {
  return row.state === "enabled_verified" || readinessRowSeverity(row) !== null;
}

/**
 * Detail codes the panel has a sentence for, as `readiness.detail.<code>`.
 *
 * The backend's `DETAIL_CODES` is the full set; the ones left out here are the
 * "this row is running" codes, which need no sentence beside a Ready label.
 * `tests/settings-readiness-i18n.test.ts` holds the two files to that split,
 * so a new backend code cannot reach a user as a raw identifier.
 */
export const EXPLAINED_DETAIL_CODES: ReadonlySet<string> = new Set([
  "active_profile_not_selected",
  "active_profile_missing",
  "active_model_not_selected",
  "active_model_missing",
  "model_identifier_missing",
  "provider_not_selected",
  "required_credential_missing",
  "connection_test_failed",
  "selected_parser_unavailable",
  "selected_parser_unreachable",
  "selected_parser_unknown",
  "parser_not_ready",
  "parser_probe_failed",
  "parser_not_selected",
  "parser_package_missing",
  "not_configured",
  "update_required",
  "models_missing",
  "cli_missing",
  "no_knowledge_base",
  "knowledge_base_building",
  "knowledge_base_needs_reindex",
  "rag_prerequisite_missing",
  "knowledge_base_not_ready",
  "visualizer_disabled",
  "visualizer_not_installed",
  "visualizer_runtime_missing",
  "tool_disabled",
  "tool_backend_not_configured",
  "enabled_tool_backend_failing",
  "tool_backend_unavailable",
  "video_provider_not_selected",
  "video_provider_not_configured",
  "selected_video_provider_not_configured",
  "selected_video_provider_unknown",
  "coordination_not_selected",
  "redis_url_missing",
  "redis_unreachable",
  "redis_not_configured",
  "multiple_workers_require_redis",
  "redis_available_but_memory_selected",
]);

const CATALOG_ANCHORS: Record<string, string> = {
  llm: "llm",
  task: "task-models",
  embedding: "embedding",
  search: "search",
  tts: "tts",
  stt: "stt",
  imagegen: "imagegen",
  videogen: "videogen",
};

const SECTION_ANCHORS: Record<string, string> = {
  // `#document-parsing` is the nav's label for it, but the mounted anchor for
  // the parsing section is the category key.
  "parser.": "knowledge",
  "tool.": "tools",
  "video.": "video-learning",
  "runtime.": "network",
};

/** Where a row is actually fixed. Knowledge bases live outside settings. */
export function readinessRowHref(rowId: string): string | null {
  if (rowId.startsWith("catalog.")) {
    const anchor = CATALOG_ANCHORS[rowId.slice("catalog.".length)];
    return anchor ? settingsAnchorHref(anchor) : null;
  }
  if (rowId.startsWith("knowledge.")) return "/knowledge-bases";
  for (const [prefix, anchor] of Object.entries(SECTION_ANCHORS)) {
    if (rowId.startsWith(prefix)) return settingsAnchorHref(anchor);
  }
  return null;
}

export async function fetchSettingsReadiness(): Promise<SettingsReadinessSnapshot> {
  const response = await apiFetch(apiUrl("/api/settings/readiness"));
  if (!response.ok)
    throw new Error("Capability readiness could not be loaded.");
  return (await response.json()) as SettingsReadinessSnapshot;
}
