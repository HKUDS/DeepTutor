"use client";

import { ArrowDown, ArrowUp, Plus, Trash2, X } from "lucide-react";

import type { ModuleInit, TopicDraft } from "@/lib/learning-api";
import { useTranslation } from "react-i18next";

import type { Translate } from "./format";
import {
  moveRouteModule,
  moveRouteWaypoint,
  normalizeRouteModules,
  routeDraftIssues,
} from "./route-draft";

let fallbackSequence = 0;

function draftId(kind: "region" | "waypoint"): string {
  const random = globalThis.crypto?.randomUUID?.();
  return random
    ? `draft_${kind}_${random}`
    : `draft_${kind}_${Date.now()}_${fallbackSequence++}`;
}

/**
 * Regions an outline may hold when the server has not said otherwise.
 *
 * The server scales its own limit with the material selected (a fourteen-
 * document library earns fourteen regions), and this editor must not be the
 * thing that refuses to add the fourteenth.
 */
const DEFAULT_MODULE_LIMIT = 8;
const MAX_MODULE_LIMIT = 20;

export function RouteDraftEditor({
  draft,
  onChange,
  compact = false,
  showDescription = true,
  moduleLimit,
}: {
  draft: TopicDraft;
  onChange: (draft: TopicDraft) => void;
  compact?: boolean;
  showDescription?: boolean;
  /** From the draft the server generated; falls back to the classic cap. */
  moduleLimit?: number;
}) {
  const { t } = useTranslation();
  const issues = routeDraftIssues(draft);
  const cap = Math.min(
    MAX_MODULE_LIMIT,
    Math.max(DEFAULT_MODULE_LIMIT, moduleLimit || DEFAULT_MODULE_LIMIT),
  );
  const updateModule = (index: number, module: ModuleInit) => {
    const modules = [...draft.modules];
    modules[index] = module;
    onChange({ ...draft, modules: normalizeRouteModules(modules) });
  };
  const removeModule = (index: number) =>
    onChange({
      ...draft,
      modules: normalizeRouteModules(
        draft.modules.filter((_, moduleIndex) => moduleIndex !== index),
      ),
    });
  const addModule = () => {
    const index = draft.modules.length;
    const moduleId = draftId("region");
    onChange({
      ...draft,
      modules: normalizeRouteModules([
        ...draft.modules,
        {
          id: moduleId,
          name: t("New module {{n}}", { n: index + 1 }),
          order: index,
          knowledge_points: [
            {
              id: draftId("waypoint"),
              name: t("New knowledge point"),
              type: "concept",
              module_id: moduleId,
            },
          ],
        },
      ]),
    });
  };
  const moduleHasIssue = (moduleIndex: number, code: string) =>
    issues.some(
      (issue) =>
        "moduleIndex" in issue &&
        issue.moduleIndex === moduleIndex &&
        issue.code === code,
    );
  const waypointHasIssue = (moduleIndex: number, waypointIndex: number) =>
    issues.some(
      (issue) =>
        issue.code === "blank_waypoint" &&
        issue.moduleIndex === moduleIndex &&
        issue.waypointIndex === waypointIndex,
    );

  return (
    <div>
      {!compact && (
        <>
          <h3 className="text-lg font-semibold text-[var(--foreground)]">
            {t("Review and adjust the modules")}
          </h3>
          <p className="mt-1 text-sm leading-6 text-[var(--muted-foreground)]">
            {t(
              "Modules define learning phases and knowledge points define the abilities to master. Up/down controls make the order editable by keyboard as well as pointer.",
            )}
          </p>
        </>
      )}
      {showDescription && (
        <label
          className={`${compact ? "" : "mt-5"} block text-xs font-medium text-[var(--foreground)]`}
        >
          {t("Map description")}
          <textarea
            value={draft.description}
            onChange={(event) =>
              onChange({ ...draft, description: event.target.value })
            }
            maxLength={500}
            rows={compact ? 2 : 3}
            className="mt-2 w-full resize-none rounded-lg border border-[var(--input)] bg-[var(--background)] px-3 py-2.5 text-sm leading-5 outline-none focus:border-[var(--ring)] focus:ring-2 focus:ring-[var(--ring)]/15"
          />
        </label>
      )}
      {issues.some((issue) => issue.code === "no_regions") && (
        <p role="alert" className="mt-4 text-xs font-medium text-red-600">
          {t("Keep at least one module.")}
        </p>
      )}
      <div className="mt-5 space-y-3">
        {draft.modules.map((module, moduleIndex) => {
          const blankRegion = moduleHasIssue(moduleIndex, "blank_region");
          const emptyRegion = moduleHasIssue(moduleIndex, "no_waypoints");
          return (
            <div
              key={module.id}
              className={`rounded-lg border bg-[var(--background)] p-3.5 ${
                blankRegion || emptyRegion
                  ? "border-red-500/45"
                  : "border-[var(--border)]"
              }`}
            >
              <div className="flex items-center gap-2">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-[var(--primary)]/10 text-[11px] font-semibold text-[var(--primary)]">
                  {moduleIndex + 1}
                </span>
                <input
                  aria-label={t("Module {{n}} name", { n: moduleIndex + 1 })}
                  aria-invalid={blankRegion}
                  value={module.name}
                  onChange={(event) =>
                    updateModule(moduleIndex, {
                      ...module,
                      name: event.target.value,
                    })
                  }
                  maxLength={200}
                  className="h-9 min-w-0 flex-1 rounded-lg border border-transparent bg-transparent px-2 text-sm font-semibold outline-none hover:border-[var(--border)] focus:border-[var(--ring)] aria-[invalid=true]:border-red-500/50"
                />
                <OrderButtons
                  index={moduleIndex}
                  count={draft.modules.length}
                  upLabel={t("Move module “{{name}}” up", {
                    name: module.name || moduleIndex + 1,
                  })}
                  downLabel={t("Move module “{{name}}” down", {
                    name: module.name || moduleIndex + 1,
                  })}
                  onMove={(to) =>
                    onChange(moveRouteModule(draft, moduleIndex, to))
                  }
                />
                <button
                  type="button"
                  onClick={() => removeModule(moduleIndex)}
                  disabled={draft.modules.length === 1}
                  aria-label={t("Remove module “{{name}}”", {
                    name: module.name || moduleIndex + 1,
                  })}
                  className="rounded-lg p-2 text-[var(--muted-foreground)] hover:bg-red-500/10 hover:text-red-600 disabled:opacity-30"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
              {blankRegion && (
                <p className="ml-8 mt-1 text-[11px] text-red-600">
                  {t("Module name cannot be blank.")}
                </p>
              )}
              <div className="mt-2 space-y-1.5 sm:pl-8">
                {module.knowledge_points.map((point, pointIndex) => {
                  const blankWaypoint = waypointHasIssue(
                    moduleIndex,
                    pointIndex,
                  );
                  return (
                    <div
                      key={point.id}
                      className="flex flex-wrap items-center gap-1.5 sm:flex-nowrap sm:gap-2"
                    >
                      <span className="h-2 w-2 shrink-0 rounded-full border-2 border-[var(--primary)]/60" />
                      <input
                        aria-label={t(
                          "Knowledge point {{point}} name in module {{region}}",
                          {
                            point: pointIndex + 1,
                            region: moduleIndex + 1,
                          },
                        )}
                        aria-invalid={blankWaypoint}
                        value={point.name}
                        onChange={(event) => {
                          const knowledgePoints = [...module.knowledge_points];
                          knowledgePoints[pointIndex] = {
                            ...point,
                            name: event.target.value,
                          };
                          updateModule(moduleIndex, {
                            ...module,
                            knowledge_points: knowledgePoints,
                          });
                        }}
                        maxLength={200}
                        className="h-8 min-w-[12rem] flex-1 rounded-lg border border-transparent bg-transparent px-2 text-xs outline-none hover:border-[var(--border)] focus:border-[var(--ring)] aria-[invalid=true]:border-red-500/50"
                      />
                      <select
                        aria-label={t("Type for “{{name}}”", {
                          name: point.name || pointIndex + 1,
                        })}
                        value={point.type}
                        onChange={(event) => {
                          const knowledgePoints = [...module.knowledge_points];
                          knowledgePoints[pointIndex] = {
                            ...point,
                            type: event.target.value,
                          };
                          updateModule(moduleIndex, {
                            ...module,
                            knowledge_points: knowledgePoints,
                          });
                        }}
                        className="h-8 rounded-lg border border-[var(--border)] bg-[var(--card)] px-2 text-[11px] text-[var(--muted-foreground)] outline-none"
                      >
                        <option value="concept">{t("Concept")}</option>
                        <option value="memory">{t("Memory")}</option>
                        <option value="procedure">{t("Procedure")}</option>
                        <option value="design">{t("Design")}</option>
                      </select>
                      <OrderButtons
                        index={pointIndex}
                        count={module.knowledge_points.length}
                        upLabel={t("Move “{{name}}” up", {
                          name: point.name || pointIndex + 1,
                        })}
                        downLabel={t("Move “{{name}}” down", {
                          name: point.name || pointIndex + 1,
                        })}
                        onMove={(to) =>
                          onChange(
                            moveRouteWaypoint(
                              draft,
                              moduleIndex,
                              pointIndex,
                              to,
                            ),
                          )
                        }
                      />
                      <button
                        type="button"
                        onClick={() =>
                          updateModule(moduleIndex, {
                            ...module,
                            knowledge_points: module.knowledge_points.filter(
                              (_, index) => index !== pointIndex,
                            ),
                          })
                        }
                        disabled={module.knowledge_points.length === 1}
                        aria-label={t("Remove “{{name}}”", {
                          name: point.name || pointIndex + 1,
                        })}
                        className="rounded-md p-1.5 text-[var(--muted-foreground)] hover:text-red-600 disabled:opacity-25"
                      >
                        <X className="h-3 w-3" />
                      </button>
                      {blankWaypoint && (
                        <p className="w-full pl-4 text-[11px] text-red-600">
                          {t("Knowledge point name cannot be blank.")}
                        </p>
                      )}
                    </div>
                  );
                })}
                {emptyRegion && (
                  <p role="alert" className="text-[11px] text-red-600">
                    {t("Every module needs at least one knowledge point.")}
                  </p>
                )}
                <button
                  type="button"
                  onClick={() =>
                    updateModule(moduleIndex, {
                      ...module,
                      knowledge_points: [
                        ...module.knowledge_points,
                        {
                          id: draftId("waypoint"),
                          name: t("New knowledge point"),
                          type: "concept",
                          module_id: module.id,
                        },
                      ],
                    })
                  }
                  className="mt-1 inline-flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-xs text-[var(--primary)] hover:bg-[var(--primary)]/[0.06]"
                >
                  <Plus className="h-3 w-3" />
                  {t("Add knowledge point")}
                </button>
              </div>
            </div>
          );
        })}
      </div>
      {draft.modules.length < cap && (
        <button
          type="button"
          onClick={addModule}
          className="mt-3 inline-flex h-9 items-center gap-2 rounded-xl border border-dashed border-[var(--border)] px-3 text-xs text-[var(--muted-foreground)] hover:border-[var(--primary)]/50 hover:text-[var(--foreground)]"
        >
          <Plus className="h-3.5 w-3.5" />
          {t("Add module")}
        </button>
      )}
    </div>
  );
}

function OrderButtons({
  index,
  count,
  upLabel,
  downLabel,
  onMove,
}: {
  index: number;
  count: number;
  upLabel: string;
  downLabel: string;
  onMove: (index: number) => void;
}) {
  return (
    <span className="inline-flex shrink-0 rounded-lg border border-[var(--border)] bg-[var(--card)]">
      <button
        type="button"
        onClick={() => onMove(index - 1)}
        disabled={index === 0}
        aria-label={upLabel}
        className="p-1.5 text-[var(--muted-foreground)] hover:text-[var(--foreground)] disabled:opacity-25"
      >
        <ArrowUp className="h-3 w-3" />
      </button>
      <button
        type="button"
        onClick={() => onMove(index + 1)}
        disabled={index === count - 1}
        aria-label={downLabel}
        className="border-l border-[var(--border)] p-1.5 text-[var(--muted-foreground)] hover:text-[var(--foreground)] disabled:opacity-25"
      >
        <ArrowDown className="h-3 w-3" />
      </button>
    </span>
  );
}
