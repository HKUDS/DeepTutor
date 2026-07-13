import { apiFetch, apiUrl } from "@/lib/api";

// ── Real notebook system (file-backed under data/user/workspace/notebook) ──
//
// Notebooks created in the Knowledge → Notebooks tab and consumed everywhere
// chat output is saved (SaveToNotebookModal) or referenced
// (NotebookRecordPicker) live in this system. They are distinct from the
// "Question Notebook" categories below which only track quiz entries.

export type NotebookRecordType =
  | "solve"
  | "question"
  | "research"
  | "chat"
  | "co_writer"
  | "tutorbot";

export interface NotebookSummary {
  id: string;
  name: string;
  description?: string;
  color?: string;
  icon?: string;
  record_count?: number;
  created_at?: number;
  updated_at?: number;
}

export interface NotebookRecordItem {
  id: string;
  type: NotebookRecordType | string;
  title: string;
  summary?: string;
  user_query: string;
  output: string;
  metadata?: Record<string, unknown>;
  created_at?: number;
  kb_name?: string | null;
}

export interface NotebookDetail extends NotebookSummary {
  records: NotebookRecordItem[];
}

export async function listNotebooks(): Promise<NotebookSummary[]> {
  const response = await apiFetch(apiUrl("/api/v1/notebook/list"), {
    cache: "no-store",
  });
  if (!response.ok) throw new Error(`Request failed: ${response.status}`);
  const data = (await response.json()) as { notebooks: NotebookSummary[] };
  return data.notebooks ?? [];
}

export async function getNotebook(notebookId: string): Promise<NotebookDetail> {
  const response = await apiFetch(apiUrl(`/api/v1/notebook/${notebookId}`), {
    cache: "no-store",
  });
  if (!response.ok) throw new Error(`Request failed: ${response.status}`);
  return (await response.json()) as NotebookDetail;
}

export async function createNotebook(payload: {
  name: string;
  description?: string;
  color?: string;
  icon?: string;
}): Promise<NotebookSummary> {
  const response = await apiFetch(apiUrl("/api/v1/notebook/create"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: payload.name,
      description: payload.description ?? "",
      color: payload.color ?? "#6366F1",
      icon: payload.icon ?? "book",
    }),
  });
  if (!response.ok) throw new Error(`Request failed: ${response.status}`);
  const data = (await response.json()) as { notebook: NotebookSummary };
  return data.notebook;
}

export async function updateNotebook(
  notebookId: string,
  payload: {
    name?: string;
    description?: string;
    color?: string;
    icon?: string;
  },
): Promise<NotebookSummary> {
  const response = await apiFetch(apiUrl(`/api/v1/notebook/${notebookId}`), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(`Request failed: ${response.status}`);
  const data = (await response.json()) as { notebook: NotebookSummary };
  return data.notebook;
}

export async function deleteNotebook(notebookId: string): Promise<void> {
  const response = await apiFetch(apiUrl(`/api/v1/notebook/${notebookId}`), {
    method: "DELETE",
  });
  if (!response.ok) throw new Error(`Request failed: ${response.status}`);
}

export async function deleteNotebookRecord(
  notebookId: string,
  recordId: string,
): Promise<void> {
  const response = await apiFetch(
    apiUrl(`/api/v1/notebook/${notebookId}/records/${recordId}`),
    { method: "DELETE" },
  );
  if (!response.ok) throw new Error(`Request failed: ${response.status}`);
}

// ── Question notebook (quiz entries + categories) ─────────────────

export interface NotebookAnswerImage {
  id: string;
  url: string;
  filename: string;
  mime_type: string;
}

export interface NotebookEntry {
  id: number;
  session_id: string;
  session_title: string;
  turn_id: string;
  question_id: string;
  question: string;
  question_type: string;
  options: Record<string, string>;
  correct_answer: string;
  explanation: string;
  difficulty: string;
  user_answer: string;
  user_answer_images?: NotebookAnswerImage[];
  is_correct: boolean;
  bookmarked: boolean;
  followup_session_id: string;
  /** Latest AI-judge text for this entry; empty when never run. */
  ai_judgment?: string;
  created_at: number;
  updated_at: number;
  categories?: NotebookCategory[];
}

export interface NotebookCategory {
  id: number;
  name: string;
  created_at: number;
  entry_count: number;
}

export interface NotebookEntryListResponse {
  items: NotebookEntry[];
  total: number;
}

async function expectJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

// ── Entries ──────────────────────────────────────────────────────

export async function listNotebookEntries(
  filter: {
    category_id?: number;
    bookmarked?: boolean;
    is_correct?: boolean;
    limit?: number;
    offset?: number;
  } = {},
): Promise<NotebookEntryListResponse> {
  const params = new URLSearchParams();
  if (filter.category_id !== undefined)
    params.set("category_id", String(filter.category_id));
  if (filter.bookmarked !== undefined)
    params.set("bookmarked", String(filter.bookmarked));
  if (filter.is_correct !== undefined)
    params.set("is_correct", String(filter.is_correct));
  if (filter.limit !== undefined) params.set("limit", String(filter.limit));
  if (filter.offset !== undefined) params.set("offset", String(filter.offset));
  const query = params.toString();
  const response = await apiFetch(
    apiUrl(`/api/v1/question-notebook/entries${query ? `?${query}` : ""}`),
    { cache: "no-store" },
  );
  return expectJson<NotebookEntryListResponse>(response);
}

export async function getNotebookEntry(
  entryId: number,
): Promise<NotebookEntry> {
  const response = await apiFetch(
    apiUrl(`/api/v1/question-notebook/entries/${entryId}`),
    {
      cache: "no-store",
    },
  );
  return expectJson<NotebookEntry>(response);
}

export async function lookupNotebookEntry(
  sessionId: string,
  questionId: string,
  turnId?: string | null,
): Promise<NotebookEntry | null> {
  const params = new URLSearchParams({
    session_id: sessionId,
    question_id: questionId,
    // Probe quietly: a not-yet-saved question returns 204 instead of 404, so
    // it stays out of the server error log and the browser network console.
    missing_ok: "true",
  });
  if (turnId) params.set("turn_id", turnId);
  const response = await apiFetch(
    apiUrl(`/api/v1/question-notebook/entries/lookup/by-question?${params}`),
  );
  // 204 (missing_ok hit) and 404 (older servers) both mean "no entry yet".
  if (response.status === 204 || response.status === 404) return null;
  return expectJson<NotebookEntry>(response);
}

export async function updateNotebookEntry(
  entryId: number,
  updates: {
    bookmarked?: boolean;
    followup_session_id?: string;
    ai_judgment?: string;
  },
): Promise<void> {
  const response = await apiFetch(
    apiUrl(`/api/v1/question-notebook/entries/${entryId}`),
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updates),
    },
  );
  await expectJson<{ updated: boolean }>(response);
}

export interface NotebookAnswerImageUpload {
  id?: string;
  /** Base64 (no ``data:`` prefix) for a freshly-picked image. */
  base64?: string;
  /** Existing AttachmentStore URL for an already-persisted image. */
  url?: string;
  filename: string;
  mime_type: string;
}

export async function upsertNotebookEntry(data: {
  session_id: string;
  turn_id?: string;
  question_id: string;
  question: string;
  question_type?: string;
  options?: Record<string, string>;
  correct_answer?: string;
  explanation?: string;
  difficulty?: string;
  user_answer?: string;
  /**
   * Optional list of images attached to the learner's answer. Omit to
   * leave any stored images untouched; pass an empty array to clear them.
   */
  user_answer_images?: NotebookAnswerImageUpload[];
  is_correct?: boolean;
}): Promise<NotebookEntry> {
  const response = await apiFetch(
    apiUrl("/api/v1/question-notebook/entries/upsert"),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...data,
        options: data.options || {},
        explanation: data.explanation || "",
        difficulty: data.difficulty || "",
      }),
    },
  );
  return expectJson<NotebookEntry>(response);
}

export async function deleteNotebookEntry(entryId: number): Promise<void> {
  const response = await apiFetch(
    apiUrl(`/api/v1/question-notebook/entries/${entryId}`),
    {
      method: "DELETE",
    },
  );
  await expectJson<{ deleted: boolean }>(response);
}

// ── Entry ↔ Category ────────────────────────────────────────────

export async function addEntryToCategory(
  entryId: number,
  categoryId: number,
): Promise<void> {
  const response = await apiFetch(
    apiUrl(`/api/v1/question-notebook/entries/${entryId}/categories`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ category_id: categoryId }),
    },
  );
  await expectJson<{ added: boolean }>(response);
}

export async function removeEntryFromCategory(
  entryId: number,
  categoryId: number,
): Promise<void> {
  const response = await apiFetch(
    apiUrl(
      `/api/v1/question-notebook/entries/${entryId}/categories/${categoryId}`,
    ),
    { method: "DELETE" },
  );
  await expectJson<{ removed: boolean }>(response);
}

// ── Categories ──────────────────────────────────────────────────

export async function listCategories(): Promise<NotebookCategory[]> {
  const response = await apiFetch(
    apiUrl("/api/v1/question-notebook/categories"),
    {
      cache: "no-store",
    },
  );
  return expectJson<NotebookCategory[]>(response);
}

export async function createCategory(name: string): Promise<NotebookCategory> {
  const response = await apiFetch(
    apiUrl("/api/v1/question-notebook/categories"),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    },
  );
  return expectJson<NotebookCategory>(response);
}

export async function renameCategory(
  categoryId: number,
  name: string,
): Promise<void> {
  const response = await apiFetch(
    apiUrl(`/api/v1/question-notebook/categories/${categoryId}`),
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    },
  );
  await expectJson<{ updated: boolean }>(response);
}

export async function deleteCategory(categoryId: number): Promise<void> {
  const response = await apiFetch(
    apiUrl(`/api/v1/question-notebook/categories/${categoryId}`),
    {
      method: "DELETE",
    },
  );
  await expectJson<{ deleted: boolean }>(response);
}
