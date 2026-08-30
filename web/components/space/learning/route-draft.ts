import type { ModuleInit, TopicDraft } from "@/lib/learning-api";

export type RouteDraftIssue =
  | { code: "no_regions" }
  | { code: "blank_region"; moduleIndex: number }
  | { code: "no_waypoints"; moduleIndex: number }
  | {
      code: "blank_waypoint";
      moduleIndex: number;
      waypointIndex: number;
    };

function move<T>(items: T[], from: number, to: number): T[] {
  if (
    from === to ||
    from < 0 ||
    to < 0 ||
    from >= items.length ||
    to >= items.length
  ) {
    return items;
  }
  const next = [...items];
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item);
  return next;
}

/** Keep positional fields coherent while stable entity ids travel with rows. */
export function normalizeRouteModules(modules: ModuleInit[]): ModuleInit[] {
  return modules.map((module, order) => ({
    ...module,
    order,
    knowledge_points: module.knowledge_points.map((point) => ({
      ...point,
      module_id: module.id,
    })),
  }));
}

export function moveRouteModule(
  draft: TopicDraft,
  from: number,
  to: number,
): TopicDraft {
  return {
    ...draft,
    modules: normalizeRouteModules(move(draft.modules, from, to)),
  };
}

export function moveRouteWaypoint(
  draft: TopicDraft,
  moduleIndex: number,
  from: number,
  to: number,
): TopicDraft {
  const currentModule = draft.modules[moduleIndex];
  if (!currentModule) return draft;
  const modules = [...draft.modules];
  modules[moduleIndex] = {
    ...currentModule,
    knowledge_points: move(currentModule.knowledge_points, from, to),
  };
  return { ...draft, modules: normalizeRouteModules(modules) };
}

export function routeDraftIssues(draft: TopicDraft): RouteDraftIssue[] {
  if (draft.modules.length === 0) return [{ code: "no_regions" }];
  const issues: RouteDraftIssue[] = [];
  draft.modules.forEach((module, moduleIndex) => {
    if (!module.name.trim()) issues.push({ code: "blank_region", moduleIndex });
    if (module.knowledge_points.length === 0) {
      issues.push({ code: "no_waypoints", moduleIndex });
    }
    module.knowledge_points.forEach((point, waypointIndex) => {
      if (!point.name.trim()) {
        issues.push({
          code: "blank_waypoint",
          moduleIndex,
          waypointIndex,
        });
      }
    });
  });
  return issues;
}

export function isRouteDraftValid(draft: TopicDraft): boolean {
  return routeDraftIssues(draft).length === 0;
}
