import { apiFetch, apiUrl } from "@/lib/api";
import { invalidateClientCache, withClientCache } from "@/lib/client-cache";
import { ApiError } from "@/shared/api/errors";

/**
 * Kinds of resource a course may reference.
 *
 * A course stores a pointer, never the thing itself — one textbook can be the
 * reading for two courses, and one partner can assist all of them. Mirrors
 * `COURSE_RESOURCE_KINDS` in `deeptutor/services/courses.py`.
 */
export const COURSE_RESOURCE_KINDS = [
  "knowledge_base",
  "book",
  "notebook",
  "mastery_path",
  "reading_workspace",
  "partner",
  "partner_group",
] as const;

export type CourseResourceKind = (typeof COURSE_RESOURCE_KINDS)[number];

export interface CourseResource {
  id: string;
  kind: CourseResourceKind;
  ref_id: string;
  /** Snapshot taken at attach time, so the row survives the target being renamed. */
  label: string;
  position: number;
  added_at: number;
}

/**
 * One ordered unit of what a course is supposed to cover.
 *
 * The syllabus is what gives progress a denominator — "6 questions done" says
 * nothing without "out of twelve weeks". `covered` is the learner's own call:
 * inferring it from mastered knowledge points would be a guess rendered as a
 * progress bar, so the evidence sits next to the checkbox instead.
 */
export interface SyllabusUnit {
  id: string;
  position: number;
  title: string;
  topics: string[];
  covered: boolean;
}

export type CourseStatus = "active" | "archived";

export interface StudyCourse {
  id: string;
  name: string;
  description: string;
  color: string;
  created_at: number;
  updated_at: number;
  /** Learner-authored conventions for this subject. Reaches every turn. */
  instructions: string;
  /** The assistant's accumulating read on the learner. Never learner-edited. */
  agent_notes: string;
  default_capability: string;
  default_persona: string;
  resources: CourseResource[];
  syllabus: SyllabusUnit[];
  /** Archiving is reversible and never touches what the course references. */
  status: CourseStatus;
  archived_at: number;
}

/** One resource plus whether its target still resolves, and a per-kind summary. */
export interface CourseResourceState extends CourseResource {
  available: boolean;
  detail: Record<string, unknown>;
}

/**
 * The course's whole picture, from one endpoint.
 *
 * Deliberately the same payload the `course_study` tools read: a course page
 * and the assistant must never disagree about how far along the learner is,
 * and two independent aggregations would drift the moment either side changed.
 */
export interface CourseState {
  course: StudyCourse;
  resources: CourseResourceState[];
  sessions: {
    active: number;
    archived: number;
    recent: { session_id: string; title: string; updated_at: number }[];
  };
  mastery: {
    paths: {
      path_id: string;
      name: string;
      objectives_total: number;
      objectives_mastered: number;
      stage: string;
      weak_points: string[];
    }[];
  };
  question_bank: {
    total: number;
    wrong: number;
    weak_categories: { name: string; wrong: number }[];
  };
  reading: {
    workspaces: { workspace_id: string; title: string; materials: number }[];
  };
  syllabus: {
    total: number;
    covered: number;
    next: { id: string; title: string; position: number } | null;
    units: (SyllabusUnit & {
      /** Evidence, not a verdict: wrong questions matching this unit's topics. */
      wrong_questions: number;
    })[];
  };
}

export const DEFAULT_COURSE_COLORS = [
  "#C65D2E",
  "#3F6F8F",
  "#4F7655",
  "#8A6543",
  "#705B8E",
  "#A04F5F",
];

async function expectJson<T>(response: Response): Promise<T> {
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const detail =
      payload && typeof payload === "object"
        ? String((payload as { detail?: unknown }).detail ?? "").trim()
        : "";
    throw new ApiError({
      code: `http_${response.status}`,
      message: detail || `Request failed (${response.status})`,
      retryable:
        response.status === 408 ||
        response.status === 429 ||
        response.status >= 500,
      scope: "network",
      status: response.status,
    });
  }
  return payload as T;
}

/** Fill in fields absent from courses created before the container existed. */
function normalizeCourse(raw: Partial<StudyCourse>): StudyCourse {
  return {
    id: String(raw.id ?? ""),
    name: String(raw.name ?? ""),
    description: String(raw.description ?? ""),
    color: String(raw.color ?? DEFAULT_COURSE_COLORS[0]),
    created_at: Number(raw.created_at ?? 0),
    updated_at: Number(raw.updated_at ?? 0),
    instructions: String(raw.instructions ?? ""),
    agent_notes: String(raw.agent_notes ?? ""),
    default_capability: String(raw.default_capability ?? ""),
    default_persona: String(raw.default_persona ?? ""),
    resources: Array.isArray(raw.resources) ? raw.resources : [],
    syllabus: Array.isArray(raw.syllabus) ? raw.syllabus : [],
    status: raw.status === "archived" ? "archived" : "active",
    archived_at: Number(raw.archived_at ?? 0),
  };
}

export async function listCourses(options?: {
  force?: boolean;
}): Promise<StudyCourse[]> {
  return withClientCache<StudyCourse[]>(
    "courses:list",
    async () => {
      const response = await apiFetch(apiUrl("/api/courses"), {
        cache: "no-store",
      });
      const courses =
        (await expectJson<{ courses: Partial<StudyCourse>[] }>(response))
          .courses ?? [];
      return courses.map(normalizeCourse);
    },
    { force: options?.force, ttlMs: 15_000 },
  );
}

export async function createCourse(input: {
  name: string;
  description?: string;
  color?: string;
  instructions?: string;
  default_capability?: string;
  default_persona?: string;
}): Promise<StudyCourse> {
  const response = await apiFetch(apiUrl("/api/courses"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  const course = (await expectJson<{ course: Partial<StudyCourse> }>(response))
    .course;
  invalidateClientCache("courses:");
  return normalizeCourse(course);
}

export async function updateCourse(
  courseId: string,
  input: Partial<
    Pick<
      StudyCourse,
      | "name"
      | "description"
      | "color"
      | "instructions"
      | "default_capability"
      | "default_persona"
      | "status"
    >
  >,
): Promise<StudyCourse> {
  const response = await apiFetch(apiUrl(`/api/courses/${courseId}`), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  const course = (await expectJson<{ course: Partial<StudyCourse> }>(response))
    .course;
  invalidateClientCache("courses:");
  return normalizeCourse(course);
}

export async function deleteCourse(courseId: string): Promise<void> {
  const response = await apiFetch(apiUrl(`/api/courses/${courseId}`), {
    method: "DELETE",
  });
  await expectJson<{ deleted: boolean }>(response);
  invalidateClientCache("courses:");
}

export async function attachCourseResource(
  courseId: string,
  input: { kind: CourseResourceKind; ref_id: string; label?: string },
): Promise<CourseResource> {
  const response = await apiFetch(
    apiUrl(`/api/courses/${courseId}/resources`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    },
  );
  const resource = (await expectJson<{ resource: CourseResource }>(response))
    .resource;
  invalidateClientCache("courses:");
  return resource;
}

export async function detachCourseResource(
  courseId: string,
  resourceId: string,
): Promise<void> {
  const response = await apiFetch(
    apiUrl(`/api/courses/${courseId}/resources/${resourceId}`),
    { method: "DELETE" },
  );
  await expectJson<{ deleted: boolean }>(response);
  invalidateClientCache("courses:");
}

export async function getCourseState(
  courseId: string,
  options?: { force?: boolean },
): Promise<CourseState> {
  return withClientCache<CourseState>(
    `courses:state:${courseId}`,
    async () => {
      const response = await apiFetch(
        apiUrl(`/api/courses/${courseId}/state`),
        { cache: "no-store" },
      );
      const state = await expectJson<CourseState>(response);
      return { ...state, course: normalizeCourse(state.course ?? {}) };
    },
    { force: options?.force, ttlMs: 10_000 },
  );
}

export type CourseResourceCandidates = Partial<
  Record<CourseResourceKind, { ref_id: string; label: string }[]>
>;

export async function listCourseResourceCandidates(options?: {
  force?: boolean;
}): Promise<CourseResourceCandidates> {
  return withClientCache<CourseResourceCandidates>(
    "courses:candidates",
    async () => {
      const response = await apiFetch(
        apiUrl("/api/courses/resource-candidates"),
        { cache: "no-store" },
      );
      return (
        (await expectJson<{ candidates: CourseResourceCandidates }>(response))
          .candidates ?? {}
      );
    },
    { force: options?.force, ttlMs: 30_000 },
  );
}

export async function setCourseSyllabus(
  courseId: string,
  units: { id?: string; title: string; topics?: string[]; covered?: boolean }[],
): Promise<StudyCourse> {
  const response = await apiFetch(apiUrl(`/api/courses/${courseId}/syllabus`), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ units }),
  });
  const course = (await expectJson<{ course: Partial<StudyCourse> }>(response))
    .course;
  invalidateClientCache("courses:");
  return normalizeCourse(course);
}

export async function setSyllabusUnitCovered(
  courseId: string,
  unitId: string,
  covered: boolean,
): Promise<SyllabusUnit> {
  const response = await apiFetch(
    apiUrl(`/api/courses/${courseId}/syllabus/${unitId}`),
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ covered }),
    },
  );
  const unit = (await expectJson<{ unit: SyllabusUnit }>(response)).unit;
  invalidateClientCache("courses:");
  return unit;
}
