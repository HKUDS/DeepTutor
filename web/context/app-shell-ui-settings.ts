import { apiFetch, apiUrl } from "@/lib/api";

import {
  normalizeLanguage,
  type AppLanguage,
} from "@/context/app-shell-storage";

type UiSettingsPayload = {
  ui?: {
    language?: unknown;
  };
};

export async function fetchBackendLanguage(
  fetcher: typeof apiFetch = apiFetch,
): Promise<AppLanguage | null> {
  try {
    const response = await fetcher(apiUrl("/api/v1/settings"), {
      skipAuthRedirect: true,
    });
    if (!response.ok) return null;

    const payload = (await response.json()) as UiSettingsPayload;
    const language = payload.ui?.language;
    if (typeof language !== "string") return null;

    const normalized = language.trim().toLowerCase();
    if (!["en", "english", "zh", "chinese", "cn"].includes(normalized)) {
      return null;
    }
    return normalizeLanguage(normalized);
  } catch {
    return null;
  }
}
