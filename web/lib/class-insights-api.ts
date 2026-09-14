import { apiFetch, apiUrl } from "@/lib/api";

/** One knowledge point below its mastery gate, per student. */
export interface WeakKnowledgePoint {
  kp_id: string;
  name: string;
  /** Display mastery 0..1 (0 for never-attempted quantitative KPs). */
  mastery: number;
}

/** Per-student row of the class insights overview. */
export interface ClassStudentInsight {
  username: string;
  kp_total: number;
  /** Average display mastery across all KPs, 0..100. */
  avg_mastery_pct: number;
  weak: WeakKnowledgePoint[];
  /** ISO timestamp of the student's latest progress update, or null. */
  last_active: string | null;
  /** Whitelist views mark rostered/linked students that have no data yet. */
  no_data?: boolean;
}

/** Response of GET /api/class-insights/overview. */
export interface ClassInsightsOverview {
  students: ClassStudentInsight[];
  generated_at: string;
  /** Present when the view is narrowed to one class roster. */
  class?: { id: string; name: string };
}

/** One class roster (K12 班级), owned by a teacher. */
export interface ClassRoster {
  id: string;
  name: string;
  teacher: string;
  students: string[];
  created_at: string;
}

/** Response of GET /api/class-insights/classes. */
export interface ClassRostersResponse {
  classes: ClassRoster[];
}

async function parseError(res: Response, fallback: string): Promise<never> {
  const data = await res.json().catch(() => ({}));
  throw new Error(
    typeof data.detail === "string" ? data.detail : `${fallback}: ${res.status}`,
  );
}

export async function fetchClassInsights(
  classId?: string,
): Promise<ClassInsightsOverview> {
  const qs = classId ? `?class_id=${encodeURIComponent(classId)}` : "";
  const res = await apiFetch(apiUrl(`/api/class-insights/overview${qs}`));
  if (!res.ok) return parseError(res, "Failed to fetch class insights");
  return res.json();
}

export async function fetchClassRosters(): Promise<ClassRostersResponse> {
  const res = await apiFetch(apiUrl("/api/class-insights/classes"));
  if (!res.ok) return parseError(res, "Failed to fetch class rosters");
  return res.json();
}

/** Parent (or admin) view: mastery of the linked children. */
export async function fetchMyChildren(): Promise<ClassInsightsOverview> {
  const res = await apiFetch(apiUrl("/api/class-insights/my-children"));
  if (!res.ok) return parseError(res, "Failed to fetch children insights");
  return res.json();
}
