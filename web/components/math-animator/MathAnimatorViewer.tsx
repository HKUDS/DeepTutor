"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Code2, Expand, Image as ImageIcon, Timer, Video } from "lucide-react";
import { apiUrl } from "@/lib/api";
import type { MathAnimatorResult } from "@/lib/math-animator-types";

export default function MathAnimatorViewer({
  result,
}: {
  result: MathAnimatorResult;
}) {
  const [fullscreenUrl, setFullscreenUrl] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const images = useMemo(
    () => result.artifacts.filter((item) => item.type === "image"),
    [result.artifacts],
  );
  const videos = useMemo(
    () => result.artifacts.filter((item) => item.type === "video"),
    [result.artifacts],
  );
  const resolveAssetUrl = (url: string) => (url.startsWith("http://") || url.startsWith("https://") ? url : apiUrl(url));

  useEffect(() => {
    const el = rootRef.current;
    if (!el) return;

    const handler = (e: WheelEvent) => {
      if (Math.abs(e.deltaY) < 1) return;

      // Don't intercept if the event target is inside a scrollable child
      // (e.g. the code <pre> block) that can still scroll in this direction.
      let node = e.target as HTMLElement | null;
      while (node && node !== el) {
        if (node.scrollHeight > node.clientHeight + 2) {
          const style = window.getComputedStyle(node);
          if (style.overflowY === "auto" || style.overflowY === "scroll") {
            const atBottom = node.scrollTop + node.clientHeight >= node.scrollHeight - 2;
            const atTop = node.scrollTop <= 2;
            if ((e.deltaY > 0 && !atBottom) || (e.deltaY < 0 && !atTop)) {
              return;
            }
          }
        }
        node = node.parentElement;
      }

      let scrollRoot: HTMLElement | null =
        el.closest("[data-chat-scroll-root='true']") as HTMLElement | null;
      if (!scrollRoot) {
        let parent: HTMLElement | null = el.parentElement;
        while (parent) {
          const style = window.getComputedStyle(parent);
          if (
            (style.overflowY === "auto" || style.overflowY === "scroll") &&
            parent.scrollHeight > parent.clientHeight + 2
          ) {
            scrollRoot = parent;
            break;
          }
          parent = parent.parentElement;
        }
      }

      if (scrollRoot) {
        e.preventDefault();
        scrollRoot.scrollBy({ top: e.deltaY, behavior: "auto" });
      }
    };

    el.addEventListener("wheel", handler, { passive: false });
    return () => el.removeEventListener("wheel", handler);
  }, []);

  return (
    <div ref={rootRef} className="mb-3 space-y-3 rounded-2xl border border-[var(--border)] bg-[var(--card)]/70 p-3">
      {videos.length > 0 ? (
        <section className="space-y-2">
          <Header icon={Video} title="Video Output" />
          {videos.map((item) => (
            <div key={item.url}>
              <video
                controls
                playsInline
                preload="metadata"
                className="aspect-video w-full rounded-xl border border-[var(--border)] bg-black object-contain"
                src={resolveAssetUrl(item.url)}
              />
            </div>
          ))}
        </section>
      ) : null}

      {images.length > 0 ? (
        <section className="space-y-2">
          <Header icon={ImageIcon} title="Image Output" />
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {images.map((item) => (
              <button
                key={item.url}
                type="button"
                onClick={() => setFullscreenUrl(resolveAssetUrl(item.url))}
                className="group relative overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--background)]"
              >
                <img
                  src={resolveAssetUrl(item.url)}
                  alt={item.label || item.filename}
                  className="max-h-[280px] w-full object-contain"
                />
                <span className="absolute right-2 top-2 inline-flex items-center gap-1 rounded-md bg-black/55 px-2 py-1 text-[11px] text-white opacity-0 transition-opacity group-hover:opacity-100">
                  <Expand size={12} />
                  Fullscreen
                </span>
              </button>
            ))}
          </div>
        </section>
      ) : null}

      {result.code.content ? (
        <details className="overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--background)]">
          <summary className="flex cursor-pointer items-center gap-2 px-3 py-2 text-[12px] font-medium text-[var(--foreground)]">
            <Code2 size={14} />
            View Manim Code
          </summary>
          <pre className="max-h-[360px] overflow-auto border-t border-[var(--border)] px-3 py-3 font-mono text-[11px] leading-[1.6] text-[var(--foreground)]">
            {result.code.content}
          </pre>
        </details>
      ) : null}

      {result.render.visual_review && result.render.visual_review.passed === false ? (
        <div className="rounded-xl border border-amber-500/35 bg-amber-500/10 px-3 py-2.5 text-[12px] leading-[1.6] text-amber-900 dark:text-amber-200">
          <div className="font-medium">
            Visual review warning: {result.render.visual_review.summary || "The generated result still has presentation issues."}
          </div>
          {result.render.visual_review.issues && result.render.visual_review.issues.length > 0 ? (
            <div className="mt-1 opacity-90">
              {result.render.visual_review.issues.join(" ")}
            </div>
          ) : null}
        </div>
      ) : null}

      {(result.render.retry_attempts || Object.keys(result.timings).length > 0) ? (
        <div className="flex flex-wrap items-center gap-2 text-[11px] text-[var(--muted-foreground)]">
          {result.render.quality ? (
            <span className="rounded-full border border-[var(--border)] px-2 py-0.5">
              Quality: {result.render.quality}
            </span>
          ) : null}
          {typeof result.render.retry_attempts === "number" ? (
            <span className="rounded-full border border-[var(--border)] px-2 py-0.5">
              Retries: {result.render.retry_attempts}
            </span>
          ) : null}
          {Object.keys(result.timings).length > 0 ? (
            <span className="inline-flex items-center gap-1 rounded-full border border-[var(--border)] px-2 py-0.5">
              <Timer size={12} />
              {Object.entries(result.timings)
                .map(([key, value]) => `${key} ${value}s`)
                .join(" · ")}
            </span>
          ) : null}
        </div>
      ) : null}

      {fullscreenUrl ? (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/85 p-6"
          onClick={() => setFullscreenUrl(null)}
        >
          <img
            src={fullscreenUrl}
            alt="Fullscreen math animation output"
            className="max-h-full max-w-full object-contain"
          />
        </div>
      ) : null}
    </div>
  );
}

function Header({
  icon: Icon,
  title,
}: {
  icon: typeof Video;
  title: string;
}) {
  return (
    <div className="flex items-center gap-2 text-[12px] font-medium text-[var(--foreground)]">
      <Icon size={14} />
      <span>{title}</span>
    </div>
  );
}
