export const APP_LANGUAGES = ["en", "zh", "es", "fr", "uk"] as const;

export type AppLanguage = (typeof APP_LANGUAGES)[number];

export interface AppLanguageDefinition {
  code: AppLanguage;
  labelKey: string;
  nativeLabel: string;
  locale: string;
  aliases: readonly string[];
}

export const APP_LANGUAGE_DEFINITIONS: readonly AppLanguageDefinition[] = [
  {
    code: "en",
    labelKey: "language.english",
    nativeLabel: "English",
    locale: "en-US",
    aliases: ["en", "en-us", "english"],
  },
  {
    code: "zh",
    labelKey: "language.chinese",
    nativeLabel: "简体中文",
    locale: "zh-CN",
    aliases: ["zh", "zh-cn", "cn", "chinese"],
  },
  {
    code: "es",
    labelKey: "language.spanishSpain",
    nativeLabel: "Español (España)",
    locale: "es-ES",
    aliases: ["es", "es-es", "spanish", "español"],
  },
  {
    code: "fr",
    labelKey: "language.french",
    nativeLabel: "Français",
    locale: "fr-FR",
    aliases: ["fr", "fr-fr", "french", "français"],
  },
  {
    code: "uk",
    labelKey: "language.ukrainian",
    nativeLabel: "Українська",
    locale: "uk-UA",
    aliases: ["uk", "uk-ua", "ua", "ukrainian"],
  },
];

export function isAppLanguage(value: unknown): value is AppLanguage {
  return typeof value === "string" &&
    (APP_LANGUAGES as readonly string[]).includes(value);
}

export function normalizeLanguage(language: unknown): AppLanguage {
  const candidate = String(language ?? "")
    .trim()
    .toLowerCase();
  return (
    APP_LANGUAGE_DEFINITIONS.find(({ aliases }) => aliases.includes(candidate))
      ?.code ?? "en"
  );
}

export function localeForLanguage(language: unknown): string {
  const normalized = normalizeLanguage(language);
  return (
    APP_LANGUAGE_DEFINITIONS.find(({ code }) => code === normalized)?.locale ??
    "en-US"
  );
}
