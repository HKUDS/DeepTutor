"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { TranscriptCue } from "@/lib/video-learning-api";

/** Uses source timing only: untimed captions never invent word timestamps. */
export function WatchingCaptions({
  cues,
  time,
  onSeek,
}: {
  cues: TranscriptCue[];
  time: number;
  onSeek(time: number): void;
}) {
  const { t } = useTranslation();
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(500);
  useEffect(() => {
    if (!ref.current) return;
    const observer = new ResizeObserver(([entry]) =>
      setWidth(entry.contentRect.width),
    );
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);
  const index = cues.findLastIndex(cue => cue.start <= time && time < cue.end);
  const cue = cues[index];
  const rows = useMemo(() => {
    if (!cue) return [];
    const canvas = document.createElement("canvas");
    const context = canvas.getContext("2d");
    if (context) context.font = "18px sans-serif";
    const parts = cue.words?.length
      ? cue.words
      : [{ text: cue.text, start: cue.start, end: cue.end }];
    const result: { text: string; start: number; end: number }[][] = [[]];
    let used = 0;
    for (const part of parts) {
      for (const text of part.text
        .split(/(\s+|(?<=[\u3000-\u9fff]))/u)
        .filter(Boolean)) {
        const size = context?.measureText(text).width ?? text.length * 18;
        if (used + size > Math.max(100, width - 32) && result.at(-1)!.length) {
          result.push([]);
          used = 0;
        }
        result.at(-1)!.push({ ...part, text });
        used += size;
      }
    }
    return result;
  }, [cue, width]);
  let row = cue?.words?.length
    ? rows.findLastIndex(line => line.some(word => word.start <= time))
    : 0;
  row = Math.max(0, row);
  let visible = rows.slice(Math.max(0, row - 1), Math.max(2, row + 1));
  if (row === 0 && visible.length === 1 && index > 0) {
    const previous = cues[index - 1];
    if (
      cue &&
      previous.end >= cue.start - 1 &&
      previous.text !== cue.text &&
      !cue.text.startsWith(previous.text)
    ) {
      let context = previous.text;
      if (previous.end > cue.start) {
        for (let length = Math.min(context.length, cue.text.length); length > 0; length--) {
          if (context.endsWith(cue.text.slice(0, length)) && (length === cue.text.length || /\s/u.test(cue.text[length]))) {
            context = context.slice(0, -length).trimEnd(); break;
          }
        }
      }
      visible = [
        [{ text: context, start: previous.start, end: previous.end }],
        ...visible,
      ];
    }
  }
  return (
    <div
      ref={ref}
      className="watching-live-captions"
      aria-label={t("Learning captions")}
    >
      {!cue ? (
        <span className="text-sm opacity-60">
          {t("No caption at this position")}
        </span>
      ) : (
        visible.map((line, i) => (
          <div key={i} className="watching-caption-line">
            {line.map((word, j) => (
              <button
                key={j}
                type="button"
                onClick={() => onSeek(word.start)}
                className={
                  cue.words?.length && word.start <= time && time < word.end
                    ? "watching-word-active"
                    : ""
                }
              >
                {word.text}
              </button>
            ))}
          </div>
        ))
      )}
      <span className="sr-only">
        {t(cue?.words?.length ? "Word timing" : "Sentence timing")}
      </span>
    </div>
  );
}
