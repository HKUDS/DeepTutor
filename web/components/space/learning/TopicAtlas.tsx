"use client";

import Link from "next/link";
import { useTranslation } from "react-i18next";
import {
  AlertCircle,
  ArrowRight,
  Compass,
  Plus,
  RefreshCw,
  Sparkles,
} from "lucide-react";

import type { MasteryTopic } from "@/lib/learning-api";
import {
  MASTERY_OPENING_SCOPE,
  masteryOpeningMessage,
  masterySessionRoute,
} from "@/lib/mastery-mode";
import { setPendingPrompt } from "@/lib/pending-prompt";

import { topicDisplayName, type Translate } from "./format";
import { TopicMapCard } from "./TopicMapCard";

export function TopicAtlas({
  topics,
  loading,
  error,
  onCreate,
  onRetry,
  scopeChip,
}: {
  topics: MasteryTopic[];
  loading: boolean;
  error: string | null;
  onCreate: (trigger: HTMLButtonElement) => void;
  onRetry: () => void;
  /** Rendered beside the eyebrow when this visit belongs to one course. */
  scopeChip?: React.ReactNode;
}) {
  const { t } = useTranslation();
  const activeTopics = topics.filter(
    (topic) => topic.metadata.status === "active",
  );
  const dueCount = activeTopics.reduce(
    (count, topic) =>
      count + topic.reviews.filter((review) => review.due).length,
    0,
  );
  const dueTopics = activeTopics.filter((topic) =>
    topic.reviews.some((review) => review.due),
  );
  const firstDueTopic = dueTopics[0];

  return (
    <main className="mastery-shell h-full overflow-y-auto [scrollbar-gutter:stable]">
      <div className="mx-auto max-w-7xl px-5 py-8 sm:px-8 lg:px-10 lg:py-10">
        <header className="flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <div className="mb-2 flex items-center gap-2 text-[11px] font-medium text-[var(--muted-foreground)]">
              <span className="inline-flex items-center gap-1.5">
                <Compass className="h-4 w-4" />
                {t("Mastery Path")}
              </span>
              {scopeChip}
            </div>
            <h1 className="font-serif text-[22px] font-semibold tracking-[-0.01em] text-[var(--foreground)]">
              {t("Your learning topics")}
            </h1>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-[var(--muted-foreground)]">
              {t(
                "Work through each topic's knowledge points, then pick up any session where you left off.",
              )}
            </p>
          </div>
          <button
            type="button"
            onClick={(event) => onCreate(event.currentTarget)}
            className="inline-flex h-9 shrink-0 items-center justify-center gap-2 rounded-xl bg-[var(--primary)] px-5 text-sm font-medium text-[var(--primary-foreground)]  transition hover:opacity-90 hover: focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2"
          >
            <Plus className="h-4 w-4" />
            {t("New topic")}
          </button>
        </header>

        {dueCount > 0 && (
          <section className="mt-8 flex flex-col gap-3 rounded-lg border border-[var(--border)] bg-[var(--muted-foreground)]/[0.07] px-4 py-3.5 text-sm text-[var(--foreground)] sm:flex-row sm:items-center">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[var(--muted-foreground)]/15 text-[var(--muted-foreground)]">
              <Sparkles className="h-4 w-4" />
            </span>
            <div className="min-w-0 flex-1">
              <div className="font-medium">
                {t("{{beacons}} reviews are due across {{count}} topics", {
                  beacons: dueCount,
                  count: dueTopics.length,
                })}
              </div>
              <div className="mt-0.5 text-xs text-[var(--muted-foreground)]">
                {t(
                  "Open their maps for a short review without losing your main route.",
                )}
              </div>
            </div>
            {firstDueTopic && (
              <Link
                // Straight into a review session: "start review" that lands on
                // a dashboard makes the learner find the door twice, and a
                // review sitting is a different kind of conversation from the
                // study one the dashboard's own button opens.
                onClick={() =>
                  setPendingPrompt(
                    masteryOpeningMessage("review", t, {
                      dueTitles: firstDueTopic.reviews
                        .filter((review) => review.due)
                        .slice(0, 5)
                        .map((review) => review.knowledge_point_name),
                    }),
                    MASTERY_OPENING_SCOPE,
                  )
                }
                href={masterySessionRoute(firstDueTopic.path_id, "review")}
                className="inline-flex h-9 shrink-0 items-center justify-center gap-1.5 rounded-xl bg-[var(--primary)] px-3.5 text-xs font-semibold text-white transition hover:opacity-90 focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)] focus-visible:ring-offset-2 "
              >
                {t("Start review")}: {topicDisplayName(firstDueTopic, t)}
                <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            )}
          </section>
        )}

        {error && (
          <div className="mt-8 flex items-center justify-between gap-4 rounded-lg border border-red-500/20 bg-red-500/[0.06] p-4 text-sm">
            <span className="flex items-center gap-2 text-red-700 dark:text-red-300">
              <AlertCircle className="h-4 w-4" /> {error}
            </span>
            <button
              type="button"
              onClick={onRetry}
              className="inline-flex items-center gap-1.5 font-medium text-[var(--foreground)] hover:underline"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              {t("Retry")}
            </button>
          </div>
        )}

        {loading ? (
          <div className="mt-9 grid gap-6 md:grid-cols-2 xl:grid-cols-3">
            {Array.from({ length: 6 }, (_, index) => (
              <div
                key={index}
                className="h-[360px] animate-pulse rounded-xl border border-[var(--border)] bg-[var(--muted)]/60"
              />
            ))}
          </div>
        ) : activeTopics.length > 0 ? (
          <section
            aria-label={t("Active learning topics")}
            className="mt-9 grid gap-6 md:grid-cols-2 xl:grid-cols-3"
          >
            {activeTopics.map((topic) => (
              <TopicMapCard key={topic.path_id} topic={topic} />
            ))}
          </section>
        ) : !error ? (
          <section className="mastery-map-paper relative mx-auto mt-12 max-w-3xl overflow-hidden rounded-xl border border-[var(--border)] px-6 py-16 text-center sm:px-12">
            <svg
              aria-hidden="true"
              viewBox="0 0 700 280"
              className="absolute inset-0 h-full w-full opacity-25"
            >
              <path
                d="M -40 210 C 90 40, 180 270, 320 115 S 550 240, 760 40"
                className="mastery-route-line"
              />
              <path
                d="M 50 40 C 150 -10, 210 90, 320 35 S 520 50, 650 10"
                fill="none"
                stroke="var(--mastery-moss)"
                strokeWidth="35"
                strokeOpacity=".2"
              />
            </svg>
            <div className="relative z-[1] mx-auto flex h-16 w-16 items-center justify-center rounded-xl border border-[var(--border)] bg-[var(--mastery-paper-raised)] ">
              <Compass className="h-7 w-7 text-[var(--mastery-route)]" />
            </div>
            <h2 className="relative z-[1] mt-6 font-serif text-[18px] font-semibold tracking-tight">
              {t("Your atlas is still uncharted")}
            </h2>
            <p className="relative z-[1] mx-auto mt-3 max-w-lg text-sm leading-6 opacity-70">
              {t(
                "Tell DeepTutor what you want to learn, mix in your books, notes, and knowledge bases, and it will draft the first outline.",
              )}
            </p>
            <button
              type="button"
              onClick={(event) => onCreate(event.currentTarget)}
              className="relative z-[1] mt-7 inline-flex h-9 items-center gap-2 rounded-xl bg-[var(--mastery-ink)] px-5 text-sm font-medium text-[var(--mastery-paper-raised)] transition hover:opacity-90"
            >
              <Plus className="h-4 w-4" />
              {t("Chart the first map")}
            </button>
          </section>
        ) : null}
      </div>
    </main>
  );
}
