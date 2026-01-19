"use client";

import React, {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  useRef,
  startTransition,
} from "react";
import { apiUrl } from "@/lib/api";
import { initializeTheme, setTheme, getStoredTheme } from "@/lib/theme";
import { UISettings, Theme, Language } from "@/types/common";

// Language storage key
const LANGUAGE_STORAGE_KEY = "deeptutor-language";

// Helper to get initial settings
function getInitialSettings(): UISettings {
  if (typeof window === "undefined") {
    return { theme: "light", language: "en" };
  }
  const initialTheme = initializeTheme();
  const storedLanguage =
    (localStorage.getItem(LANGUAGE_STORAGE_KEY) as Language) || "en";
  return { theme: initialTheme, language: storedLanguage };
}

// Context type
interface UISettingsContextType {
  uiSettings: UISettings;
  refreshSettings: () => Promise<void>;
  updateTheme: (theme: Theme) => Promise<void>;
  updateLanguage: (language: Language) => Promise<void>;
}

const UISettingsContext = createContext<UISettingsContextType | undefined>(
  undefined,
);

export function UISettingsProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [uiSettings, setUiSettings] = useState<UISettings>(getInitialSettings);
  const isInitializedRef = useRef(false);

  const refreshSettings = useCallback(async () => {
    // Try to load from backend API first, fallback to localStorage
    try {
      const res = await fetch(apiUrl("/api/v1/settings"));
      if (res.ok) {
        const data = await res.json();
        const serverTheme = data.ui?.theme || "light";
        const serverLanguage = data.ui?.language || "en";
        startTransition(() => {
          setUiSettings({
            theme: serverTheme,
            language: serverLanguage,
          });
        });
        setTheme(serverTheme);
        // Sync to localStorage as cache
        if (typeof window !== "undefined") {
          localStorage.setItem(LANGUAGE_STORAGE_KEY, serverLanguage);
        }
        return;
      }
    } catch (e) {
      console.warn(
        "Failed to load settings from server, using localStorage:",
        e,
      );
    }

    // Fallback to localStorage
    const storedTheme = getStoredTheme();
    const storedLanguage =
      typeof window !== "undefined"
        ? (localStorage.getItem(LANGUAGE_STORAGE_KEY) as Language) || "en"
        : "en";

    const themeToUse = storedTheme || "light";
    startTransition(() => {
      setUiSettings({
        theme: themeToUse,
        language: storedLanguage,
      });
    });
    setTheme(themeToUse);
  }, []);

  const updateTheme = useCallback(async (newTheme: Theme) => {
    // Update UI immediately
    setTheme(newTheme);
    setUiSettings((prev) => ({ ...prev, theme: newTheme }));

    // Persist to backend
    try {
      await fetch(apiUrl("/api/v1/settings/theme"), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ theme: newTheme }),
      });
    } catch (e) {
      console.warn("Failed to save theme to server:", e);
    }
  }, []);

  const updateLanguage = useCallback(async (newLanguage: Language) => {
    // Update UI immediately
    setUiSettings((prev) => ({ ...prev, language: newLanguage }));
    if (typeof window !== "undefined") {
      localStorage.setItem(LANGUAGE_STORAGE_KEY, newLanguage);
    }

    // Persist to backend
    try {
      await fetch(apiUrl("/api/v1/settings/language"), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ language: newLanguage }),
      });
    } catch (e) {
      console.warn("Failed to save language to server:", e);
    }
  }, []);

  useEffect(() => {
    // Async load settings from server on first render (which may override localStorage)
    if (!isInitializedRef.current) {
      isInitializedRef.current = true;
      refreshSettings();
    }
  }, [refreshSettings]);

  return (
    <UISettingsContext.Provider
      value={{
        uiSettings,
        refreshSettings,
        updateTheme,
        updateLanguage,
      }}
    >
      {children}
    </UISettingsContext.Provider>
  );
}

export const useUISettings = () => {
  const context = useContext(UISettingsContext);
  if (!context)
    throw new Error("useUISettings must be used within UISettingsProvider");
  return context;
};
