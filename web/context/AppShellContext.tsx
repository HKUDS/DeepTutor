"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { apiFetch, apiUrl } from "@/lib/api";
import {
  getStoredTheme,
  getSystemTheme,
  setTheme as applyThemePreference,
  subscribeToThemeChanges,
  type Theme,
} from "@/lib/theme";
import {
  ACTIVE_SESSION_EVENT,
  ACTIVE_SESSION_STORAGE_KEY,
  CODE_BLOCK_SHOW_LINE_NUMBERS_STORAGE_KEY,
  CODE_BLOCK_SETTINGS_EVENT,
  CODE_BLOCK_THEME_STORAGE_KEY,
  CODE_BLOCK_WRAP_LONG_LINES_STORAGE_KEY,
  DEFAULT_CODE_BLOCK_SHOW_LINE_NUMBERS,
  DEFAULT_CODE_BLOCK_THEME,
  DEFAULT_CODE_BLOCK_WRAP_LONG_LINES,
  LANGUAGE_EVENT,
  LANGUAGE_STORAGE_KEY,
  hasStoredLanguage,
  hasStoredResponseLanguage,
  SIDEBAR_COLLAPSED_EVENT,
  SIDEBAR_COLLAPSED_STORAGE_KEY,
  normalizeCodeBlockShowLineNumbers,
  normalizeCodeBlockTheme,
  normalizeCodeBlockWrapLongLines,
  normalizeLanguage,
  resolveResponseLanguage,
  readStoredActiveSessionId,
  readStoredCodeBlockShowLineNumbers,
  readStoredCodeBlockTheme,
  readStoredCodeBlockWrapLongLines,
  readStoredLanguage,
  writeStoredResponseLanguage,
  readStoredSidebarCollapsed,
  writeStoredActiveSessionId,
  writeStoredCodeBlockShowLineNumbers,
  writeStoredCodeBlockTheme,
  writeStoredCodeBlockWrapLongLines,
  writeStoredLanguage,
  writeStoredSidebarCollapsed,
  type AppLanguage,
} from "@/context/app-shell-storage";

interface AppShellContextValue {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  language: AppLanguage;
  languageReady: boolean;
  setLanguage: (language: AppLanguage) => void;
  activeSessionId: string | null;
  setActiveSessionId: (sessionId: string | null) => void;
  sidebarCollapsed: boolean;
  setSidebarCollapsed: (collapsed: boolean) => void;
  codeBlockTheme: string;
  setCodeBlockTheme: (theme: string) => void;
  codeBlockShowLineNumbers: boolean;
  setCodeBlockShowLineNumbers: (show: boolean) => void;
  codeBlockWrapLongLines: boolean;
  setCodeBlockWrapLongLines: (wrap: boolean) => void;
}

const AppShellContext = createContext<AppShellContextValue | null>(null);

export function AppShellProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(() => {
    return getStoredTheme() ?? getSystemTheme();
  });
  // Always start with "en" to match SSR; hydrate from localStorage after mount
  const [language, setLanguageState] = useState<AppLanguage>("en");
  const [languageReady, setLanguageReady] = useState(false);
  const [activeSessionId, setActiveSessionIdState] = useState<string | null>(
    () => readStoredActiveSessionId(),
  );
  // Always start expanded to match SSR; hydrate from localStorage after mount
  const [sidebarCollapsed, setSidebarCollapsedState] = useState<boolean>(false);
  // Code block settings - start with defaults, hydrate from localStorage after mount
  const [codeBlockTheme, setCodeBlockThemeState] = useState<string>(
    DEFAULT_CODE_BLOCK_THEME,
  );
  const [codeBlockShowLineNumbers, setCodeBlockShowLineNumbersState] =
    useState<boolean>(DEFAULT_CODE_BLOCK_SHOW_LINE_NUMBERS);
  const [codeBlockWrapLongLines, setCodeBlockWrapLongLinesState] =
    useState<boolean>(DEFAULT_CODE_BLOCK_WRAP_LONG_LINES);

  useEffect(() => {
    // Hydrate client-only preferences after SSR-safe first render.
    setSidebarCollapsedState(readStoredSidebarCollapsed());
    setCodeBlockThemeState(readStoredCodeBlockTheme());
    setCodeBlockShowLineNumbersState(readStoredCodeBlockShowLineNumbers());
    setCodeBlockWrapLongLinesState(readStoredCodeBlockWrapLongLines());
  }, []);

  useEffect(() => {
    // The saved languages live in the backend's ui settings, but only the
    // settings route ever read them, so every other page started in English
    // until the user changed it again in this browser. Adopt them once, and
    // only when this browser has made no choice of its own — a local selection
    // is the more specific signal and must win.
    //
    // One fetch carries both fields: the interface locale and the
    // reader-facing output language are stored together and are gated by the
    // same "has this browser chosen yet?" question, so splitting them into two
    // bootstraps would only give them a chance to disagree.
    const controller = new AbortController();
    let cancelled = false;
    let fallbackTimer: ReturnType<typeof setTimeout> | undefined;
    void (async () => {
      // Both keys are checked, not just the interface one. They were split
      // after the interface language shipped, so a browser from before the
      // split has `deeptutor-language` and no `deeptutor-response-language` —
      // and returning here on the first alone locked it out of ever adopting
      // the account's model output language.
      if (hasStoredLanguage() && hasStoredResponseLanguage()) {
        if (!cancelled) {
          setLanguageState(readStoredLanguage());
          setLanguageReady(true);
        }
        return;
      }
      fallbackTimer = setTimeout(() => {
        controller.abort();
        if (!cancelled) setLanguageReady(true);
      }, 1_500);
      try {
        const response = await apiFetch(apiUrl("/api/settings/ui"), {
          signal: controller.signal,
          skipAuthRedirect: true,
        });
        if (!response.ok) return;
        const payload = (await response.json()) as {
          language?: unknown;
          response_language?: unknown;
        };
        if (payload.language !== "zh" && payload.language !== "en") return;
        // Only what this browser is actually missing: a stored interface
        // language is this user's own choice and the server must not overwrite
        // it just because the response key was absent.
        const hadLanguage = hasStoredLanguage();
        if (!hadLanguage) writeStoredLanguage(payload.language);
        if (!hasStoredResponseLanguage()) {
          // A backend that predates the split sends no response_language;
          // resolveResponseLanguage inherits the interface locale, matching
          // what the server does for a legacy interface.json.
          writeStoredResponseLanguage(
            resolveResponseLanguage(
              typeof payload.response_language === "string"
                ? payload.response_language
                : null,
              payload.language,
            ),
          );
        }
        if (!cancelled && !hadLanguage) setLanguageState(payload.language);
      } catch {
        // Offline or unauthenticated: keep the local default.
      } finally {
        if (fallbackTimer) clearTimeout(fallbackTimer);
        if (!cancelled) setLanguageReady(true);
      }
    })();
    return () => {
      cancelled = true;
      if (fallbackTimer) clearTimeout(fallbackTimer);
      controller.abort();
    };
  }, []);

  useEffect(() => {
    return subscribeToThemeChanges((nextTheme) => {
      setThemeState(nextTheme);
    });
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;

    const onStorage = (event: StorageEvent) => {
      if (event.key === LANGUAGE_STORAGE_KEY) {
        setLanguageState(normalizeLanguage(event.newValue));
      }
      if (event.key === ACTIVE_SESSION_STORAGE_KEY) {
        setActiveSessionIdState(event.newValue);
      }
      if (event.key === SIDEBAR_COLLAPSED_STORAGE_KEY) {
        setSidebarCollapsedState(event.newValue === "1");
      }
      if (event.key === CODE_BLOCK_THEME_STORAGE_KEY) {
        setCodeBlockThemeState(normalizeCodeBlockTheme(event.newValue));
      }
      if (event.key === CODE_BLOCK_SHOW_LINE_NUMBERS_STORAGE_KEY) {
        setCodeBlockShowLineNumbersState(
          normalizeCodeBlockShowLineNumbers(event.newValue),
        );
      }
      if (event.key === CODE_BLOCK_WRAP_LONG_LINES_STORAGE_KEY) {
        setCodeBlockWrapLongLinesState(
          normalizeCodeBlockWrapLongLines(event.newValue),
        );
      }
    };

    const onLanguage = (event: Event) => {
      const detail = (event as CustomEvent<{ language?: AppLanguage }>).detail;
      setLanguageState(normalizeLanguage(detail?.language));
    };

    const onActiveSession = (event: Event) => {
      const detail = (event as CustomEvent<{ sessionId?: string | null }>)
        .detail;
      setActiveSessionIdState(detail?.sessionId ?? null);
    };

    const onSidebarCollapsed = (event: Event) => {
      const detail = (event as CustomEvent<{ collapsed?: boolean }>).detail;
      setSidebarCollapsedState(Boolean(detail?.collapsed));
    };

    const onCodeBlockSettings = (event: Event) => {
      const detail = (
        event as CustomEvent<{
          codeBlockTheme?: string;
          codeBlockShowLineNumbers?: boolean;
          codeBlockWrapLongLines?: boolean;
        }>
      ).detail;

      if (detail?.codeBlockTheme !== undefined) {
        setCodeBlockThemeState(normalizeCodeBlockTheme(detail.codeBlockTheme));
      }
      if (detail?.codeBlockShowLineNumbers !== undefined) {
        setCodeBlockShowLineNumbersState(
          Boolean(detail.codeBlockShowLineNumbers),
        );
      }
      if (detail?.codeBlockWrapLongLines !== undefined) {
        setCodeBlockWrapLongLinesState(Boolean(detail.codeBlockWrapLongLines));
      }
    };

    window.addEventListener("storage", onStorage);
    window.addEventListener(LANGUAGE_EVENT, onLanguage);
    window.addEventListener(ACTIVE_SESSION_EVENT, onActiveSession);
    window.addEventListener(SIDEBAR_COLLAPSED_EVENT, onSidebarCollapsed);
    window.addEventListener(CODE_BLOCK_SETTINGS_EVENT, onCodeBlockSettings);

    return () => {
      window.removeEventListener("storage", onStorage);
      window.removeEventListener(LANGUAGE_EVENT, onLanguage);
      window.removeEventListener(ACTIVE_SESSION_EVENT, onActiveSession);
      window.removeEventListener(SIDEBAR_COLLAPSED_EVENT, onSidebarCollapsed);
      window.removeEventListener(
        CODE_BLOCK_SETTINGS_EVENT,
        onCodeBlockSettings,
      );
    };
  }, []);

  const setTheme = useCallback((nextTheme: Theme) => {
    applyThemePreference(nextTheme);
    setThemeState(nextTheme);
  }, []);

  const setLanguage = useCallback((nextLanguage: AppLanguage) => {
    writeStoredLanguage(nextLanguage);
    setLanguageState(nextLanguage);
    setLanguageReady(true);
  }, []);

  const setActiveSessionId = useCallback((sessionId: string | null) => {
    writeStoredActiveSessionId(sessionId);
    setActiveSessionIdState(sessionId);
  }, []);

  const setSidebarCollapsed = useCallback((collapsed: boolean) => {
    writeStoredSidebarCollapsed(collapsed);
    setSidebarCollapsedState(collapsed);
  }, []);

  const setCodeBlockTheme = useCallback((nextTheme: string) => {
    const normalizedTheme = normalizeCodeBlockTheme(nextTheme);
    writeStoredCodeBlockTheme(normalizedTheme);
    setCodeBlockThemeState(normalizedTheme);
  }, []);

  const setCodeBlockShowLineNumbers = useCallback((show: boolean) => {
    writeStoredCodeBlockShowLineNumbers(show);
    setCodeBlockShowLineNumbersState(show);
  }, []);

  const setCodeBlockWrapLongLines = useCallback((wrap: boolean) => {
    writeStoredCodeBlockWrapLongLines(wrap);
    setCodeBlockWrapLongLinesState(wrap);
  }, []);

  const value = useMemo<AppShellContextValue>(
    () => ({
      theme,
      setTheme,
      language,
      languageReady,
      setLanguage,
      activeSessionId,
      setActiveSessionId,
      sidebarCollapsed,
      setSidebarCollapsed,
      codeBlockTheme,
      setCodeBlockTheme,
      codeBlockShowLineNumbers,
      setCodeBlockShowLineNumbers,
      codeBlockWrapLongLines,
      setCodeBlockWrapLongLines,
    }),
    [
      activeSessionId,
      codeBlockShowLineNumbers,
      codeBlockTheme,
      codeBlockWrapLongLines,
      language,
      languageReady,
      setActiveSessionId,
      setCodeBlockShowLineNumbers,
      setCodeBlockTheme,
      setCodeBlockWrapLongLines,
      setLanguage,
      setSidebarCollapsed,
      setTheme,
      sidebarCollapsed,
      theme,
    ],
  );

  return (
    <AppShellContext.Provider value={value}>
      {children}
    </AppShellContext.Provider>
  );
}

export function useAppShell() {
  const context = useContext(AppShellContext);
  if (!context) {
    throw new Error("useAppShell must be used inside AppShellProvider");
  }
  return context;
}
