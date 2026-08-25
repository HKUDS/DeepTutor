"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { getVideoLearningMaterial, resolveVideoLearning, saveVideoPosition, type TimedMediaMaterial } from "@/lib/video-learning-api";
import { getWatchingModeActive, setWatchingMaterial, setWatchingViewport, subscribeWatchingMode } from "@/lib/watching-turn-state";

interface WatchingContextValue {
  material: TimedMediaMaterial | null;
  active: boolean;
  loading: boolean;
  error: string | null;
  currentTime: number;
  pendingSeek: number | null;
  openUrl: (url: string) => Promise<void>;
  openMaterial: (materialId: string, options?: { seekSeconds?: number }) => Promise<void>;
  replaceMaterial: (next: TimedMediaMaterial) => void;
  close: () => void;
  setCurrentTime: (seconds: number, locator?: number) => void;
  seek: (seconds: number) => void;
  clearSeek: () => void;
}

const WatchingContext = createContext<WatchingContextValue>({ material: null, active: false, loading: false, error: null, currentTime: 0, pendingSeek: null, openUrl: async () => {}, openMaterial: async () => {}, replaceMaterial: () => {}, close: () => {}, setCurrentTime: () => {}, seek: () => {}, clearSeek: () => {} });

export function WatchingProvider({ children }: { children: ReactNode }) {
  const [material, setMaterial] = useState<TimedMediaMaterial | null>(null);
  const active = useSyncExternalStore(subscribeWatchingMode, getWatchingModeActive, () => false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [currentTime, setCurrentTimeState] = useState(0);
  const [pendingSeek, setPendingSeek] = useState<number | null>(null);
  const tokenRef = useRef(0);
  const lastSavedRef = useRef(0);

  useEffect(() => { setWatchingMaterial(material?.material_id ?? null); }, [material]);
  const accept = useCallback((next: TimedMediaMaterial, seekSeconds?: number) => {
    const fallback = Number(next.source.entry_time_seconds || next.learning.last_position || 0);
    const start = Number.isFinite(seekSeconds) ? Math.max(0, Number(seekSeconds)) : fallback;
    setMaterial(next);
    setCurrentTimeState(start);
    setPendingSeek(start);
    setWatchingViewport({ timeSeconds: start });
    lastSavedRef.current = start;
  }, []);
  const openUrl = useCallback(async (url: string) => {
    const token = ++tokenRef.current; setLoading(true); setError(null);
    try { const next = await resolveVideoLearning(url); if (token === tokenRef.current) accept(next); }
    catch (caught) { if (token === tokenRef.current) setError(caught instanceof Error ? caught.message : "This YouTube video could not be opened."); }
    finally { if (token === tokenRef.current) setLoading(false); }
  }, [accept]);
  const openMaterial = useCallback(async (materialId: string, options?: { seekSeconds?: number }) => {
    const token = ++tokenRef.current; setLoading(true); setError(null);
    try {
      const next = await getVideoLearningMaterial(materialId);
      if (token === tokenRef.current) accept(next, options?.seekSeconds);
    }
    catch (caught) { if (token === tokenRef.current) setError(caught instanceof Error ? caught.message : "This video learning material could not be opened."); }
    finally { if (token === tokenRef.current) setLoading(false); }
  }, [accept]);
  const setCurrentTime = useCallback((seconds: number, locator?: number) => {
    const safe = Math.max(0, Number.isFinite(seconds) ? seconds : 0); setCurrentTimeState(safe); setWatchingViewport({ timeSeconds: safe, locator });
    if (material && Math.abs(safe - lastSavedRef.current) >= 10) { lastSavedRef.current = safe; void saveVideoPosition(material.material_id, safe).catch(() => {}); }
  }, [material]);
  const replaceMaterial = useCallback((next: TimedMediaMaterial) => { setMaterial(next); }, []);
  const close = useCallback(() => { tokenRef.current += 1; setMaterial(null); setError(null); setCurrentTimeState(0); setPendingSeek(null); setWatchingViewport({ timeSeconds: 0, locator: 0 }); }, []);
  const seek = useCallback((seconds: number) => { const safe = Math.max(0, seconds); setPendingSeek(safe); setCurrentTimeState(safe); setWatchingViewport({ timeSeconds: safe }); }, []);
  const clearSeek = useCallback(() => setPendingSeek(null), []);
  useEffect(() => {
    const onClick = (event: MouseEvent) => { const target = event.target instanceof Element ? event.target.closest("a[href^=\"#dt-time-\"]") : null; if (!target) return; const value = Number((target as HTMLAnchorElement).hash.slice(9)); if (!Number.isFinite(value)) return; event.preventDefault(); seek(value); };
    window.addEventListener("click", onClick); return () => window.removeEventListener("click", onClick);
  }, [seek]);
  const value = useMemo(() => ({ material, active, loading, error, currentTime, pendingSeek, openUrl, openMaterial, replaceMaterial, close, setCurrentTime, seek, clearSeek }), [material, active, loading, error, currentTime, pendingSeek, openUrl, openMaterial, replaceMaterial, close, setCurrentTime, seek, clearSeek]);
  return <WatchingContext.Provider value={value}>{children}</WatchingContext.Provider>;
}

export function useWatching(): WatchingContextValue { return useContext(WatchingContext); }
