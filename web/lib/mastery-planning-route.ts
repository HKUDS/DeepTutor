import type { LearningPlanState } from "./learning-api";

export interface LearningPlanRouteOptions {
  courseId?: string | null;
  regenerate?: boolean;
}

function courseQuery(courseId?: string | null): URLSearchParams {
  const query = new URLSearchParams();
  if (courseId?.trim()) query.set("course", courseId.trim());
  return query;
}

function routeWithQuery(route: string, query: URLSearchParams): string {
  const search = query.toString();
  return search ? `${route}?${search}` : route;
}

export function learningPlanDraftRoute(
  planId: string,
  options: LearningPlanRouteOptions = {},
): string {
  const query = courseQuery(options.courseId);
  if (options.regenerate) query.set("regenerate", "1");
  return routeWithQuery(`/mastery/planning/${encodeURIComponent(planId)}/draft`, query);
}

export function learningPlanRoute(
  planId: string,
  options: Pick<LearningPlanRouteOptions, "courseId"> = {},
): string {
  return routeWithQuery(`/mastery/planning/${encodeURIComponent(planId)}`, courseQuery(options.courseId));
}

export function learningPlanNewRoute(courseId?: string | null): string {
  return routeWithQuery("/mastery/new", courseQuery(courseId));
}

export function shouldGenerateLearningPlanDraft(
  state: LearningPlanState,
  regenerate = false,
): boolean {
  return regenerate || state !== "draft_ready";
}
