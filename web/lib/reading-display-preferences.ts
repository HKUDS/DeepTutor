export type ReaderTheme = "auto" | "sepia" | "night";

export interface ReaderDisplayPreferences {
  fontSize: number;
  lineWidth: number;
  serif: boolean;
  readerTheme: ReaderTheme;
}

export const DEFAULT_FONT_SIZE = 17;
export const MIN_FONT_SIZE = 12;
export const MAX_FONT_SIZE = 28;
export const DEFAULT_LINE_WIDTH = 84;
export const MIN_LINE_WIDTH = 48;
export const MAX_LINE_WIDTH = 104;
export const DEFAULT_READER_DISPLAY_PREFERENCES: ReaderDisplayPreferences = {
  fontSize: DEFAULT_FONT_SIZE,
  lineWidth: DEFAULT_LINE_WIDTH,
  serif: true,
  readerTheme: "auto",
};

function bounded(
  value: unknown,
  fallback: number,
  minimum: number,
  maximum: number,
): number {
  return typeof value === "number" && Number.isFinite(value)
    ? Math.min(maximum, Math.max(minimum, value))
    : fallback;
}

export function normaliseReaderDisplayPreferences(
  value: unknown,
): ReaderDisplayPreferences {
  const row =
    value && typeof value === "object"
      ? (value as Record<string, unknown>)
      : {};
  const readerTheme = ["auto", "sepia", "night"].includes(
    String(row.readerTheme),
  )
    ? (row.readerTheme as ReaderTheme)
    : DEFAULT_READER_DISPLAY_PREFERENCES.readerTheme;
  return {
    fontSize: bounded(
      row.fontSize,
      DEFAULT_FONT_SIZE,
      MIN_FONT_SIZE,
      MAX_FONT_SIZE,
    ),
    lineWidth: bounded(
      row.lineWidth,
      DEFAULT_LINE_WIDTH,
      MIN_LINE_WIDTH,
      MAX_LINE_WIDTH,
    ),
    serif:
      typeof row.serif === "boolean"
        ? row.serif
        : DEFAULT_READER_DISPLAY_PREFERENCES.serif,
    readerTheme,
  };
}

export type ReaderDisplayShortcut = "increase" | "decrease" | "reset";

export function readerDisplayShortcut(input: {
  key: string;
  modifier: boolean;
  readerHovered: boolean;
  readerFocused: boolean;
}): ReaderDisplayShortcut | null {
  if (!input.modifier || (!input.readerHovered && !input.readerFocused))
    return null;
  if (input.key === "+" || input.key === "=") return "increase";
  if (input.key === "-") return "decrease";
  if (input.key === "0") return "reset";
  return null;
}
