"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  Circle,
  CircleCheck,
  CircleDot,
  Loader2,
} from "lucide-react";

import {
  fetchObjectiveReport,
  type MasteryMap,
  type ObjectiveReport,
  type ObjectiveStatus,
} from "@/lib/learning-api";

import { ObjectiveDetail } from "./ObjectiveDetail";
import type { Translate } from "./format";

export const STATUS_META: Record<
  ObjectiveStatus,
  { cn: string; en: string; className: string }
> = {
  mastered: { cn: "已掌握", en: "Mastered", className: "text-green-500" },
  learning: { cn: "学习中", en: "Learning", className: "text-yellow-500" },
  new: {
    cn: "未开始",
    en: "Not started",
    className: "text-[var(--muted-foreground)]",
  },
};

/**
 * The module → objective map, with each objective openable.
 *
 * Rows stay as terse as before; the evidence behind one only loads when it is
 * opened, so a large path costs a single map request until the learner asks a
 * question of it. `revision` re-fetches whatever is open, which is how an
 * expanded objective keeps up with a live tutoring session.
 */
export function PathMap({
  pathId,
  map,
  revision,
  tr,
  zh,
}: {
  pathId: string;
  map: MasteryMap;
  revision: number;
  tr: Translate;
  zh: boolean;
}) {
  const [openId, setOpenId] = useState<string | null>(null);
  const [report, setReport] = useState<ObjectiveReport | null>(null);
  // Loading is derived rather than tracked: a report that does not match the
  // open objective is, by definition, still on its way.
  const loaded = openId !== null && report?.id === openId;

  useEffect(() => {
    if (!openId) return;
    const controller = new AbortController();
    fetchObjectiveReport(pathId, openId, { signal: controller.signal })
      .then(setReport)
      .catch(() => {
        if (!controller.signal.aborted) setReport(null);
      });
    return () => controller.abort();
  }, [pathId, openId, revision]);

  const toggle = useCallback((id: string) => {
    setOpenId((current) => (current === id ? null : id));
    setReport(null);
  }, []);

  return (
    <div className="space-y-4">
      {map.modules.map((module) => (
        <div key={module.id}>
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-medium text-[var(--foreground)]">
              {module.name}
            </h3>
            <span className="text-xs text-[var(--muted-foreground)]">
              {module.mastered}/{module.total}
            </span>
          </div>
          <div className="mt-1.5">
            {module.knowledge_points.map((kp) => {
              const open = openId === kp.id;
              return (
                <div key={kp.id}>
                  <button
                    onClick={() => toggle(kp.id)}
                    aria-expanded={open}
                    className="flex w-full items-center gap-2 rounded-md px-2 py-1 text-left text-sm hover:bg-[var(--accent)] cursor-pointer"
                  >
                    {open ? (
                      <ChevronDown className="h-3 w-3 shrink-0 text-[var(--muted-foreground)]" />
                    ) : (
                      <ChevronRight className="h-3 w-3 shrink-0 text-[var(--muted-foreground)]" />
                    )}
                    <StatusIcon status={kp.status} />
                    <span className="flex-1 truncate text-[var(--foreground)]">
                      {kp.name}
                    </span>
                    <span className="text-[10px] uppercase tracking-wide text-[var(--muted-foreground)]">
                      {kp.type}
                    </span>
                    <span
                      className={`text-xs ${STATUS_META[kp.status].className}`}
                    >
                      {zh
                        ? STATUS_META[kp.status].cn
                        : STATUS_META[kp.status].en}
                    </span>
                  </button>
                  {open &&
                    (loaded && report ? (
                      <ObjectiveDetail report={report} tr={tr} zh={zh} />
                    ) : (
                      <div className="ml-8 py-2 text-[var(--muted-foreground)]">
                        <Loader2 className="h-3 w-3 animate-spin" />
                      </div>
                    ))}
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

function StatusIcon({ status }: { status: ObjectiveStatus }) {
  const cls = `w-3 h-3 shrink-0 ${STATUS_META[status].className}`;
  if (status === "mastered") return <CircleCheck className={cls} />;
  if (status === "learning") return <CircleDot className={cls} />;
  return <Circle className={cls} />;
}
