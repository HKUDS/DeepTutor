// Options and value handling for the web fetch backend select.
//
// The answer comes from the backend (`GET /api/settings/web-fetch`), which
// derives the list from the `FETCH_PROVIDERS` spec table next to the search
// providers. There is deliberately no backend table here — a second copy is
// how the web app ended up flagging Serper as deprecated while the backend
// supported it. Until the choices load, the select shows only the stored
// value: better one honest option than a name list this module invented.

export type WebFetchBackendChoice = {
  value: string;
  label: string;
  requires_api_key?: boolean;
};

export type WebFetchSettingsPayload = {
  settings: { backend: string };
  effective: { backend: string };
  choices: WebFetchBackendChoice[];
};

export type WebFetchBackendOption = { value: string; label: string };

export const DEFAULT_WEB_FETCH_BACKEND = "local";

/**
 * Select options for the fetch backend, given the backend's own choices.
 * Unknown, custom, or not-yet-loaded lists fall back to a single option
 * carrying the stored value, so the control never offers a name the backend
 * did not send.
 */
export function webFetchBackendOptions(
  choices: WebFetchBackendChoice[] | null | undefined,
  current: string | null | undefined,
): WebFetchBackendOption[] {
  const options = (choices ?? [])
    .filter((choice) => Boolean(choice && choice.value))
    .map((choice) => ({
      value: choice.value,
      label: choice.label?.trim() || choice.value,
    }));
  if (options.length > 0) return options;
  const stored = (current ?? "").trim();
  return stored ? [{ value: stored, label: stored }] : [];
}

/**
 * The select value for a stored backend: an offered option as-is, otherwise
 * the default backend when it is offered, otherwise the first option — an
 * unknown stored value must never render a select with nothing selected.
 */
export function webFetchBackendValue(
  value: string | null | undefined,
  options: WebFetchBackendOption[],
): string {
  const raw = (value ?? "").trim();
  if (raw && options.some((option) => option.value === raw)) return raw;
  const fallback = options.find(
    (option) => option.value === DEFAULT_WEB_FETCH_BACKEND,
  );
  return fallback ? fallback.value : (options[0]?.value ?? "");
}
