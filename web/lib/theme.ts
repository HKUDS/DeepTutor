/**
 * Theme persistence utilities.
 * An explicit palette is stored as itself. "system", and a missing value,
 * follow the OS and must not freeze the first detected palette into storage.
 */

import { browserStorage } from "@/shared/storage";

export type Theme = "light" | "dark" | "glass" | "snow";

/** Explicit palette, or "system" to follow prefers-color-scheme. */
export type ThemePreference = Theme | "system";

export const THEME_STORAGE_KEY = "deeptutor-theme";

const EXPLICIT_THEMES = new Set<string>(["light", "dark", "glass", "snow"]);

type ThemeChangeListener = (theme: Theme) => void;
const themeListeners = new Set<ThemeChangeListener>();

let systemMedia: MediaQueryList | null = null;
let systemMediaHandler: ((event: MediaQueryListEvent) => void) | null = null;

function isExplicitTheme(value: string | null): value is Theme {
  return value !== null && EXPLICIT_THEMES.has(value);
}

function followsSystem(preference: ThemePreference | null): boolean {
  return preference === null || preference === "system";
}

/**
 * Subscribe to resolved theme changes (explicit choices and live OS updates).
 */
export function subscribeToThemeChanges(listener: ThemeChangeListener): () => void {
  themeListeners.add(listener);
  return () => themeListeners.delete(listener);
}

/**
 * Notify all listeners of a resolved theme change.
 */
function notifyThemeChange(theme: Theme): void {
  themeListeners.forEach((listener) => listener(theme));
}

function readStoredPreferenceRaw(): string | null {
  if (typeof window === "undefined") return null;

  try {
    return browserStorage.readRaw("local", THEME_STORAGE_KEY);
  } catch (e) {
    // Silently fail - localStorage may be disabled
    return null;
  }
}

/**
 * Stored choice, including "system". Missing or unrecognized values are null,
 * which means "follow the OS" without writing anything.
 */
export function getStoredThemePreference(): ThemePreference | null {
  const stored = readStoredPreferenceRaw();
  if (stored === "system" || isExplicitTheme(stored)) return stored;
  return null;
}

/**
 * Explicit stored palette. "system" and a missing value return null so callers
 * can fall through to the live OS palette without treating it as a choice.
 */
export function getStoredTheme(): Theme | null {
  const preference = getStoredThemePreference();
  if (!preference || preference === "system") return null;
  return preference;
}

/**
 * Save a theme preference to localStorage.
 * Pass "system" to remember that the OS should keep winning.
 */
export function saveThemeToStorage(theme: ThemePreference): boolean {
  if (typeof window === "undefined") return false;

  try {
    return browserStorage.writeRaw("local", THEME_STORAGE_KEY, theme);
  } catch (e) {
    // Silently fail - localStorage may be disabled or full
    return false;
  }
}

/**
 * Get system preference for theme.
 * Light systems get "snow" (the pure-white Default theme); dark systems
 * get "dark". Must stay in sync with the inline ThemeScript fallback.
 */
export function getSystemTheme(): Theme {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return "snow";
  }

  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "snow";
}

/** Resolve a preference to the palette that should be on the document. */
export function resolveTheme(preference: ThemePreference | null): Theme {
  if (preference && preference !== "system") return preference;
  return getSystemTheme();
}

/**
 * Apply a resolved palette to the document.
 */
export function applyThemeToDocument(theme: Theme): void {
  if (typeof document === "undefined") return;

  const html = document.documentElement;

  html.classList.remove("dark", "theme-glass", "theme-snow");

  if (theme === "dark") {
    html.classList.add("dark");
  } else if (theme === "glass") {
    html.classList.add("dark", "theme-glass");
  } else if (theme === "snow") {
    html.classList.add("theme-snow");
  }
}

function detachSystemThemeListener(): void {
  if (systemMedia && systemMediaHandler) {
    systemMedia.removeEventListener("change", systemMediaHandler);
  }
  systemMedia = null;
  systemMediaHandler = null;
}

/**
 * Subscribe while the preference follows the OS. Explicit palettes detach.
 * Rebinding replaces any previous listener so a new matchMedia mock or a
 * preference change cannot stack handlers.
 */
function syncSystemThemeSubscription(preference: ThemePreference | null): void {
  detachSystemThemeListener();
  if (!followsSystem(preference)) return;
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return;
  }

  const media = window.matchMedia("(prefers-color-scheme: dark)");
  const onChange = (event: MediaQueryListEvent) => {
    if (!followsSystem(getStoredThemePreference())) {
      detachSystemThemeListener();
      return;
    }
    const next: Theme = event.matches ? "dark" : "snow";
    applyThemeToDocument(next);
    notifyThemeChange(next);
  };
  media.addEventListener("change", onChange);
  systemMedia = media;
  systemMediaHandler = onChange;
}

/**
 * Initialize theme on app startup.
 * Priority: explicit localStorage palette > live system preference.
 * A missing value follows the OS and is not written back.
 */
export function initializeTheme(): Theme {
  const preference = getStoredThemePreference();
  const resolved = resolveTheme(preference);
  applyThemeToDocument(resolved);
  syncSystemThemeSubscription(preference);
  return resolved;
}

/**
 * Set a preference and persist it.
 * "system" is stored as the choice itself; the document gets the live palette.
 */
export function setTheme(theme: ThemePreference): void {
  const resolved = resolveTheme(theme);
  applyThemeToDocument(resolved);
  saveThemeToStorage(theme);
  syncSystemThemeSubscription(theme);
  notifyThemeChange(resolved);
}
