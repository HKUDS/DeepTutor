"use client";

import { useEffect, type RefObject } from "react";

/** Scroll only the transcript rail, keeping its sticky search controls clear. */
export function useTranscriptFollow(
  panelRef: RefObject<HTMLDivElement | null>,
  cueStart: number | undefined,
  enabled: boolean,
) {
  useEffect(() => {
    const panel = panelRef.current;
    if (!panel || !enabled || cueStart === undefined) return;
    const content = panel.querySelector<HTMLElement>(".watching-transcript-list");
    const tools = panel.querySelector<HTMLElement>(".watching-transcript-tools");
    const workspace = panel.closest("[data-watching-workspace]");
    const captions = workspace?.querySelector<HTMLElement>(".watching-live-captions");
    const stage = workspace?.querySelector<HTMLElement>(".watching-video-stage");
    let frame = 0;
    const center = () => {
      const row = panel.querySelector<HTMLElement>(`[data-cue-start="${cueStart}"]`);
      if (!row || panel.clientHeight === 0) return;
      const bounds = panel.getBoundingClientRect();
      const rowBounds = row.getBoundingClientRect();
      const toolbarHeight = tools?.getBoundingClientRect().height ?? 0;
      const usableTop = bounds.top + panel.clientTop + toolbarHeight;
      const usableHeight = Math.max(0, panel.clientHeight - toolbarHeight);
      let centerY = usableTop + usableHeight / 2;
      const captionBounds = captions?.getBoundingClientRect();
      if (window.matchMedia("(min-width: 900px)").matches && captionBounds?.height) {
        // Align the two reading surfaces while reserving context above and below.
        centerY = Math.max(usableTop + usableHeight * .25, Math.min(
          usableTop + usableHeight * .75,
          captionBounds.top + captionBounds.height / 2,
        ));
      }
      const target = panel.scrollTop + rowBounds.top + rowBounds.height / 2 - centerY;
      const top = Math.max(0, Math.min(panel.scrollHeight - panel.clientHeight, target));
      if (Math.abs(top - panel.scrollTop) < 1) return;
      panel.scrollTo({
        top,
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth",
      });
    };
    const schedule = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(center);
    };
    schedule();
    const observer = new ResizeObserver(schedule);
    observer.observe(panel);
    if (tools) observer.observe(tools);
    if (content) observer.observe(content);
    if (captions) observer.observe(captions);
    if (stage) observer.observe(stage);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      // Stop an in-flight animation when the learner starts browsing manually.
      panel.scrollTo({ top: panel.scrollTop, behavior: "instant" });
    };
  }, [panelRef, cueStart, enabled]);
}
