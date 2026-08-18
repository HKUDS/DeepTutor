import { apiFetch, apiUrl } from "@/lib/api";

export type TranslationTaskStatus = "queued" | "running" | "completed" | "failed" | "cancelled";
export type TranslationSourceType = "bilingual" | "kb_document";
export type TranslationGlossaryDecision = "candidate" | "approved" | "rejected";

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
  glossary?: TranslationGlossaryEntry[];
  target_language: string;
  reason: string;
  priority: "high" | "normal" | "low";
  status: TranslationTaskStatus;
  attempts: number;
  error: string;
  created_at: number;
  updated_at: number;
  run_id?: string | null;
}

export interface TranslationTaskSummary {
  total: number;
  queued: number;
  running: number;
  completed: number;
  failed: number;
  cancelled: number;
  filtered_total: number;
  filtered_queued: number;
  filtered_running: number;
  filtered_completed: number;
  filtered_failed: number;
  filtered_cancelled: number;
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
  glossary?: TranslationGlossaryEntry[];
}

export interface TranslationGlossaryEntry {
  term: string;
  translation: string;
  kind: string;
  frequency: number;
  protected: boolean;
  approved: boolean;
  decision?: TranslationGlossaryDecision;
}

export interface TranslationRun {
  run_id: string;
  source_type?: TranslationSourceType | null;
  source_id?: string | null;
  chapter_id?: string | null;
  task_ids: string[];
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  sequence: number;
  completed: number;
  failed: number;
  created_at: number;
  updated_at: number;
}

export interface TranslationTaskEvent {
  type:
    | "snapshot"
    | "run_started"
    | "run_cancelled"
    | "group_translated"
    | "task_updated"
    | "run_completed"
    | "heartbeat";
  run_id?: string | null;
  sequence?: number;
  task?: TranslationTask & { translation?: string };
  board?: TranslationTaskBoard;
  selected_task_ids?: string[];
  completed?: number;
  failed?: number;
  parse_error?: boolean;
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

async function readEventStream(
  body: ReadableStream<Uint8Array>,
  onEvent: (data: string) => void,
) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const rawEvent = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const data = rawEvent
        .split(/\r?\n/)
        .filter((line) => line.startsWith("data: "))
        .map((line) => line.slice(6))
        .join("\n");
      if (data) onEvent(data);
      boundary = buffer.indexOf("\n\n");
    }
  }
}

const KNOWN_TRANSLATION_EVENTS = new Set<TranslationTaskEvent["type"]>([
  "snapshot",
  "run_started",
  "run_cancelled",
  "group_translated",
  "task_updated",
  "run_completed",
  "heartbeat",
]);

export function safeParseEvent(
  data: string,
  runId?: string | null,
): TranslationTaskEvent {
  try {
    const event = JSON.parse(data) as TranslationTaskEvent;
    if (!KNOWN_TRANSLATION_EVENTS.has(event.type)) {
      return invalidEvent(runId);
    }
    return event;
  } catch {
    return invalidEvent(runId);
  }
}

function invalidEvent(runId?: string | null): TranslationTaskEvent {
  return {
    type: "task_updated",
    run_id: runId ?? null,
    sequence: 0,
    parse_error: true,
  };
}

export const translationTaskApi = {
  list: (options?: {
    sourceType?: TranslationSourceType;
    sourceId?: string;
    chapterId?: string;
    status?: TranslationTaskStatus;
  }) =>
    request<TranslationTaskBoard>(
      sourcePath(options?.sourceType, options?.sourceId, options?.chapterId),
    ),
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
  }): Promise<TranslationTaskBoard & {
    started: boolean;
    run_id: string | null;
    selected_task_ids: string[];
    run?: TranslationRun;
  }> =>
    request("/api/v1/translation/tasks/run", {
      method: "POST",
      body: JSON.stringify({
        limit: options?.limit ?? 4,
        source_type: options?.sourceType,
        source_id: options?.sourceId,
        chapter_id: options?.chapterId,
      }),
    }),
  retry: (taskId: string) =>
    request<TranslationTaskBoard>(
      `/api/v1/translation/tasks/${encodeURIComponent(taskId)}/retry`,
      { method: "POST" },
    ),
  retryFailed: (sourceType?: TranslationSourceType, sourceId?: string) =>
    request<TranslationTaskBoard>("/api/v1/translation/tasks/retry-failed", {
      method: "POST",
      body: JSON.stringify({ source_type: sourceType, source_id: sourceId }),
    }),
  cancelRun: (runId: string) =>
    request<TranslationTaskBoard>(`/api/v1/translation/tasks/runs/${encodeURIComponent(runId)}/cancel`, {
      method: "POST",
    }),
  streamRun: async (
    runId: string,
    options: { onEvent: (event: TranslationTaskEvent) => void; signal?: AbortSignal },
  ) => {
    const response = await apiFetch(
      apiUrl(`/api/v1/translation/tasks/runs/${encodeURIComponent(runId)}/stream`),
      { signal: options.signal },
    );
    if (!response.ok || !response.body) {
      throw new Error(`Translation stream failed (${response.status})`);
    }
    await readEventStream(response.body, (data) =>
      options.onEvent(safeParseEvent(data, runId)),
    );
  },
  stream: async (options: {
    sourceType?: TranslationSourceType;
    sourceId?: string;
    chapterId?: string;
    limit?: number;
    onEvent: (event: TranslationTaskEvent) => void;
    signal?: AbortSignal;
  }) => {
    const params = new URLSearchParams();
    if (options.sourceType) params.set("source_type", options.sourceType);
    if (options.sourceId) params.set("source_id", options.sourceId);
    if (options.chapterId) params.set("chapter_id", options.chapterId);
    params.set("limit", String(options.limit ?? 8));
    const response = await apiFetch(
      apiUrl(`/api/v1/translation/tasks/stream?${params.toString()}`),
      { signal: options.signal },
    );
    if (!response.ok || !response.body) {
      throw new Error(`Translation stream failed (${response.status})`);
    }
    await readEventStream(response.body, (data) => options.onEvent(safeParseEvent(data)));
  },
  getGlossary: (sourceType: TranslationSourceType, sourceId: string) =>
    request<{ entries: TranslationGlossaryEntry[] }>(
      `/api/v1/translation/glossary?source_type=${encodeURIComponent(sourceType)}&source_id=${encodeURIComponent(sourceId)}`,
    ),
  updateGlossary: (
    sourceType: TranslationSourceType,
    sourceId: string,
    entries: TranslationGlossaryEntry[],
  ) =>
    request<TranslationTaskBoard>("/api/v1/translation/glossary", {
      method: "PUT",
      body: JSON.stringify({ source_type: sourceType, source_id: sourceId, entries }),
    }),
};
