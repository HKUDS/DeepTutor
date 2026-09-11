"use client";

import {
  createContext,
  useCallback,
  useContext,
  useRef,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";

import {
  getVideoMaterial,
  refreshInvidiousTranscript,
  resolveVideo,
  type TimedMediaMaterial,
  type VideoProvider,
} from "@/lib/video-learning-api";
import {
  setWatchingMaterial,
  setWatchingViewport,
} from "@/lib/watching-turn-state";

interface WatchingContextValue {
  material: TimedMediaMaterial | null;
  active: boolean;
  loading: boolean;
  error: string | null;
  lastUrl: string;
  openUrl(
    url: string,
    language?: string,
    providerOverride?: VideoProvider,
  ): Promise<void>;
  restore(materialId: string | null): Promise<void>;
  refresh(): Promise<void>;
  refreshTranscript(): Promise<void>;
  close(): void;
  reportTime(seconds: number): void;
  clearError(): void;
  setActive(active: boolean): void;
}

const WatchingContext = createContext<WatchingContextValue | null>(null);

export function WatchingProvider({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const [material, setMaterial] = useState<TimedMediaMaterial | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUrl, setLastUrl] = useState("");
  const [active, setActive] = useState(false);
  const generation = useRef(0);

  const accept = useCallback((next: TimedMediaMaterial) => {
    setMaterial(next);
    setWatchingMaterial(next.material_id);
    setWatchingViewport(next.playback.start_seconds || 0);
    setLastUrl(next.source.url);
  }, []);

  const restore = useCallback(
    async (materialId: string | null) => {
      const request = ++generation.current;
      setMaterial(null);
      setWatchingMaterial(null);
      setLastUrl("");
      setError(null);
      setLoading(Boolean(materialId));
      if (!materialId) return;
      try {
        const next = await getVideoMaterial(materialId);
        if (request === generation.current) accept(next);
      } catch (caught) {
        if (request === generation.current)
          setError(
            caught instanceof Error
              ? caught.message
              : t("The player provider is unavailable."),
          );
      } finally {
        if (request === generation.current) setLoading(false);
      }
    },
    [accept, t],
  );

  const openUrl = useCallback(
    async (url: string, language = "", providerOverride?: VideoProvider) => {
      const request = ++generation.current;
      setLoading(true);
      setError(null);
      setLastUrl(url);
      try {
        const next = await resolveVideo(url, language, providerOverride);
        if (request === generation.current) accept(next);
      } catch (caught) {
        if (request !== generation.current) return;
        setError(
          caught instanceof Error
            ? caught.message
            : t("This video could not be opened."),
        );
        throw caught;
      } finally {
        if (request === generation.current) setLoading(false);
      }
    },
    [accept, t],
  );

  const refresh = useCallback(async () => {
    if (!material) return;
    const request = ++generation.current;
    setLoading(true);
    setError(null);
    try {
      const next = await getVideoMaterial(material.material_id);
      if (request === generation.current) accept(next);
    } catch (caught) {
      if (request !== generation.current) return;
      setError(
        caught instanceof Error
          ? caught.message
          : t("The player provider is unavailable."),
      );
    } finally {
      if (request === generation.current) setLoading(false);
    }
  }, [accept, material, t]);

  const refreshTranscript = useCallback(async () => {
    if (!material) return;
    const request = ++generation.current;
    setLoading(true);
    setError(null);
    try {
      const next = await refreshInvidiousTranscript(material.material_id);
      if (request === generation.current) accept(next);
    } catch (caught) {
      if (request !== generation.current) return;
      setError(
        caught instanceof Error
          ? caught.message
          : t("The player provider is unavailable."),
      );
    } finally {
      if (request === generation.current) setLoading(false);
    }
  }, [accept, material, t]);

  const close = useCallback(() => {
    generation.current += 1;
    setMaterial(null);
    setWatchingMaterial(null);
    setLastUrl("");
    setLoading(false);
    setError(null);
  }, []);
  const reportTime = useCallback(
    (seconds: number) => setWatchingViewport(seconds),
    [],
  );
  const clearError = useCallback(() => setError(null), []);

  const value = useMemo(
    () => ({
      material,
      active,
      loading,
      error,
      lastUrl,
      openUrl,
      restore,
      refresh,
      refreshTranscript,
      close,
      reportTime,
      clearError,
      setActive,
    }),
    [
      material,
      active,
      loading,
      error,
      lastUrl,
      openUrl,
      restore,
      refresh,
      refreshTranscript,
      close,
      reportTime,
      clearError,
    ],
  );
  return (
    <WatchingContext.Provider value={value}>
      {children}
    </WatchingContext.Provider>
  );
}

export function useWatching(): WatchingContextValue {
  const context = useContext(WatchingContext);
  if (!context)
    throw new Error("useWatching must be used inside WatchingProvider");
  return context;
}
