export const QUOTA_MAX_UNITS = 10_000_000_000;
export const LLM_TOKEN_UNIT = 10_000;
export const EMBEDDING_TOKEN_UNIT = 1_000_000;

export function quotaInputValue(raw: number, unit: number): string {
  if (!Number.isFinite(raw) || raw <= 0) return "0";
  const value = raw / unit;
  return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(4)));
}

export function parseQuotaInput(
  value: string,
  unit: number,
): number | null {
  const trimmed = value.trim();
  if (!/^\d+(?:\.\d{1,4})?$/.test(trimmed)) return null;
  const parsed = Number(trimmed) * unit;
  if (!Number.isSafeInteger(parsed) || parsed < 0 || parsed > QUOTA_MAX_UNITS) {
    return null;
  }
  return parsed;
}

export function formatQuotaRaw(raw: number, suffix: string): string {
  return `${new Intl.NumberFormat("en-US").format(raw)} ${suffix}`;
}
