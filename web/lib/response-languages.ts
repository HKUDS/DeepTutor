/**
 * Reply-language codes the settings picker lists, plus a compact BCP-47
 * check for Custom values. Mirrors ``RESPONSE_LANGUAGE_CHOICES`` /
 * ``is_response_language_code`` in ``deeptutor/services/prompt/language.py``.
 */

export const RESPONSE_LANGUAGE_OPTIONS: Array<{ code: string; label: string }> =
  [
    { code: "en", label: "English" },
    { code: "zh", label: "简体中文" },
    { code: "zh-tw", label: "繁體中文" },
    { code: "ja", label: "日本語" },
    { code: "ko", label: "한국어" },
    { code: "es", label: "Español" },
    { code: "fr", label: "Français" },
    { code: "de", label: "Deutsch" },
    { code: "ru", label: "Русский" },
    { code: "pt", label: "Português" },
    { code: "it", label: "Italiano" },
  ];

export const CUSTOM_RESPONSE_LANGUAGE = "__custom__";

const RESPONSE_LANGUAGE_CODE_RE = /^[a-z]{2,3}(-[a-z0-9]{2,8}){0,2}$/;
const RESPONSE_LANGUAGE_CODE_MAX_LEN = 16;

export function isListedResponseLanguage(code: string): boolean {
  return RESPONSE_LANGUAGE_OPTIONS.some((option) => option.code === code);
}

export function isResponseLanguageCode(value: string | null | undefined): boolean {
  if (!value) return false;
  const code = value.trim().toLowerCase();
  if (!code || code.length > RESPONSE_LANGUAGE_CODE_MAX_LEN) return false;
  return RESPONSE_LANGUAGE_CODE_RE.test(code);
}

export function tryParseResponseLanguage(
  value: string | null | undefined,
): string | null {
  if (!value) return null;
  const raw = value.trim().toLowerCase();
  if (!raw) return null;
  if (raw === "english") return "en";
  if (raw === "chinese" || raw === "cn") return "zh";
  return isResponseLanguageCode(raw) ? raw : null;
}
