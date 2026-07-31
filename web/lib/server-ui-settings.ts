export type InitialAppLanguage = "en" | "zh";

const DEFAULT_API_BASE_URL = "http://localhost:8001";

export async function loadInitialLanguage(
  fetcher: typeof fetch = fetch,
  apiBaseUrl = process.env.DEEPTUTOR_API_BASE_URL ?? DEFAULT_API_BASE_URL,
): Promise<InitialAppLanguage | null> {
  try {
    const response = await fetcher(
      new URL("/api/v1/settings/ui", apiBaseUrl),
      { cache: "no-store" },
    );
    if (!response.ok) return null;

    const payload = (await response.json()) as { language?: unknown };
    return payload.language === "zh" || payload.language === "en"
      ? payload.language
      : null;
  } catch {
    return null;
  }
}
