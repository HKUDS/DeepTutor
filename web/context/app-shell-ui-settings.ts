import { apiFetch, apiUrl } from "@/lib/api";

import {
  normalizeLanguage,
  type AppLanguage,
} from "@/context/app-shell-storage";
import type { Theme } from "@/lib/theme";

type UiSettingsPayload = {
  ui?: {
    language?: unknown;
    theme?: unknown;
  };
};

export type BackendUiPreferences = {
  language?: AppLanguage;
  theme?: Theme;
};

const VALID_THEMES = new Set<Theme>(["light", "dark", "glass", "snow"]);

export async function fetchBackendUiPreferences(
  fetcher: typeof apiFetch = apiFetch,
): Promise<BackendUiPreferences | null> {
  try {
    const response = await fetcher(apiUrl("/api/v1/settings"), {
      skipAuthRedirect: true,
    });
    if (!response.ok) return null;

    const payload = (await response.json()) as UiSettingsPayload;
    const preferences: BackendUiPreferences = {};

    const language = payload.ui?.language;
    if (typeof language === "string") {
      const normalized = language.trim().toLowerCase();
      if (["en", "english", "zh", "chinese", "cn"].includes(normalized)) {
        preferences.language = normalizeLanguage(normalized);
      }
    }

    const theme = payload.ui?.theme;
    if (typeof theme === "string" && VALID_THEMES.has(theme as Theme)) {
      preferences.theme = theme as Theme;
    }

    return Object.keys(preferences).length > 0 ? preferences : null;
  } catch {
    return null;
  }
}
