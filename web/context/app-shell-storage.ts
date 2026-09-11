"use client";

import { browserStorage } from "@/shared/storage";

export type AppLanguage = "en" | "zh";

export const ACTIVE_SESSION_STORAGE_KEY = "deeptutor.activeSessionId.tab";
export const LANGUAGE_STORAGE_KEY = "deeptutor-language";
export const RESPONSE_LANGUAGE_STORAGE_KEY = "deeptutor-response-language";
export const SIDEBAR_COLLAPSED_STORAGE_KEY = "deeptutor.sidebarCollapsed";
export const CHAT_RESPONSE_TIMEOUT_STORAGE_KEY =
  "deeptutor.chatResponseTimeout";
export const CODE_BLOCK_THEME_STORAGE_KEY = "deeptutor.code-block-theme";
export const CODE_BLOCK_SHOW_LINE_NUMBERS_STORAGE_KEY =
  "deeptutor.code-block-show-line-numbers";
export const CODE_BLOCK_WRAP_LONG_LINES_STORAGE_KEY =
  "deeptutor.code-block-wrap-long-lines";

// Mirror of the per-user ``chat_response_timeout`` UI preference. Cached in
// localStorage so the chat watchdog (a separate provider from Settings) can
// read it synchronously without its own fetch. Kept in sync on settings load.
export const DEFAULT_CHAT_RESPONSE_TIMEOUT_SECONDS = 180;
export const MIN_CHAT_RESPONSE_TIMEOUT_SECONDS = 30;
export const MAX_CHAT_RESPONSE_TIMEOUT_SECONDS = 1800;

export function clampChatResponseTimeout(seconds: number): number {
  if (!Number.isFinite(seconds)) return DEFAULT_CHAT_RESPONSE_TIMEOUT_SECONDS;
  return Math.min(
    MAX_CHAT_RESPONSE_TIMEOUT_SECONDS,
    Math.max(MIN_CHAT_RESPONSE_TIMEOUT_SECONDS, Math.round(seconds)),
  );
}

export function readStoredChatResponseTimeout(): number {
  if (typeof window === "undefined")
    return DEFAULT_CHAT_RESPONSE_TIMEOUT_SECONDS;
  try {
    const raw = browserStorage.readRaw(
      "local",
      CHAT_RESPONSE_TIMEOUT_STORAGE_KEY,
    );
    const parsed = raw ? Number.parseInt(raw, 10) : NaN;
    return Number.isFinite(parsed) && parsed > 0
      ? clampChatResponseTimeout(parsed)
      : DEFAULT_CHAT_RESPONSE_TIMEOUT_SECONDS;
  } catch {
    return DEFAULT_CHAT_RESPONSE_TIMEOUT_SECONDS;
  }
}

export function writeStoredChatResponseTimeout(seconds: number): void {
  if (typeof window === "undefined") return;
  try {
    browserStorage.writeRaw(
      "local",
      CHAT_RESPONSE_TIMEOUT_STORAGE_KEY,
      String(clampChatResponseTimeout(seconds)),
    );
  } catch {
    // localStorage may be unavailable
  }
}

export const ACTIVE_SESSION_EVENT = "deeptutor:active-session";
export const LANGUAGE_EVENT = "deeptutor:language";
export const RESPONSE_LANGUAGE_EVENT = "deeptutor:response-language";
export const SIDEBAR_COLLAPSED_EVENT = "deeptutor:sidebar-collapsed";
export const CODE_BLOCK_SETTINGS_EVENT = "deeptutor:code-block-settings";

export function normalizeLanguage(
  value: string | null | undefined,
): AppLanguage {
  return value === "zh" ? "zh" : "en";
}

export function resolveResponseLanguage(
  value: string | null | undefined,
  legacyLanguage: string | null | undefined = "en",
): AppLanguage {
  return value === "zh" || value === "en"
    ? value
    : normalizeLanguage(legacyLanguage);
}

export function readStoredLanguage(): AppLanguage {
  if (typeof window === "undefined") return "en";
  try {
    return normalizeLanguage(
      browserStorage.readRaw("local", LANGUAGE_STORAGE_KEY),
    );
  } catch {
    return "en";
  }
}

/** Whether this browser has ever recorded a choice.
 *
 * ``readStoredLanguage`` cannot answer this: it normalizes a missing value to
 * "en", which is indistinguishable from an explicit English selection. The
 * bootstrap needs the difference — it may only consult the server-side
 * preference when the browser has no choice of its own to honour.
 */
export function hasStoredLanguage(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return browserStorage.readRaw("local", LANGUAGE_STORAGE_KEY) !== null;
  } catch {
    return false;
  }
}

export function writeStoredLanguage(language: AppLanguage): void {
  if (typeof window === "undefined") return;
  try {
    browserStorage.writeRaw("local", LANGUAGE_STORAGE_KEY, language);
    window.dispatchEvent(
      new CustomEvent(LANGUAGE_EVENT, {
        detail: { language },
      }),
    );
  } catch {
    // localStorage may be unavailable
  }
}

/** Whether this browser has ever recorded a model-output-language choice.
 *
 * The mirror of {@link hasStoredLanguage}, and needed for the same reason but
 * on the other key. The two languages were split later than the interface one,
 * so a browser that predates the split has `deeptutor-language` and no
 * `deeptutor-response-language` — and gating adoption of the server's value on
 * `hasStoredLanguage` alone locks such a browser out of ever picking one up.
 */
export function hasStoredResponseLanguage(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return (
      browserStorage.readRaw("local", RESPONSE_LANGUAGE_STORAGE_KEY) !== null
    );
  } catch {
    return false;
  }
}

export function readStoredResponseLanguage(): AppLanguage {
  if (typeof window === "undefined") return "en";
  try {
    return resolveResponseLanguage(
      browserStorage.readRaw("local", RESPONSE_LANGUAGE_STORAGE_KEY),
      browserStorage.readRaw("local", LANGUAGE_STORAGE_KEY),
    );
  } catch {
    return "en";
  }
}

export function writeStoredResponseLanguage(language: AppLanguage): void {
  if (typeof window === "undefined") return;
  try {
    browserStorage.writeRaw("local", RESPONSE_LANGUAGE_STORAGE_KEY, language);
    window.dispatchEvent(
      new CustomEvent(RESPONSE_LANGUAGE_EVENT, {
        detail: { language },
      }),
    );
  } catch {
    // localStorage may be unavailable
  }
}

export function readStoredActiveSessionId(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return browserStorage.readRaw("session", ACTIVE_SESSION_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function writeStoredActiveSessionId(sessionId: string | null): void {
  if (typeof window === "undefined") return;
  try {
    if (sessionId) {
      browserStorage.writeRaw("session", ACTIVE_SESSION_STORAGE_KEY, sessionId);
    } else {
      browserStorage.removeRaw("session", ACTIVE_SESSION_STORAGE_KEY);
    }
    window.dispatchEvent(
      new CustomEvent(ACTIVE_SESSION_EVENT, {
        detail: { sessionId },
      }),
    );
  } catch {
    // sessionStorage may be unavailable
  }
}

export function readStoredSidebarCollapsed(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return (
      browserStorage.readRaw("local", SIDEBAR_COLLAPSED_STORAGE_KEY) === "1"
    );
  } catch {
    return false;
  }
}

export function writeStoredSidebarCollapsed(collapsed: boolean): void {
  if (typeof window === "undefined") return;
  try {
    browserStorage.writeRaw(
      "local",
      SIDEBAR_COLLAPSED_STORAGE_KEY,
      collapsed ? "1" : "0",
    );
    window.dispatchEvent(
      new CustomEvent(SIDEBAR_COLLAPSED_EVENT, {
        detail: { collapsed },
      }),
    );
  } catch {
    // localStorage may be unavailable
  }
}

// Code block settings defaults
export const DEFAULT_CODE_BLOCK_THEME = "oneDark";
export const DEFAULT_CODE_BLOCK_SHOW_LINE_NUMBERS = false;
export const DEFAULT_CODE_BLOCK_WRAP_LONG_LINES = false;

export function normalizeCodeBlockTheme(
  value: string | null | undefined,
): string {
  if (!value || value.trim() === "") return DEFAULT_CODE_BLOCK_THEME;
  return value.trim();
}

export function readStoredCodeBlockTheme(): string {
  if (typeof window === "undefined") return DEFAULT_CODE_BLOCK_THEME;
  try {
    const raw = browserStorage.readRaw("local", CODE_BLOCK_THEME_STORAGE_KEY);
    return normalizeCodeBlockTheme(raw);
  } catch {
    return DEFAULT_CODE_BLOCK_THEME;
  }
}

export function writeStoredCodeBlockTheme(theme: string): void {
  if (typeof window === "undefined") return;
  try {
    browserStorage.writeRaw(
      "local",
      CODE_BLOCK_THEME_STORAGE_KEY,
      normalizeCodeBlockTheme(theme),
    );
    window.dispatchEvent(
      new CustomEvent(CODE_BLOCK_SETTINGS_EVENT, {
        detail: { codeBlockTheme: normalizeCodeBlockTheme(theme) },
      }),
    );
  } catch {
    // localStorage may be unavailable
  }
}

export function normalizeCodeBlockShowLineNumbers(
  value: string | null | undefined,
): boolean {
  if (value === "true") return true;
  if (value === "false") return false;
  return DEFAULT_CODE_BLOCK_SHOW_LINE_NUMBERS;
}

export function readStoredCodeBlockShowLineNumbers(): boolean {
  if (typeof window === "undefined")
    return DEFAULT_CODE_BLOCK_SHOW_LINE_NUMBERS;
  try {
    const raw = browserStorage.readRaw(
      "local",
      CODE_BLOCK_SHOW_LINE_NUMBERS_STORAGE_KEY,
    );
    return normalizeCodeBlockShowLineNumbers(raw);
  } catch {
    return DEFAULT_CODE_BLOCK_SHOW_LINE_NUMBERS;
  }
}

export function writeStoredCodeBlockShowLineNumbers(show: boolean): void {
  if (typeof window === "undefined") return;
  try {
    browserStorage.writeRaw(
      "local",
      CODE_BLOCK_SHOW_LINE_NUMBERS_STORAGE_KEY,
      String(show),
    );
    window.dispatchEvent(
      new CustomEvent(CODE_BLOCK_SETTINGS_EVENT, {
        detail: { codeBlockShowLineNumbers: show },
      }),
    );
  } catch {
    // localStorage may be unavailable
  }
}

export function normalizeCodeBlockWrapLongLines(
  value: string | null | undefined,
): boolean {
  if (value === "true") return true;
  if (value === "false") return false;
  return DEFAULT_CODE_BLOCK_WRAP_LONG_LINES;
}

export function readStoredCodeBlockWrapLongLines(): boolean {
  if (typeof window === "undefined") return DEFAULT_CODE_BLOCK_WRAP_LONG_LINES;
  try {
    const raw = browserStorage.readRaw(
      "local",
      CODE_BLOCK_WRAP_LONG_LINES_STORAGE_KEY,
    );
    return normalizeCodeBlockWrapLongLines(raw);
  } catch {
    return DEFAULT_CODE_BLOCK_WRAP_LONG_LINES;
  }
}

export function writeStoredCodeBlockWrapLongLines(wrap: boolean): void {
  if (typeof window === "undefined") return;
  try {
    browserStorage.writeRaw(
      "local",
      CODE_BLOCK_WRAP_LONG_LINES_STORAGE_KEY,
      String(wrap),
    );
    window.dispatchEvent(
      new CustomEvent(CODE_BLOCK_SETTINGS_EVENT, {
        detail: { codeBlockWrapLongLines: wrap },
      }),
    );
  } catch {
    // localStorage may be unavailable
  }
}
