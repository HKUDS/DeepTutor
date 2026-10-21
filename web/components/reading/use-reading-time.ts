"use client";

/**
 * Sends effective reading-time heartbeats while the Reader is genuinely used.
 *
 * The page must stay visible and focused, and the learner must have acted
 * (page turn, scroll, tap, selection, key) within the last 60 seconds — or
 * read-aloud / media playback must be running. About every 30 seconds the
 * accumulated seconds go to the server, which clamps the claim against wall
 * clock since the account's previous beat, so parallel tabs cannot double
 * count. A final `sendBeacon` beat leaves on `pagehide`.
 */

import { useEffect, useRef } from "react";
import {
  READING_TIME_BEAT_INTERVAL_MS,
  READING_TIME_TICK_MS,
  ReadingTimeAccumulator,
  type ReadingActivityState,
} from "@/lib/reading-time";
import { saveReadingTime, sendReadingTimeBeacon } from "@/lib/reading-api";

const INPUT_EVENTS = [
  "pointerdown",
  "keydown",
  "wheel",
  "touchstart",
  "scroll",
] as const;

function timezone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}

export function useReadingTimeHeartbeat(options: {
  materialId: string | null;
  /** Read-aloud or media playback keeps the clock running without input. */
  playing?: () => boolean;
}): void {
  const { materialId } = options;
  const playingRef = useRef(options.playing);
  useEffect(() => {
    playingRef.current = options.playing;
  }, [options.playing]);

  useEffect(() => {
    if (!materialId) return;
    const targetMaterialId = materialId;
    const signals = {
      visible: document.visibilityState === "visible",
      focused: document.hasFocus(),
      lastInputAt: null as number | null,
    };
    const state = (): ReadingActivityState => ({
      visible: signals.visible,
      focused: signals.focused,
      playing: Boolean(playingRef.current?.()),
      lastInputAt: signals.lastInputAt,
    });
    const accumulator = new ReadingTimeAccumulator(state);

    const markInput = () => {
      signals.lastInputAt = Date.now();
    };
    const onVisibility = () => {
      if (document.visibilityState === "hidden") flush("beacon");
      signals.visible = document.visibilityState === "visible";
    };
    const onFocus = () => {
      signals.focused = true;
    };
    const onBlur = () => {
      signals.focused = false;
    };
    const onPageHide = () => flush("beacon");

    function flush(how: "fetch" | "beacon") {
      const claimed = accumulator.takeBeat();
      if (claimed <= 0) return;
      const beat = { active_seconds: claimed, timezone: timezone() };
      if (how === "beacon") {
        sendReadingTimeBeacon(targetMaterialId, beat);
        return;
      }
      void saveReadingTime(targetMaterialId, beat).catch(() => {
        // A missed beat only loses its seconds; the server clamps the next
        // one against wall clock anyway, so never retry from here.
      });
    }

    for (const event of INPUT_EVENTS) {
      window.addEventListener(event, markInput, { capture: true, passive: true });
    }
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("focus", onFocus);
    window.addEventListener("blur", onBlur);
    window.addEventListener("pagehide", onPageHide);

    const tickTimer = window.setInterval(() => {
      accumulator.tick(Date.now());
    }, READING_TIME_TICK_MS);
    const beatTimer = window.setInterval(() => {
      flush("fetch");
    }, READING_TIME_BEAT_INTERVAL_MS);

    return () => {
      // Every timer and listener registered here is released on unmount.
      window.clearInterval(tickTimer);
      window.clearInterval(beatTimer);
      for (const event of INPUT_EVENTS) {
        window.removeEventListener(event, markInput, { capture: true });
      }
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("focus", onFocus);
      window.removeEventListener("blur", onBlur);
      window.removeEventListener("pagehide", onPageHide);
      flush("beacon");
    };
  }, [materialId]);
}
