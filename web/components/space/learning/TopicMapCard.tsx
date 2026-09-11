"use client";

import Link from "next/link";
import { useTranslation } from "react-i18next";
import { CircleCheck } from "lucide-react";

import type { MasteryTopic } from "@/lib/learning-api";

import { topicDisplayName, type Translate } from "./format";
import { ProgressRing } from "./ProgressRing";

export function TopicMapCard({ topic }: { topic: MasteryTopic }) {
  const { t } = useTranslation();
  const { map, metadata } = topic;
  const total = map.counts.total;
  const mastered = map.counts.mastered;
  const progress = total ? mastered / total : 0;
  const due = topic.reviews.filter((review) => review.due).length;
  const displayName = topicDisplayName(topic, t);

  return (
    <Link
      href={`/mastery/${encodeURIComponent(topic.path_id)}`}
      aria-label={t(
        "Open {{name}}, {{mastered}} of {{total}} knowledge points complete",
        {
          name: displayName,
          mastered,
          total,
        },
      )}
      className="mastery-map-card group block overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--card)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
    >
      <div className="flex items-start gap-3.5 p-4">
        <ProgressRing value={total ? mastered / total : 0} />
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-3">
            <h2 className="min-w-0 flex-1 truncate font-serif text-[15px] font-semibold tracking-[-0.01em] text-[var(--foreground)]">
              {displayName}
            </h2>
            {map.complete && (
              <CircleCheck className="mt-0.5 h-4 w-4 shrink-0 text-[var(--primary)]" />
            )}
          </div>
          <p className="mt-1 line-clamp-2 text-[12px] leading-5 text-[var(--muted-foreground)]">
            {metadata.description || metadata.goal}
          </p>
          <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px] tabular-nums text-[var(--muted-foreground)]">
            <span className="whitespace-nowrap">
              {t("{{count}} modules", { count: map.modules.length })}
            </span>
            <span className="whitespace-nowrap">
              {mastered}/{total} {t("knowledge points")}
            </span>
            <span className="whitespace-nowrap">
              {t("{{count}} sessions", { count: topic.session_count })}
            </span>
          </div>
        </div>
      </div>
    </Link>
  );
}
