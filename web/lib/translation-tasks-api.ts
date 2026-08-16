import { apiFetch, apiUrl } from "@/lib/api";

export type TranslationTaskStatus = "queued" | "running" | "completed" | "failed";
export type TranslationSourceType = "bilingual" | "kb_document";

export interface TranslationTask {
  id: string;
  source_type: TranslationSourceType;
  source_id: string;
  source_label: string;
  title: string;
  chapter_id: string;
  chapter_index: number;
  group_index: number;
  source_text: string;
  target_language: string;
  reason: string;
  priority: "high" | "normal" | "low";
  status: TranslationTaskStatus;
  attempts: number;
  error: string;
  created_at: number;
  updated_at: number;
}

export interface TranslationTaskSummary {
  total: number;
  queued: number;
  running: number;
  completed: number;
  failed: number;
  filtered_total: number;
  filtered_queued: number;
  filtered_running: number;
  filtered_completed: number;
  filtered_failed: number;
  is_running: boolean;
  last_run_at: number;
}

export interface TranslationSourceSummary {
  source_type: TranslationSourceType;
  source_id: string;
  label: string;
  total_units: number;
  translated_units: number;
  all_translated: boolean;
  updated_at: number;
}

export interface TranslationChapterSummary {
  chapter_id: string;
  chapter_index: number;
  title: string;
  total_units: number;
  translated_units: number;
  completed: boolean;
}

export interface TranslationDocumentSummary {
  document_path: string;
  title: string;
  completed: boolean;
}

export interface TranslationTaskBoard {
  tasks: TranslationTask[];
  summary: TranslationTaskSummary;
  sources: TranslationSourceSummary[];
  chapters?: TranslationChapterSummary[];
  documents?: TranslationDocumentSummary[];
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body) headers.set("Content-Type", "application/json");
  const response = await apiFetch(apiUrl(path), { ...init, headers });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body?.detail || detail;
    } catch {
      // Keep the HTTP status text.
    }
    throw new Error(String(detail));
  }
  return (await response.json()) as T;
}

function sourcePath(
  sourceType?: TranslationSourceType,
  sourceId?: string,
  chapterId?: string,
): string {
  const params = new URLSearchParams();
  if (sourceType) params.set("source_type", sourceType);
  if (sourceId) params.set("source_id", sourceId);
  if (chapterId) params.set("chapter_id", chapterId);
  const query = params.toString();
  return `/api/v1/translation/tasks${query ? `?${query}` : ""}`;
}

export const translationTaskApi = {
  list: (options?: {
    sourceType?: TranslationSourceType;
    sourceId?: string;
    chapterId?: string;
    status?: TranslationTaskStatus;
  }) => request<TranslationTaskBoard>(sourcePath(options?.sourceType, options?.sourceId, options?.chapterId)),
  plan: (sourceType: TranslationSourceType, sourceId: string, force = false) =>
    request<TranslationTaskBoard>("/api/v1/translation/tasks/plan", {
      method: "POST",
      body: JSON.stringify({ source_type: sourceType, source_id: sourceId, force }),
    }),
  run: (options?: {
    sourceType?: TranslationSourceType;
    sourceId?: string;
    chapterId?: string;
    limit?: number;
  }) =>
    request<TranslationTaskBoard & { started: boolean }>("/api/v1/translation/tasks/run", {
      method: "POST",
      body: JSON.stringify({
        limit: options?.limit ?? 4,
        source_type: options?.sourceType,
        source_id: options?.sourceId,
        chapter_id: options?.chapterId,
      }),
    }),
  retry: (taskId: string) =>
    request<TranslationTaskBoard>(`/api/v1/translation/tasks/${encodeURIComponent(taskId)}/retry`, {
      method: "POST",
    }),
  retryFailed: (sourceType?: TranslationSourceType, sourceId?: string) =>
    request<TranslationTaskBoard>("/api/v1/translation/tasks/retry-failed", {
      method: "POST",
      body: JSON.stringify({ source_type: sourceType, source_id: sourceId }),
    }),
};
