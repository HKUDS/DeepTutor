"use client";

/**
 * The study screen's outline rail.
 *
 * Same information as ``ModuleOutline`` on the topic page, at a tenth of the
 * weight: this one sits beside a conversation, so it has to read as
 * peripheral. It borrows that page's state language — fill → ring → outline,
 * never hue alone — and drops everything else: no card, no tinted number
 * chips, no dashed rules. What structure remains is one hairline rail per
 * module, which is enough to say "these belong together" without drawing a
 * second box inside a column that is already bounded.
 */

import { ChevronsLeft, ChevronsRight } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { MapKnowledgePoint, MasteryTopic } from "@/lib/learning-api";

/** 6px dot on the rail: filled = mastered, ring = current, hollow = ahead. */
function PointMark({
  point,
  current,
  justMastered,
}: {
  point: MapKnowledgePoint;
  current: boolean;
  /** Crossed into mastered moments ago — replay the transition. */
  justMastered: boolean;
}) {
  if (point.status === "mastered") {
    return (
      <span
        className={`h-[7px] w-[7px] rounded-full bg-[var(--primary)] ${
          justMastered ? "mastery-just-mastered-dot" : ""
        }`}
      />
    );
  }
  if (current) {
    return (
      <span className="h-[7px] w-[7px] rounded-full bg-[var(--background)] ring-2 ring-[var(--primary)]" />
    );
  }
  return (
    <span
      className={`h-[7px] w-[7px] rounded-full border ${
        point.status === "learning"
          ? "border-[var(--primary)]/60"
          : "border-[var(--muted-foreground)]/35"
      }`}
    />
  );
}

export function StudyOutline({
  topic,
  currentPointId,
  justMasteredId,
  collapsed,
  onToggleCollapsed,
}: {
  topic: MasteryTopic;
  /** The waypoint the tutor is on — highlighted, never a link. */
  currentPointId: string;
  /** Knowledge point that just cleared its gate, for the arrival animation. */
  justMasteredId?: string | null;
  collapsed: boolean;
  onToggleCollapsed: () => void;
}) {
  const { t } = useTranslation();
  const { mastered, total } = topic.map.counts;

  // Collapsed state keeps the toggle in the same real estate rather than
  // moving it up into the header, where a lone icon among several others
  // read as decoration, not a control — the outline's own edge is where a
  // learner already looks to bring it back.
  if (collapsed) {
    return (
      <button
        type="button"
        onClick={onToggleCollapsed}
        title={t("Show outline")}
        aria-label={t("Show outline")}
        className={`flex h-full w-full flex-col items-center gap-2.5 pt-4 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)]/50 hover:text-[var(--foreground)] ${
          justMasteredId ? "mastery-just-mastered-strip" : ""
        }`}
      >
        <ChevronsRight className="h-4 w-4" />
        <span
          className="text-[10px] font-medium uppercase tracking-[0.16em]"
          style={{ writingMode: "vertical-rl" }}
        >
          {t("Outline")}
        </span>
      </button>
    );
  }

  return (
    <nav aria-label={t("Outline")} className="pb-10">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[10px] font-medium uppercase tracking-[0.16em] text-[var(--muted-foreground)]/70">
          {t("Outline")}
        </span>
        <div className="flex items-center gap-2">
          <span className="text-[10.5px] tabular-nums text-[var(--muted-foreground)]/55">
            {mastered}/{total}
          </span>
          <button
            type="button"
            onClick={onToggleCollapsed}
            title={t("Hide outline")}
            aria-label={t("Hide outline")}
            className="flex h-5 w-5 items-center justify-center rounded text-[var(--muted-foreground)]/50 transition-colors hover:bg-[var(--muted)]/60 hover:text-[var(--foreground)]"
          >
            <ChevronsLeft className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      <div className="mt-5 space-y-6">
        {topic.map.modules.map((module, index) => (
          <section key={module.id}>
            <div className="flex items-baseline gap-2">
              <span className="w-[18px] shrink-0 text-[10.5px] font-medium tabular-nums text-[var(--muted-foreground)]/45">
                {String(index + 1).padStart(2, "0")}
              </span>
              <h2 className="min-w-0 text-[12.5px] font-semibold leading-5 text-[var(--foreground)]">
                {module.name}
              </h2>
            </div>

            {/* The rail is the module's spine — one continuous hairline
                behind the dots, rather than a border on every row. */}
            <ul className="relative mt-1.5 before:absolute before:bottom-[14px] before:left-[21px] before:top-[14px] before:w-px before:bg-[var(--border)]">
              {module.knowledge_points.map((point) => {
                const current = point.id === currentPointId;
                const justMastered = point.id === justMasteredId;
                return (
                  <li key={point.id} className="relative">
                    <div
                      className={`flex items-start gap-2 rounded-md py-[5px] pl-[18px] pr-2 ${
                        justMastered
                          ? "mastery-just-mastered-row"
                          : current
                            ? "bg-[color-mix(in_srgb,var(--primary)_7%,transparent)]"
                            : ""
                      }`}
                    >
                      <span
                        className={`relative z-[1] flex h-[18px] w-[7px] shrink-0 items-center justify-center ${
                          justMastered ? "mastery-just-mastered-halo" : ""
                        }`}
                      >
                        <PointMark
                          point={point}
                          current={current}
                          justMastered={justMastered}
                        />
                      </span>
                      <span
                        className={`min-w-0 text-[12px] leading-[18px] transition-colors duration-500 ${
                          justMastered
                            ? "font-medium text-[var(--foreground)]"
                            : current
                              ? "font-medium text-[var(--foreground)]"
                              : point.status === "mastered"
                                ? "text-[var(--muted-foreground)]/75"
                                : "text-[var(--muted-foreground)]"
                        }`}
                      >
                        {point.name}
                      </span>
                    </div>
                  </li>
                );
              })}
            </ul>
          </section>
        ))}
      </div>
    </nav>
  );
}
