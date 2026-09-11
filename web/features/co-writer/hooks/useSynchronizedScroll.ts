"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  loadSynchronizedScroll,
  saveSynchronizedScroll,
} from "../storage/drafts";

export type ScrollSyncSource = "editor" | "preview";

export function useSynchronizedScroll() {
  const [enabled, setEnabled] = useState(true);
  const sourceRef = useRef<ScrollSyncSource | null>(null);
  const resetTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const preferencesLoadedRef = useRef(false);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      setEnabled(loadSynchronizedScroll(window.localStorage));
      preferencesLoadedRef.current = true;
    });
    return () => window.cancelAnimationFrame(frame);
  }, []);
  useEffect(() => {
    if (!preferencesLoadedRef.current) return;
    saveSynchronizedScroll(window.localStorage, enabled);
  }, [enabled]);

  const releaseSource = useCallback(() => {
    if (resetTimerRef.current) clearTimeout(resetTimerRef.current);
    resetTimerRef.current = setTimeout(() => {
      sourceRef.current = null;
    }, 90);
  }, []);

  useEffect(
    () => () => {
      if (resetTimerRef.current) clearTimeout(resetTimerRef.current);
    },
    [],
  );

  return {
    scrollSyncEnabled: enabled,
    scrollSyncSourceRef: sourceRef,
    setSyncScrollEnabled: setEnabled,
    releaseScrollSyncSource: releaseSource,
  };
}
