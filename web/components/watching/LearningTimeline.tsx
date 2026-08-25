"use client";

import { VIDEO_MARK_COLORS, markCoversTime, timelineStyle } from "@/lib/video-learning-marks";
import type { VideoLearningMark } from "@/lib/video-learning-api";

export function LearningTimeline({
  marks,
  duration,
  currentTime,
  onSeek,
}: {
  marks: VideoLearningMark[];
  duration: number;
  currentTime: number;
  onSeek: (seconds: number) => void;
}) {
  const total = Math.max(duration, 1);
  const playhead = Math.min(100, Math.max(0, (currentTime / total) * 100));

  return (
    <div className="border-b border-[var(--border)] px-3 py-2">
      <div
        className="relative h-7 cursor-pointer"
        onClick={(event) => {
          const rect = event.currentTarget.getBoundingClientRect();
          const ratio = rect.width > 0 ? (event.clientX - rect.left) / rect.width : 0;
          onSeek(Math.max(0, ratio * total));
        }}
      >
        <div className="absolute inset-x-0 top-1/2 h-1.5 -translate-y-1/2 rounded bg-[var(--border)]" />
        {marks.map((mark) => {
          const style = timelineStyle(mark, total);
          const active = markCoversTime(mark, currentTime);
          return (
            <button
              key={mark.mark_id}
              type="button"
              title={mark.quote || mark.kind}
              aria-label={mark.kind}
              className="absolute top-1/2 h-3 -translate-y-1/2 rounded-sm"
              style={{
                left: style.left,
                width: style.width,
                backgroundColor: VIDEO_MARK_COLORS[mark.kind],
                opacity: active ? 1 : 0.72,
                boxShadow: active ? `0 0 0 2px ${VIDEO_MARK_COLORS[mark.kind]}55` : undefined,
              }}
              onClick={(event) => {
                event.stopPropagation();
                onSeek(mark.start_seconds);
              }}
            />
          );
        })}
        <div
          className="pointer-events-none absolute top-0 h-full w-0.5 bg-[var(--foreground)]"
          style={{ left: `${playhead}%` }}
        />
      </div>
    </div>
  );
}
