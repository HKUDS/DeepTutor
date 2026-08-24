"use client";

import { useEffect, useRef } from "react";

import { apiFetch, apiUrl } from "@/lib/api";
import {
  resolveResponseLanguage,
  writeStoredLanguage,
  writeStoredResponseLanguage,
  type AppLanguage,
} from "@/context/app-shell-storage";
import { setTheme, type Theme } from "@/lib/theme";
import { collectAppliedSettingIds } from "@/lib/setup-signals";
import type { StreamEvent } from "@/lib/unified-ws";

const THEMES: readonly Theme[] = ["light", "dark", "glass", "snow"];

function asTheme(value: unknown): Theme | null {
  return typeof value === "string" &&
    (THEMES as readonly string[]).includes(value)
    ? (value as Theme)
    : null;
}

/**
 * Re-read UI preferences after the assistant changes them from within chat.
 *
 * The browser is the source of truth for language and theme: the app shell
 * reads them from localStorage and only consults the server when localStorage
 * holds nothing at all (see `AppShellContext`). That is right for a person
 * switching languages in one tab, but it means a change the assistant makes
 * on the server is invisible here — the user is told "done" while the
 * interface stays exactly as it was, which reads as a broken promise.
 *
 * So the backend's `apply_setting` tags its result with `setup_applied`, and
 * this hook treats that tag as "your cached copy is stale": it re-reads the
 * server's UI settings once and writes them through the same storage helpers a
 * manual change would use. Those helpers emit the storage events the app shell
 * already listens to, so the whole UI switches over without a reload.
 *
 * Each tool call is honoured once — replayed history and re-renders must not
 * keep overwriting a preference the user has since changed by hand.
 */
export function useSetupSync(
  messages: ReadonlyArray<{ events?: StreamEvent[] }> | undefined,
): void {
  const handledRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    const fresh = collectAppliedSettingIds(messages).filter(
      (id) => !handledRef.current.has(id),
    );
    if (fresh.length === 0) return;
    for (const id of fresh) handledRef.current.add(id);

    let cancelled = false;
    void (async () => {
      try {
        const res = await apiFetch(apiUrl("/api/v1/settings/ui"));
        if (!res.ok || cancelled) return;
        const payload = (await res.json()) as {
          language?: unknown;
          response_language?: unknown;
          theme?: unknown;
        };
        if (cancelled) return;
        if (payload.language === "zh" || payload.language === "en") {
          writeStoredLanguage(payload.language);
          writeStoredResponseLanguage(
            resolveResponseLanguage(
              typeof payload.response_language === "string"
                ? payload.response_language
                : null,
              payload.language,
            ),
          );
        }
        const theme = asTheme(payload.theme);
        if (theme) setTheme(theme);
      } catch {
        // A preference that failed to refresh is a cosmetic miss: the value is
        // stored server-side and the next load picks it up.
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [messages]);
}

export type { AppLanguage };
