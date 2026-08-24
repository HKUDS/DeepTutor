import type { TFunction } from "i18next";

export interface KnowledgeUploadPolicy {
  extensions: string[];
  accept: string;
  max_file_size_bytes: number;
}

export const DEFAULT_UPLOAD_POLICY: KnowledgeUploadPolicy = {
  extensions: [],
  accept: "",
  max_file_size_bytes: 200 * 1024 * 1024,
};

const PAGEINDEX_UPLOAD_EXTENSIONS: Record<string, string[]> = {
  pageindex: [
    ".pdf",
    ".md",
    ".markdown",
    ".txt",
    ".docx",
    ".doc",
    ".pptx",
    ".ppt",
    ".xlsx",
    ".xls",
    ".csv",
  ],
  "pageindex-oss": [".pdf"],
};

export function uploadPolicyForProvider(
  policy: KnowledgeUploadPolicy,
  provider?: string,
): KnowledgeUploadPolicy {
  const extensions = PAGEINDEX_UPLOAD_EXTENSIONS[provider || ""];
  return extensions
    ? { ...policy, extensions, accept: extensions.join(",") }
    : policy;
}

export interface ProgressInfo {
  task_id?: string;
  stage?: string;
  /** Rendered English. Prefer `progressMessage()`, which translates. */
  message?: string;
  /** English `{{name}}` template the backend formatted `message` from. */
  message_key?: string;
  message_params?: Record<string, string | number>;
  current?: number;
  total?: number;
  percent?: number;
  progress_percent?: number;
  indexed_count?: number;
  index_changed?: boolean;
  index_action?: string;
  error?: string;
  error_code?: string;
  retryable?: boolean;
}

/**
 * The progress line to show, translated when the backend named its template.
 *
 * Indexing runs detached from any request, so the backend has no viewer
 * language and sends the English template plus its values; `t()` is where the
 * language is actually known. Falls back to the rendered English for progress
 * emitted before a producer was converted.
 */
export function progressMessage(
  progress: Pick<ProgressInfo, "message" | "message_key" | "message_params">,
  t: (key: string, options?: Record<string, unknown>) => string,
): string | undefined {
  if (!progress.message_key) return progress.message;
  return t(progress.message_key, progress.message_params ?? {});
}

export interface KnowledgeIndexFailure {
  code?: string;
  message?: string;
  retryable?: boolean;
  requiresModelChange: boolean;
  settingsHref?: string;
}

export interface IndexVersion {
  signature?: string;
  model?: string;
  dimension?: number;
  binding?: string;
  created_at?: string;
  ready?: boolean;
  legacy?: boolean;
}

export interface KnowledgeBase {
  id?: string;
  name: string;
  is_default?: boolean;
  status?: string;
  path?: string;
  metadata?: {
    created_at?: string;
    last_updated?: string;
    last_indexed_at?: string;
    last_indexed_count?: number;
    last_indexed_action?: string;
    rag_provider?: string;
    needs_reindex?: boolean;
    embedding_model?: string;
    embedding_dim?: number;
    embedding_mismatch?: boolean;
    /** Connected-source kind (e.g. "obsidian", "subagent"); absent for ordinary indexed KBs. */
    type?: string;
    /** Absolute path of a connected Obsidian vault (when type === "obsidian"). */
    vault_path?: string;
    /** SQLite store of a connected MarginNote 4 library (when type === "marginnote4"). */
    db_path?: string;
    /** Backend of a connected subagent (when type === "subagent"): "claude_code" | "codex" | "gemini" | "antigravity" | "kimi" | "opencode" | "mimo" | "partner". */
    agent_kind?: string;
    /** Bound partner id when agent_kind === "partner". */
    partner_id?: string;
  };
  progress?: ProgressInfo;
  statistics?: {
    raw_documents?: number;
    images?: number;
    content_lists?: number;
    rag_provider?: string;
    rag_initialized?: boolean;
    needs_reindex?: boolean;
    status?: string;
    progress?: ProgressInfo;
    index_versions?: IndexVersion[];
    active_signature?: string | null;
    active_match?: boolean;
  };
  source?: "admin" | "user";
  assigned?: boolean;
  read_only?: boolean;
  provenance_label?: string;
  available?: boolean;
}

export type ProviderConnectionStatus = "ready" | "needs_key" | "unavailable";

export const providerUsesEmbeddingMetadata = (provider?: string): boolean =>
  provider !== "pageindex" && provider !== "pageindex-oss";

export const providerConnectionStatus = (provider: {
  id: string;
  configured?: boolean;
  requires_api_key?: boolean;
}): ProviderConnectionStatus => {
  if (provider.requires_api_key && provider.configured === false)
    return "needs_key";
  if (provider.configured === false) return "unavailable";
  return "ready";
};

export interface ValidatedSelectionFile {
  id: string;
  file: File;
  extension: string;
  sizeLabel: string;
  valid: boolean;
  error: string | null;
}

export interface ValidatedFileSelection {
  items: ValidatedSelectionFile[];
  validFiles: File[];
  invalidFiles: ValidatedSelectionFile[];
  totalBytes: number;
}

export const formatFileSize = (bytes: number): string => {
  if (bytes >= 1024 * 1024 * 1024)
    return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${bytes} B`;
};

export const getFileExtension = (filename: string): string => {
  const index = filename.lastIndexOf(".");
  return index >= 0 ? filename.slice(index).toLowerCase() : "";
};

export const selectionFileId = (file: File): string =>
  `${file.name}:${file.size}:${file.lastModified}`;

export const mergeSelectedFiles = (
  existing: File[],
  incoming: File[],
): File[] => {
  const merged = new Map<string, File>();
  [...existing, ...incoming].forEach((file) => {
    merged.set(selectionFileId(file), file);
  });
  return Array.from(merged.values());
};

const parseKnowledgeTimestamp = (value?: string): Date | null => {
  if (!value) return null;
  const normalized = value.includes("T") ? value : value.replace(" ", "T");
  const parsed = new Date(normalized);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
};

export const formatKnowledgeTimestamp = (value?: string): string | null => {
  const parsed = parseKnowledgeTimestamp(value);
  return parsed ? parsed.toLocaleString() : value || null;
};

export const MARGINNOTE4_KB_TYPE = "marginnote4";

/**
 * A connected MarginNote 4 library.
 *
 * It owns no documents and no index: the Add-on pushes objects into its own
 * store and the MarginNote tools read them, so the file, add-documents and
 * index-version surfaces have nothing to act on.
 */
export const isMarginNoteKb = (kb: KnowledgeBase): boolean =>
  kb.metadata?.type === MARGINNOTE4_KB_TYPE;

export const KB_DETAIL_SECTIONS = [
  "files",
  "add",
  "github",
  "versions",
  "devices",
  "settings",
] as const;

export type KbDetailSection = (typeof KB_DETAIL_SECTIONS)[number];

/**
 * The detail sections a KB has something to show in.
 *
 * A MarginNote library owns no raw files and builds no index, so files /
 * add-documents / index-versions would all render empty against it; what it
 * does have is the devices that feed it. Every other KB has the reverse.
 */
export const kbDetailSections = (kb: KnowledgeBase): KbDetailSection[] =>
  isMarginNoteKb(kb)
    ? ["devices", "settings"]
    : KB_DETAIL_SECTIONS.filter((section) => section !== "devices");

/** The retrieval engine a KB is bound to. Connected vaults badge by source. */
export const kbProvider = (kb: KnowledgeBase): string => {
  if (kb.metadata?.type === "obsidian") return "obsidian";
  if (isMarginNoteKb(kb)) return MARGINNOTE4_KB_TYPE;
  return (
    (kb.statistics?.rag_provider as string | undefined) ||
    (kb.metadata?.rag_provider as string | undefined) ||
    "llamaindex"
  );
};

/** Source-document count for a KB, or null when unknown. */
export const kbDocCount = (kb: KnowledgeBase): number | null => {
  const raw = kb.statistics?.raw_documents;
  if (typeof raw === "number") return raw;
  const indexed = kb.metadata?.last_indexed_count;
  return typeof indexed === "number" ? indexed : null;
};

export const resolveKbStatus = (kb: KnowledgeBase): string =>
  kb.status ?? kb.statistics?.status ?? "unknown";

export const resolveKnowledgeIndexFailure = (
  kb: KnowledgeBase,
): KnowledgeIndexFailure | null => {
  if (resolveKbStatus(kb) !== "error") return null;

  const progress = kb.progress;
  const storedProgress = kb.statistics?.progress;
  const code =
    progress?.error_code?.trim() ||
    storedProgress?.error_code?.trim() ||
    undefined;
  const message =
    progress?.error?.trim() ||
    storedProgress?.error?.trim() ||
    progress?.message?.trim() ||
    storedProgress?.message?.trim() ||
    undefined;

  const embeddingConfigurationCodes = new Set([
    "graphrag_embedding_authentication_failed",
    "graphrag_embedding_dimension_mismatch",
    "graphrag_embedding_endpoint_failed",
    "graphrag_embedding_incompatible",
    "graphrag_embedding_provider_unsupported",
  ]);
  const completionConfigurationCodes = new Set([
    "graphrag_model_incompatible",
    "graphrag_provider_unsupported",
    "graphrag_model_authentication_failed",
    "graphrag_model_endpoint_failed",
  ]);
  const requiresEmbeddingChange = embeddingConfigurationCodes.has(code ?? "");
  const requiresCompletionChange = completionConfigurationCodes.has(code ?? "");

  return {
    code,
    message,
    retryable: progress?.retryable ?? storedProgress?.retryable,
    requiresModelChange: requiresEmbeddingChange || requiresCompletionChange,
    settingsHref: requiresEmbeddingChange
      ? "/settings/embedding"
      : requiresCompletionChange
        ? "/settings/models"
        : undefined,
  };
};

export const taskFailureMessage = (payload: {
  detail?: string;
  details?: string;
}): string => payload.detail?.trim() || "Task failed";

export const kbNeedsReindex = (kb: KnowledgeBase): boolean =>
  Boolean(kb.statistics?.needs_reindex) ||
  resolveKbStatus(kb) === "needs_reindex";

export const kbIsUploadable = (kb: KnowledgeBase): boolean =>
  resolveKbStatus(kb) === "ready" && !kbNeedsReindex(kb);

export const kbCanReindex = (kb: KnowledgeBase): boolean => {
  const status = resolveKbStatus(kb);
  const hasSourceFiles =
    typeof kb.statistics?.raw_documents === "number"
      ? kb.statistics.raw_documents > 0
      : true;
  if (!hasSourceFiles) return false;
  if (status === "error") return true;
  return (
    Boolean(kb.statistics?.needs_reindex) ||
    kb.statistics?.active_match === false
  );
};

const LIVE_PROGRESS_STAGES = new Set([
  "initializing",
  "starting",
  "processing_documents",
  "processing_file",
]);

export const kbHasLiveProgress = (kb: KnowledgeBase): boolean => {
  const status = resolveKbStatus(kb);
  if (status === "ready" || status === "error" || status === "needs_reindex") {
    return false;
  }
  const stage = kb.progress?.stage;
  if (!stage) return false;
  if (stage === "completed" || stage === "error") return false;
  return LIVE_PROGRESS_STAGES.has(stage);
};

export const resolveProgressPercent = (progress?: ProgressInfo): number => {
  const directPercent = progress?.progress_percent ?? progress?.percent;
  if (typeof directPercent === "number") return directPercent;

  const current = progress?.current ?? 0;
  const total = progress?.total ?? 0;
  if (!current || !total) return 0;
  return Math.round((current / total) * 100);
};

export function validateFiles(
  files: File[],
  uploadPolicy: KnowledgeUploadPolicy,
  t: TFunction,
): ValidatedFileSelection {
  const allowedExtensions = new Set(
    uploadPolicy.extensions.map((ext) => ext.toLowerCase()),
  );

  const items = files.map((file) => {
    const extension = getFileExtension(file.name);
    let error: string | null = null;

    if (allowedExtensions.size > 0 && !allowedExtensions.has(extension)) {
      error = t("Unsupported file type");
    } else if (file.size > uploadPolicy.max_file_size_bytes) {
      error = t("This file exceeds the maximum size of {{size}}.", {
        size: formatFileSize(uploadPolicy.max_file_size_bytes),
      });
    }

    return {
      id: selectionFileId(file),
      file,
      extension: extension || t("No extension"),
      sizeLabel: formatFileSize(file.size),
      valid: !error,
      error,
    };
  });

  return {
    items,
    validFiles: items.filter((item) => item.valid).map((item) => item.file),
    invalidFiles: items.filter((item) => !item.valid),
    totalBytes: files.reduce((total, file) => total + file.size, 0),
  };
}
