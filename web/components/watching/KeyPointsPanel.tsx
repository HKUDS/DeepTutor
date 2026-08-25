"use client";

import { useState } from "react";
import { Bookmark, HelpCircle, Play, RotateCcw, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  VIDEO_MARK_COLORS,
  filterMarks,
  formatMarkRange,
  markCoversTime,
} from "@/lib/video-learning-marks";
import type { VideoLearningMark, VideoMarkKind, VideoMarkSuggestion } from "@/lib/video-learning-api";

const FILTERS: Array<VideoMarkKind | "all"> = ["all", "key_point", "question", "review"];

export function KeyPointsPanel({
  marks,
  suggestions,
  currentTime,
  durationEndMark,
  error,
  onSeek,
  onDelete,
  onReviewed,
  onSaveSuggestion,
  onDismissEnd,
  onReplayEnd,
}: {
  marks: VideoLearningMark[];
  suggestions: VideoMarkSuggestion[];
  currentTime: number;
  durationEndMark: VideoLearningMark | null;
  error: string;
  onSeek: (seconds: number) => void;
  onDelete: (markId: string) => void;
  onReviewed: (mark: VideoLearningMark) => void;
  onSaveSuggestion: (suggestion: VideoMarkSuggestion) => void;
  onDismissEnd: () => void;
  onReplayEnd: (mark: VideoLearningMark) => void;
}) {
  const { t } = useTranslation();
  const [filter, setFilter] = useState<VideoMarkKind | "all">("all");
  const visible = filterMarks(marks, filter);

  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-3 text-sm">
      {durationEndMark && (
        <div className="mb-3 rounded border border-[var(--border)] bg-[var(--muted)] p-3">
          <p className="mb-2 text-xs text-[var(--muted-foreground)]">
            {t("Reached the end of this mark.")}
          </p>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="rounded border border-[var(--border)] px-2 py-1 text-xs hover:bg-[var(--background)]"
              onClick={onDismissEnd}
            >
              {t("Continue watching")}
            </button>
            <button
              type="button"
              className="inline-flex items-center gap-1 rounded border border-[var(--border)] px-2 py-1 text-xs hover:bg-[var(--background)]"
              onClick={() => onReplayEnd(durationEndMark)}
            >
              <RotateCcw size={12} />
              {t("Replay mark")}
            </button>
            {durationEndMark.kind === "review" && (
              <button
                type="button"
                className="rounded border border-[var(--border)] px-2 py-1 text-xs hover:bg-[var(--background)]"
                onClick={() => onReviewed(durationEndMark)}
              >
                {t("Mark as reviewed")}
              </button>
            )}
          </div>
        </div>
      )}

      {suggestions.length > 0 && (
        <div className="mb-4 space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
            {t("Suggested marks")}
          </p>
          {suggestions.map((suggestion, index) => (
            <div key={`${suggestion.kind}-${suggestion.start_seconds}-${index}`} className="rounded border border-dashed border-[var(--border)] p-2">
              <div className="mb-1 flex items-center justify-between gap-2">
                <span className="text-xs font-medium" style={{ color: VIDEO_MARK_COLORS[suggestion.kind] }}>
                  {labelForKind(suggestion.kind, t)}
                </span>
                <button
                  type="button"
                  className="rounded bg-[var(--foreground)] px-2 py-1 text-xs text-[var(--background)]"
                  onClick={() => onSaveSuggestion(suggestion)}
                >
                  {t("Save")}
                </button>
              </div>
              <button type="button" className="font-mono text-xs text-[var(--muted-foreground)]" onClick={() => onSeek(suggestion.start_seconds)}>
                {formatMarkRange(suggestion)}
              </button>
              {suggestion.quote && <p className="mt-1 text-[var(--foreground)]">{suggestion.quote}</p>}
            </div>
          ))}
        </div>
      )}

      <div className="mb-3 flex flex-wrap gap-1">
        {FILTERS.map((kind) => (
          <button
            key={kind}
            type="button"
            onClick={() => setFilter(kind)}
            className={`rounded px-2 py-1 text-xs ${filter === kind ? "bg-[var(--muted)] font-semibold" : "text-[var(--muted-foreground)]"}`}
          >
            {kind === "all" ? t("All") : labelForKind(kind, t)}
          </button>
        ))}
      </div>

      {error && <p className="mb-2 text-xs text-red-600">{error}</p>}

      {visible.length ? (
        <div className="space-y-2">
          {visible.map((mark) => {
            const active = markCoversTime(mark, currentTime);
            return (
              <article
                key={mark.mark_id}
                data-testid={`watching-mark-card-${mark.kind}`}
                className={`rounded border p-2 ${active ? "border-[var(--foreground)] bg-[var(--muted)]" : "border-[var(--border)]"}`}
              >
                <div className="mb-1 flex items-center gap-2">
                  {mark.kind === "question" ? <HelpCircle size={13} /> : <Bookmark size={13} />}
                  <span className="text-xs font-medium" style={{ color: VIDEO_MARK_COLORS[mark.kind] }}>
                    {labelForKind(mark.kind, t)}
                  </span>
                  <button
                    type="button"
                    className="ml-auto inline-flex items-center gap-1 font-mono text-xs text-[var(--muted-foreground)]"
                    onClick={() => onSeek(mark.start_seconds)}
                  >
                    <Play size={11} />
                    {formatMarkRange(mark)}
                  </button>
                  <button
                    type="button"
                    aria-label={t("Delete mark")}
                    className="rounded p-1 text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
                    onClick={() => onDelete(mark.mark_id)}
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
                {mark.quote && <p className="text-[var(--foreground)]">{mark.quote}</p>}
                {mark.note && <p className="mt-1 text-xs text-[var(--muted-foreground)]">{mark.note}</p>}
                {mark.reviewed_at && (
                  <p className="mt-1 text-xs text-[var(--muted-foreground)]">{t("Reviewed")}</p>
                )}
              </article>
            );
          })}
        </div>
      ) : (
        <p className="text-[var(--muted-foreground)]">{t("No key points yet.")}</p>
      )}
    </div>
  );
}

function labelForKind(kind: VideoMarkKind, t: (key: string) => string): string {
  if (kind === "question") return t("Question mark");
  if (kind === "review") return t("Review later");
  return t("Key point");
}
