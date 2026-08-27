import { apiUrl, apiFetch } from "./api";

export interface ModuleInit {
  id: string;
  name: string;
  order: number;
  pass_threshold?: number;
  knowledge_points: {
    id: string;
    name: string;
    type: string;
    module_id: string;
  }[];
}

export interface LearningKnowledgePoint {
  id: string;
  name: string;
  type: string;
}

export interface LearningModule {
  id: string;
  name: string;
  order: number;
  pass_threshold: number;
  knowledge_points: LearningKnowledgePoint[];
}

export interface ProgressDetail {
  book_id: string;
  modules: LearningModule[];
  mastery_levels: Record<string, number>;
  current_module_id?: string;
  current_stage?: string;
  diagnostic?: unknown;
}

export async function fetchProgress(bookId: string): Promise<ProgressDetail> {
  const res = await apiFetch(apiUrl(`/api/v1/learning/progress/${bookId}`));
  if (!res.ok) throw new Error(`Failed to fetch progress: ${res.status}`);
  return res.json() as Promise<ProgressDetail>;
}

export async function initModules(bookId: string, modules: ModuleInit[]) {
  const res = await apiFetch(
    apiUrl(`/api/v1/learning/progress/${bookId}/init-modules`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ modules }),
    },
  );
  if (!res.ok) throw new Error(`Failed to init modules: ${res.status}`);
  return res.json();
}

// ── Mastery map (the dashboard view) ──────────────────────────────────────
// Mirrors deeptutor/learning/policy.py map_summary + next_objective.

export type ObjectiveStatus = "new" | "learning" | "mastered";

export interface MapKnowledgePoint {
  id: string;
  name: string;
  type: string;
  status: ObjectiveStatus;
  mastery: number;
}

export interface MapModule {
  id: string;
  name: string;
  order: number;
  mastered: number;
  total: number;
  knowledge_points: MapKnowledgePoint[];
}

export interface MasteryMap {
  /** What to call this path — see policy.path_display_name. */
  name: string;
  counts: { mastered: number; learning: number; new: number; total: number };
  due_reviews: number;
  complete: boolean;
  modules: MapModule[];
}

export interface NextStep {
  action: string;
  knowledge_point_id: string;
  knowledge_point_name: string;
  knowledge_point_type: string;
  status: string;
  gate: string;
  mastery: number;
  threshold: number;
  reason: string;
  /** The outstanding question's text, when `action` is `answer_pending`. */
  pending_prompt: string;
}

export interface MasteryMapResult {
  book_id: string;
  name: string;
  path_revision: number;
  next: NextStep;
  map: MasteryMap;
}

export async function fetchMasteryMap(
  pathId: string,
  init?: RequestInit,
): Promise<MasteryMapResult> {
  const res = await apiFetch(
    apiUrl(`/api/v1/learning/progress/${encodeURIComponent(pathId)}/map`),
    init,
  );
  if (!res.ok) throw new Error(`Failed to fetch mastery map: ${res.status}`);
  return res.json() as Promise<MasteryMapResult>;
}

/** Rename a path. An empty name restores the derived display name. */
export async function renameProgress(pathId: string, name: string) {
  const res = await apiFetch(
    apiUrl(`/api/v1/learning/progress/${encodeURIComponent(pathId)}`),
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    },
  );
  if (!res.ok) throw new Error(`Failed to rename path: ${res.status}`);
  return res.json() as Promise<{ status: string; name: string }>;
}

// ── Activity feed ─────────────────────────────────────────────────────────
// Mirrors deeptutor/learning/models.py MasteryEvent. Every committed change to
// a path emits one, numbered by the path's revision — which is what lets the
// dashboard follow along with a tutoring session running in another tab.

export interface MasteryEvent {
  id: number;
  revision: number;
  event_type: string;
  payload: Record<string, unknown>;
  session_id: string;
  turn_id: string;
  created_at: number;
}

export async function fetchProgressEvents(
  pathId: string,
  afterRevision = 0,
  init?: RequestInit,
): Promise<MasteryEvent[]> {
  const res = await apiFetch(
    apiUrl(
      `/api/v1/learning/progress/${encodeURIComponent(pathId)}/events?after_revision=${afterRevision}`,
    ),
    init,
  );
  if (!res.ok) throw new Error(`Failed to fetch path events: ${res.status}`);
  return (await res.json()).events as MasteryEvent[];
}

// ── One objective's evidence trail ────────────────────────────────────────
// Mirrors deeptutor/learning/policy.py objective_report.

export interface ObjectiveAttempt {
  question_id: string;
  prompt: string;
  answer: string;
  is_correct: boolean;
  error_type: string;
  at: number;
}

export interface ObjectiveReview {
  due_at: number | null;
  interval_index: number;
  consecutive_correct: number;
  consecutive_wrong: number;
}

export interface ObjectiveErrorRecord {
  id: string;
  error_type: string;
  status: string;
  self_attribution: string;
  retries: number;
  created_at: number;
}

export interface ObjectiveReport {
  id: string;
  name: string;
  type: string;
  module_name: string;
  status: ObjectiveStatus;
  gate: "quantitative" | "qualitative";
  mastered: boolean;
  mastery: number;
  threshold: number;
  attempts: ObjectiveAttempt[];
  correct_count: number;
  explanation: string;
  review: ObjectiveReview | null;
  errors: ObjectiveErrorRecord[];
}

export async function fetchObjectiveReport(
  pathId: string,
  objectiveId: string,
  init?: RequestInit,
): Promise<ObjectiveReport> {
  const res = await apiFetch(
    apiUrl(
      `/api/v1/learning/progress/${encodeURIComponent(pathId)}/objectives/${encodeURIComponent(objectiveId)}`,
    ),
    init,
  );
  if (!res.ok) throw new Error(`Failed to fetch objective: ${res.status}`);
  return (await res.json()).objective as ObjectiveReport;
}

export interface ProgressSummary {
  book_id: string;
  name: string;
  modules_count: number;
  kp_count: number;
  current_stage: string;
  avg_mastery_pct: number;
  updated_at: number;
}

export interface ProgressListResult {
  summaries: ProgressSummary[];
  errors: { book_id: string; error: string }[];
}

export async function fetchAllProgress(): Promise<ProgressListResult> {
  const res = await apiFetch(apiUrl("/api/v1/learning/progress"));
  if (!res.ok) throw new Error(`Failed to fetch all progress: ${res.status}`);
  return res.json();
}

export async function deleteProgress(bookId: string) {
  const res = await apiFetch(
    apiUrl(`/api/v1/learning/progress/${encodeURIComponent(bookId)}`),
    { method: "DELETE" },
  );
  if (!res.ok) throw new Error(`Failed to delete progress: ${res.status}`);
  return res.json();
}

export async function redoProgress(bookId: string) {
  const res = await apiFetch(
    apiUrl(`/api/v1/learning/progress/${encodeURIComponent(bookId)}/redo`),
    { method: "POST" },
  );
  if (!res.ok) throw new Error(`Failed to redo progress: ${res.status}`);
  return res.json();
}

/** Drop an outstanding question, keeping every mastery level already earned. */
export async function skipPendingQuestion(bookId: string) {
  const res = await apiFetch(
    apiUrl(
      `/api/v1/learning/progress/${encodeURIComponent(bookId)}/skip-question`,
    ),
    { method: "POST" },
  );
  if (!res.ok) throw new Error(`Failed to skip question: ${res.status}`);
  return res.json();
}

export async function importFromBook(
  bookId: string,
  chapters: { title: string; knowledge_points: string[] }[],
) {
  const res = await apiFetch(
    apiUrl(
      `/api/v1/learning/progress/${encodeURIComponent(bookId)}/import-from-book`,
    ),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chapters }),
    },
  );
  if (!res.ok) throw new Error(`Failed to import from book: ${res.status}`);
  return res.json();
}

export async function generateModulesFromNotebook(
  bookId: string,
  notebookId: string,
  records: { id: string; type: string; title: string; output: string }[],
): Promise<{ modules: ModuleInit[] }> {
  const res = await apiFetch(
    apiUrl(
      `/api/v1/learning/progress/${encodeURIComponent(bookId)}/generate-from-notebook`,
    ),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ notebook_id: notebookId, records }),
    },
  );
  if (!res.ok)
    throw new Error(`Failed to generate modules from notebook: ${res.status}`);
  return res.json();
}
