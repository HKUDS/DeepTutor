import type { ResponseLanguage } from "@/i18n/languages";

export type ResponseLanguageOption = {
  value: ResponseLanguage;
  label: string;
};

/**
 * Every reply language the backend accepts, in a light module so pickers can
 * offer the full list without importing the settings store.
 */
export const RESPONSE_LANGUAGE_OPTIONS: readonly ResponseLanguageOption[] = [
  { value: "en", label: "English" },
  { value: "zh", label: "简体中文" },
  { value: "zh-tw", label: "繁體中文" },
  { value: "ja", label: "日本語" },
  { value: "ko", label: "한국어" },
  { value: "es", label: "Español" },
  { value: "fr", label: "Français" },
  { value: "de", label: "Deutsch" },
  { value: "ru", label: "Русский" },
  { value: "pt", label: "Português" },
  { value: "it", label: "Italiano" },
  { value: "ar", label: "العربية" },
  { value: "pl", label: "Polski" },
  { value: "uk", label: "Українська" },
  { value: "ms", label: "Bahasa Melayu" },
  { value: "vi", label: "Tiếng Việt" },
  { value: "tr", label: "Türkçe" },
];
