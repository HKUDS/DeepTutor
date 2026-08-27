import { apiFetch, apiUrl } from "@/lib/api";
import { invalidateClientCache, withClientCache } from "@/lib/client-cache";

export interface StudyCourse {
  id: string;
  name: string;
  description: string;
  color: string;
  created_at: number;
  updated_at: number;
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
  if (!response.ok) throw new Error(`Request failed: ${response.status}`);
  return response.json() as Promise<T>;
}

export async function listCourses(options?: {
  force?: boolean;
}): Promise<StudyCourse[]> {
  return withClientCache<StudyCourse[]>(
    "courses:list",
    async () => {
      const response = await apiFetch(apiUrl("/api/v1/courses"), {
        cache: "no-store",
      });
      return (
        (await expectJson<{ courses: StudyCourse[] }>(response)).courses ?? []
      );
    },
    { force: options?.force, ttlMs: 15_000 },
  );
}

export async function createCourse(input: {
  name: string;
  description?: string;
  color?: string;
}): Promise<StudyCourse> {
  const response = await apiFetch(apiUrl("/api/v1/courses"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  const course = (await expectJson<{ course: StudyCourse }>(response)).course;
  invalidateClientCache("courses:");
  return course;
}

export async function updateCourse(
  courseId: string,
  input: Partial<Pick<StudyCourse, "name" | "description" | "color">>,
): Promise<StudyCourse> {
  const response = await apiFetch(apiUrl(`/api/v1/courses/${courseId}`), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  const course = (await expectJson<{ course: StudyCourse }>(response)).course;
  invalidateClientCache("courses:");
  return course;
}

export async function deleteCourse(courseId: string): Promise<void> {
  const response = await apiFetch(apiUrl(`/api/v1/courses/${courseId}`), {
    method: "DELETE",
  });
  await expectJson<{ deleted: boolean }>(response);
  invalidateClientCache("courses:");
}
