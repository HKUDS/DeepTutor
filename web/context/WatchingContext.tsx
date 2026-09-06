"use client";

import { browserStorage } from "@/shared/storage";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
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

const LAST_MATERIAL_KEY = "dt:video-learning:last-material";
const LAST_URL_KEY = "dt:video-learning:last-url";

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

  const accept = useCallback((next: TimedMediaMaterial) => {
    setMaterial(next);
    setWatchingMaterial(next.material_id);
    setWatchingViewport(next.playback.start_seconds || 0);
    if (typeof window !== "undefined") {
      browserStorage.writeRaw("local", LAST_MATERIAL_KEY, next.material_id);
      browserStorage.writeRaw("local", LAST_URL_KEY, next.source.url);
    }
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!active || material) return;
    const materialId = browserStorage.readRaw("local", LAST_MATERIAL_KEY);
    if (!materialId) return;
    const sourceUrl = browserStorage.readRaw("local", LAST_URL_KEY) || "";
    setLastUrl(sourceUrl);
    setLoading(true);
    void getVideoMaterial(materialId)
      .then(accept)
      .catch((caught) => {
        setError(
          caught instanceof Error
            ? caught.message
            : t("The player provider is unavailable."),
        );
        browserStorage.removeRaw("local", LAST_MATERIAL_KEY);
      })
      .finally(() => setLoading(false));
  }, [accept, active, material, t]);

  const openUrl = useCallback(
    async (url: string, language = "", providerOverride?: VideoProvider) => {
      setLoading(true);
      setError(null);
      setLastUrl(url);
      try {
        accept(await resolveVideo(url, language, providerOverride));
      } catch (caught) {
        setError(
          caught instanceof Error
            ? caught.message
            : t("This video could not be opened."),
        );
        throw caught;
      } finally {
        setLoading(false);
      }
    },
    [accept, t],
  );

  const refresh = useCallback(async () => {
    if (!material) return;
    setLoading(true);
    setError(null);
    try {
      accept(await getVideoMaterial(material.material_id));
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : t("The player provider is unavailable."),
      );
    } finally {
      setLoading(false);
    }
  }, [accept, material, t]);

  const refreshTranscript = useCallback(async () => {
    if (!material) return;
    setLoading(true);
    setError(null);
    try {
      accept(await refreshInvidiousTranscript(material.material_id));
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : t("The player provider is unavailable."),
      );
    } finally {
      setLoading(false);
    }
  }, [accept, material, t]);

  const close = useCallback(() => {
    setMaterial(null);
    setWatchingMaterial(null);
    setError(null);
    if (typeof window !== "undefined") {
      browserStorage.removeRaw("local", LAST_MATERIAL_KEY);
      browserStorage.removeRaw("local", LAST_URL_KEY);
    }
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
