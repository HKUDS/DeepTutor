import { apiFetch, apiUrl } from "@/lib/api";

/**
 * The assignments contract (``/api/assignments``) — 教师作业布置 + 学生作答.
 *
 * Both sides spell the fields out: the teacher page renders exactly these and
 * the router returns exactly these. Items are server-side snapshots of the
 * KP question bank; the student-facing shapes never carry ``answer`` /
 * ``explanation`` (the router strips them before responding).
 */

/** One question as the student sees it — no answer, no explanation. */
export interface AssignmentItem {
  kp_id: string;
  q_idx: number;
  stem: string;
  /** "choice" renders option radios; "short" renders a fill-in input. */
  type: "choice" | "short";
  /** Empty for a short item. */
  options: string[];
}

export interface AssignmentSummary {
  assignment_id: string;
  class_id: string;
  title: string;
  created_at: string | null;
  due_at: string | null;
  item_count: number;
  submission_count: number;
}

/** Per-student, per-KP accuracy in the teacher's stats table. */
export interface StudentAssignmentStat {
  username: string;
  submitted: boolean;
  submitted_at: string | null;
  correct: number;
  total: number;
  per_kp: { kp_id: string; correct: number; total: number }[];
  /** Same accuracy broken out by question type (choice / short). */
  per_type: { type: "choice" | "short"; correct: number; total: number }[];
}

export interface TeacherAssignment extends AssignmentSummary {
  students: StudentAssignmentStat[];
}

export interface TeacherAssignmentsResponse {
  assignments: TeacherAssignment[];
}

export interface AssignSkipped {
  kp_id: string;
  reason: string;
}

export interface AssignResponse {
  assignment: AssignmentSummary;
  skipped: AssignSkipped[];
}

export interface SubmitResult {
  kp_id: string;
  q_idx: number;
  /** Correctness only — no answer text of any kind crosses the wire. */
  correct: boolean;
}

/**
 * Where the wrong answers went: ``linked`` counts error records written into
 * the student's own mastery store; ``skipped`` names why nothing was written
 * (e.g. the student has no LearningProgress for the book yet).
 */
export interface ErrorLinkReport {
  linked: number;
  skipped: string | null;
}

export interface StudentAssignment {
  assignment_id: string;
  class_id: string;
  title: string;
  created_at: string | null;
  due_at: string | null;
  status: "todo" | "done";
  items: AssignmentItem[];
  submitted_at?: string | null;
  results?: SubmitResult[];
}

export interface MyAssignmentsResponse {
  assignments: StudentAssignment[];
}

export interface SubmitResponse {
  assignment_id: string;
  correct_count: number;
  total: number;
  results: SubmitResult[];
  error_link: ErrorLinkReport;
}

/** One KP row of the teacher picker (with an optional question preview). */
export interface KpQuestionOption {
  kp_id: string;
  name: string;
  module: string;
  has_question: boolean;
  preview: { stem: string; type: "choice" | "short"; options: string[] } | null;
}

export interface KpQuestionsResponse {
  book_id: string;
  kps: KpQuestionOption[];
}

async function parseError(res: Response, fallback: string): Promise<never> {
  const data = await res.json().catch(() => ({}));
  throw new Error(
    typeof data.detail === "string" ? data.detail : `${fallback}: ${res.status}`,
  );
}

export async function fetchTeacherAssignments(
  classId?: string,
): Promise<TeacherAssignmentsResponse> {
  const qs = classId ? `?class_id=${encodeURIComponent(classId)}` : "";
  const res = await apiFetch(apiUrl(`/api/assignments${qs}`));
  if (!res.ok) return parseError(res, "Failed to fetch assignments");
  return res.json();
}

export async function createAssignment(body: {
  class_id: string;
  book_id: string;
  title: string;
  kp_ids: string[];
  due_at?: string;
}): Promise<AssignResponse> {
  const res = await apiFetch(apiUrl("/api/assignments"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) return parseError(res, "Failed to create assignment");
  return res.json();
}

export async function fetchKpQuestions(
  bookId: string,
): Promise<KpQuestionsResponse> {
  const res = await apiFetch(
    apiUrl(`/api/assignments/kps?book_id=${encodeURIComponent(bookId)}`),
  );
  if (!res.ok) return parseError(res, "Failed to fetch knowledge points");
  return res.json();
}

export async function fetchMyAssignments(): Promise<MyAssignmentsResponse> {
  const res = await apiFetch(apiUrl("/api/assignments/mine"));
  if (!res.ok) return parseError(res, "Failed to fetch assignments");
  return res.json();
}

export async function submitAssignment(
  assignmentId: string,
  answers: { kp_id: string; q_idx: number; answer: string }[],
): Promise<SubmitResponse> {
  const res = await apiFetch(
    apiUrl(`/api/assignments/${encodeURIComponent(assignmentId)}/submit`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answers }),
    },
  );
  if (!res.ok) return parseError(res, "Failed to submit assignment");
  return res.json();
}
