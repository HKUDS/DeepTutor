"use client";

import { useState } from "react";
import { Bookmark, HelpCircle, Loader2, Play, RotateCcw, Trash2, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import type {
  VideoLearningMark,
  VideoMarkKind,
  VideoMarkSuggestion,
} from "@/lib/video-learning-api";
import {
  VIDEO_MARK_COLORS,
  filterMarks,
  formatMarkRange,
  markCoversTime,
} from "@/lib/video-learning-marks";

const FILTERS: Array<VideoMarkKind | "all"> = [
  "all",
  "key_point",
  "question",
  "review",
];

export function WatchingMarksPanel({
  marks,
  suggestions,
  currentTime = 0,
  error = null,
  busy = false,
  onSeek,
  onDelete,
  onReview,
  onSaveSuggestion,
  onDismissSuggestion,
}: {
  marks: VideoLearningMark[];
  suggestions: VideoMarkSuggestion[];
  currentTime?: number;
  error?: string | null;
  busy?: boolean;
  onSeek(seconds: number): void;
  onDelete(markId: string): void;
  onReview(mark: VideoLearningMark): void;
  onSaveSuggestion(suggestion: VideoMarkSuggestion): void;
  onDismissSuggestion?(suggestion: VideoMarkSuggestion): void;
}) {
  const { t } = useTranslation();
  const [filter, setFilter] = useState<VideoMarkKind | "all">("all");
  const visible = filterMarks(marks, filter);

  return (
    <div className="space-y-3">
      {error && (
        <p
          role="alert"
          className="rounded-lg border border-[var(--border)] bg-[var(--muted)] px-3 py-2 text-sm text-[var(--destructive)]"
        >
          {error}
        </p>
      )}

      {suggestions.length > 0 && (
        <section className="space-y-2 rounded-lg border border-dashed border-[var(--border)] p-3">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
            {t("Suggested marks")}
          </h4>
          {suggestions.map((suggestion, index) => (
            <article
              key={`${suggestion.kind}-${suggestion.start_seconds}-${index}`}
              className="rounded-md bg-[var(--muted)]/50 p-2"
            >
              <div className="flex items-center gap-2">
                <span
                  className="text-xs font-medium"
                  style={{ color: VIDEO_MARK_COLORS[suggestion.kind] }}
                >
                  {markLabel(suggestion.kind, t)}
                </span>
                <button
                  type="button"
                  onClick={() => onSeek(suggestion.start_seconds)}
                  className="ml-auto font-mono text-xs text-blue-600"
                >
                  {formatMarkRange(suggestion)}
                </button>
                <button
                  type="button"
                  onClick={() => onSaveSuggestion(suggestion)}
                  disabled={busy}
                  className="rounded-md bg-[var(--primary)] px-2 py-1 text-xs text-[var(--primary-foreground)] disabled:opacity-50"
                >
                  {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : t("Save")}
                </button>
                {onDismissSuggestion && (
                  <button
                    type="button"
                    onClick={() => onDismissSuggestion(suggestion)}
                    disabled={busy}
                    aria-label={t("Dismiss suggestion")}
                    className="rounded-md p-1 text-[var(--muted-foreground)] hover:bg-[var(--muted)] disabled:opacity-50"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>
              {suggestion.quote && (
                <p className="mt-1 text-sm">{suggestion.quote}</p>
              )}
            </article>
          ))}
        </section>
      )}

      <div
        className="flex flex-wrap gap-1"
        role="group"
        aria-label={t("Filter marks")}
      >
        {FILTERS.map((kind) => (
          <button
            key={kind}
            type="button"
            onClick={() => setFilter(kind)}
            aria-pressed={filter === kind}
            className={`rounded-full px-2.5 py-1 text-xs ${filter === kind ? "bg-[var(--muted)] font-semibold" : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]/60"}`}
          >
            {kind === "all" ? t("All") : markLabel(kind, t)}
          </button>
        ))}
      </div>

      {visible.length ? (
        <div className="space-y-2">
          {visible.map((mark) => {
            const active = markCoversTime(mark, currentTime);
            return (
              <article
                key={mark.mark_id}
                data-testid={`watching-mark-${mark.kind}`}
                className={`rounded-lg border p-3 ${active ? "border-blue-500/40 bg-blue-500/10" : "border-[var(--border)]"}`}
              >
                <div className="flex items-center gap-2">
                  {mark.kind === "question" ? (
                    <HelpCircle className="h-4 w-4" />
                  ) : (
                    <Bookmark className="h-4 w-4" />
                  )}
                  <span
                    className="text-xs font-medium"
                    style={{ color: VIDEO_MARK_COLORS[mark.kind] }}
                  >
                    {markLabel(mark.kind, t)}
                  </span>
                  <button
                    type="button"
                    onClick={() => onSeek(mark.start_seconds)}
                    className="ml-auto inline-flex items-center gap-1 font-mono text-xs text-blue-600"
                  >
                    <Play className="h-3 w-3" />
                    {formatMarkRange(mark)}
                  </button>
                  {!mark.reviewed_at && mark.kind === "review" && (
                    <button
                      type="button"
                      onClick={() => onReview(mark)}
                      disabled={busy}
                      aria-label={t("Mark as reviewed")}
                      className="rounded-md p-1.5 hover:bg-[var(--muted)] disabled:opacity-50"
                    >
                      <RotateCcw className="h-3.5 w-3.5" />
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => onDelete(mark.mark_id)}
                    disabled={busy}
                    aria-label={t("Delete mark")}
                    className="rounded-md p-1.5 text-[var(--destructive)] hover:bg-[var(--destructive)]/10 disabled:opacity-50"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
                {mark.quote && <p className="mt-2 text-sm">{mark.quote}</p>}
                {mark.note && (
                  <p className="mt-1 text-xs text-[var(--muted-foreground)]">
                    {mark.note}
                  </p>
                )}
                {mark.reviewed_at && (
                  <p className="mt-1 text-xs text-[var(--muted-foreground)]">
                    {t("Reviewed")}
                  </p>
                )}
              </article>
            );
          })}
        </div>
      ) : (
        <p className="text-sm text-[var(--muted-foreground)]">
          {t("No marks yet.")}
        </p>
      )}
    </div>
  );
}

function markLabel(
  kind: VideoMarkKind,
  t: (key: string) => string,
): string {
  if (kind === "question") return t("Question");
  if (kind === "review") return t("Review later");
  return t("Key point");
}
