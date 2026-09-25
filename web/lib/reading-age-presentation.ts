export type ReadingAgeMode = "early" | "young" | "older" | "default";

type ReadingAgeInput = {
  learnerMode: boolean;
  profileAge?: number | null;
  policyAgeBand?: string | null;
};

/** Keep a profile age private to the host; extensions only see their usual action input. */
export function resolveReadingAgeMode({
  learnerMode,
  profileAge,
  policyAgeBand,
}: ReadingAgeInput): ReadingAgeMode {
  if (!learnerMode) return "default";
  if (
    typeof profileAge === "number" &&
    Number.isInteger(profileAge) &&
    profileAge >= 3 &&
    profileAge <= 120
  ) {
    if (profileAge <= 6) return "early";
    if (profileAge <= 9) return "young";
    if (profileAge <= 12) return "older";
    return "default";
  }
  // Policy bands are coarser than profile ages. Never guess the 3–6 style
  // from a 6–8 band, which also includes older learners.
  if (policyAgeBand === "6-8") return "young";
  if (policyAgeBand === "9-12") return "older";
  return "default";
}

export const PRIMARY_READING_ACTIONS = [
  "read_aloud:read",
  "vocabulary:explain",
  "quiz:start",
] as const;

export function primaryReadingActionRank(key: string): number {
  return PRIMARY_READING_ACTIONS.findIndex((candidate) => candidate === key);
}

const baseButton =
  "inline-flex min-w-[88px] flex-1 items-center justify-center gap-1.5 border focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-600 focus-visible:ring-offset-2 disabled:opacity-50";

const adultButton =
  "h-8 rounded-lg border-[var(--border)] bg-[var(--card)] px-2 text-xs font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)]";

const learnerButtons: Record<Exclude<ReadingAgeMode, "default">, string> = {
  early:
    "min-h-14 min-w-[112px] w-max flex-none flex-col gap-0.5 rounded-[20px] border-2 px-3 py-1 text-xs font-bold leading-tight max-sm:min-w-0 max-sm:w-0 max-sm:flex-1 max-sm:px-1 motion-safe:animate-[dt-reading-button-enter_220ms_ease-out_both] motion-safe:transition-transform motion-safe:hover:-translate-y-0.5 motion-safe:active:translate-y-0.5",
  young:
    "min-h-12 min-w-[100px] w-max flex-none rounded-2xl border-2 px-3 text-sm font-semibold max-sm:min-w-0 max-sm:w-0 max-sm:flex-1 max-sm:flex-col max-sm:gap-0.5 max-sm:px-1 motion-safe:transition-transform motion-safe:hover:-translate-y-0.5 motion-safe:active:scale-[.98]",
  older:
    "min-h-11 w-max flex-none rounded-xl border px-3 text-sm font-medium max-sm:min-w-0 max-sm:w-0 max-sm:flex-1 max-sm:flex-col max-sm:gap-0.5 max-sm:px-1 motion-safe:transition-transform motion-safe:active:scale-[.99]",
};

const tones: Record<Exclude<ReadingAgeMode, "default">, Record<string, string>> = {
  early: {
    "read_aloud:read": "border-emerald-300 bg-emerald-100 text-emerald-950 hover:bg-emerald-200",
    "vocabulary:explain": "border-amber-300 bg-amber-100 text-amber-950 hover:bg-amber-200",
    "quiz:start": "border-sky-300 bg-sky-100 text-sky-950 hover:bg-sky-200",
  },
  young: {
    "read_aloud:read": "border-emerald-200 bg-emerald-50 text-emerald-950 hover:bg-emerald-100",
    "vocabulary:explain": "border-amber-200 bg-amber-50 text-amber-950 hover:bg-amber-100",
    "quiz:start": "border-sky-200 bg-sky-50 text-sky-950 hover:bg-sky-100",
  },
  older: {
    "read_aloud:read": "border-emerald-200 bg-emerald-50 text-emerald-950 hover:bg-emerald-100",
    "vocabulary:explain": "border-amber-200 bg-amber-50 text-amber-950 hover:bg-amber-100",
    "quiz:start": "border-sky-200 bg-sky-50 text-sky-950 hover:bg-sky-100",
  },
};

export function readingActionClass(mode: ReadingAgeMode, key: string): string {
  if (mode === "default") return `${baseButton} ${adultButton}`;
  const tone = tones[mode][key];
  return tone ? `${baseButton} ${learnerButtons[mode]} ${tone}` : `${baseButton} ${adultButton}`;
}
