import type { TFunction } from "i18next";

export interface KnowledgeUploadPolicy {
  extensions: string[];
  accept: string;
  max_file_size_bytes: number;
  max_pdf_size_bytes: number;
}

export const DEFAULT_UPLOAD_POLICY: KnowledgeUploadPolicy = {
  extensions: [],
  accept: "",
  max_file_size_bytes: 100 * 1024 * 1024,
  max_pdf_size_bytes: 50 * 1024 * 1024,
};

export interface ProgressInfo {
  task_id?: string;
  stage?: string;
  message?: string;
  current?: number;
  total?: number;
  percent?: number;
  progress_percent?: number;
  indexed_count?: number;
  index_changed?: boolean;
  index_action?: string;
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

export const resolveKbStatus = (kb: KnowledgeBase): string =>
  kb.status ?? kb.statistics?.status ?? "unknown";

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
  "extracting_items",
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
    } else if (
      extension === ".pdf" &&
      file.size > uploadPolicy.max_pdf_size_bytes
    ) {
      error = t("PDF files must be smaller than {{size}}.", {
        size: formatFileSize(uploadPolicy.max_pdf_size_bytes),
      });
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
