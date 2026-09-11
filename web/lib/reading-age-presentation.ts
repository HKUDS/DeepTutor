export type ReadingAgeMode =
  | "early"
  | "young"
  | "older"
  | "default";

type ActionTone = "speech" | "vocabulary" | "quiz" | "general";

const BAND_STARTS: Record<string, number> = {
  "6-8": 6,
  "9-12": 9,
  "13-15": 13,
};

export function resolveReadingAgeMode(
  profileAge?: number | null,
  learningAgeBand?: string | null,
): ReadingAgeMode {
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

  const bandStart = learningAgeBand
    ? BAND_STARTS[learningAgeBand]
    : undefined;
  if (bandStart === undefined) return "default";
  if (bandStart <= 6) return "young";
  if (bandStart <= 9) return "older";
  return "default";
}

export function readingToolbarClass(mode: ReadingAgeMode) {
  if (mode === "early") return "gap-2.5 px-3 py-3";
  if (mode === "young") return "gap-2 px-3 py-2.5";
  if (mode === "older") return "gap-2 px-2.5 py-2";
  return "gap-1.5 px-2.5 py-2";
}

export function readingMoreClass(mode: ReadingAgeMode) {
  if (mode === "early")
    return "min-h-14 rounded-full border-2 px-4 text-base font-bold shadow-sm";
  if (mode === "young")
    return "min-h-12 rounded-2xl border px-3 text-sm font-semibold shadow-sm";
  if (mode === "older")
    return "min-h-11 rounded-xl border px-3 text-sm font-semibold";
  return "rounded-lg border px-2 text-xs";
}

export function readingActionClass(
  mode: ReadingAgeMode,
  tone: ActionTone,
) {
  const size =
    mode === "early"
      ? "min-h-14 rounded-full border-2 px-3 py-2 text-base font-bold shadow-sm"
      : mode === "young"
        ? "min-h-12 rounded-2xl border px-3 py-2 text-sm font-semibold shadow-sm"
        : mode === "older"
          ? "min-h-11 rounded-xl border px-3 py-1.5 text-sm font-semibold"
          : "min-h-8 rounded-lg border px-2 py-1 text-xs font-medium";

  if (mode === "default") {
    return `${size} border-[var(--border)] bg-[var(--card)] text-[var(--foreground)] transition hover:bg-[var(--muted)] disabled:opacity-50`;
  }

  const palette =
    mode === "early"
      ? {
          speech:
            "border-emerald-300 bg-emerald-100 text-emerald-950 hover:bg-emerald-200",
          vocabulary:
            "border-amber-300 bg-amber-100 text-amber-950 hover:bg-amber-200",
          quiz: "border-sky-300 bg-sky-100 text-sky-950 hover:bg-sky-200",
          general:
            "border-violet-300 bg-violet-100 text-violet-950 hover:bg-violet-200",
        }
      : mode === "young"
        ? {
            speech:
              "border-emerald-200 bg-emerald-50 text-emerald-900 hover:bg-emerald-100",
            vocabulary:
              "border-amber-200 bg-amber-50 text-amber-900 hover:bg-amber-100",
            quiz: "border-sky-200 bg-sky-50 text-sky-900 hover:bg-sky-100",
            general:
              "border-violet-200 bg-violet-50 text-violet-900 hover:bg-violet-100",
          }
        : {
            speech:
              "border-emerald-200 bg-emerald-50/60 text-emerald-800 hover:bg-emerald-50",
            vocabulary:
              "border-amber-200 bg-amber-50/60 text-amber-800 hover:bg-amber-50",
            quiz: "border-sky-200 bg-sky-50/60 text-sky-800 hover:bg-sky-50",
            general:
              "border-violet-200 bg-violet-50/60 text-violet-800 hover:bg-violet-50",
          };

  return `${size} ${palette[tone]} transition disabled:opacity-50`;
}
