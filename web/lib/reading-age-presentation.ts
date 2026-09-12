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
    return "min-h-16 rounded-full border-[3px] px-4 text-base font-extrabold transition-transform duration-200 ease-bounce motion-safe:hover:-translate-y-1";
  if (mode === "young")
    return "min-h-12 rounded-[18px] border-2 px-3 text-sm font-bold shadow-sm transition-transform duration-150 motion-safe:hover:-translate-y-px";
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
      ? "min-h-16 min-w-fit rounded-full border-[3px] px-4 py-2.5 text-base font-extrabold"
      : mode === "young"
        ? "min-h-12 min-w-fit rounded-[18px] border-2 px-3.5 py-2 text-sm font-bold shadow-sm transition-transform duration-150 motion-safe:hover:-translate-y-px"
        : mode === "older"
          ? "min-h-11 rounded-xl border px-3 py-1.5 text-sm font-semibold"
          : "min-h-8 rounded-lg border px-2 py-1 text-xs font-medium";

  if (mode === "default") {
    return `${size} border-[var(--border)] bg-[var(--card)] text-[var(--foreground)] transition hover:bg-[var(--muted)] disabled:opacity-50`;
  }

  const lift =
    mode === "early"
      ? "transition-transform duration-200 ease-bounce motion-safe:hover:-translate-y-1 motion-safe:active:translate-y-0.5"
      : mode === "young"
        ? "transition-transform duration-150 motion-safe:hover:-translate-y-px"
        : "transition hover:brightness-[.98]";

  const palette =
    mode === "early"
      ? {
          speech:
            "border-emerald-300 bg-emerald-100 text-emerald-950 shadow-[0_5px_0_rgb(110_231_183)] hover:border-emerald-400 hover:bg-emerald-200",
          vocabulary:
            "border-amber-300 bg-amber-100 text-amber-950 shadow-[0_5px_0_rgb(252_211_77)] hover:border-amber-400 hover:bg-amber-200",
          quiz: "border-sky-300 bg-sky-100 text-sky-950 shadow-[0_5px_0_rgb(125_211_252)] hover:border-sky-400 hover:bg-sky-200",
          general:
            "border-violet-300 bg-violet-100 text-violet-950 shadow-[0_5px_0_rgb(196_181_253)] hover:border-violet-400 hover:bg-violet-200",
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

  return `${size} ${palette[tone]} ${lift} disabled:opacity-50`;
}

export function readingActionIconClass(
  mode: ReadingAgeMode,
  tone: ActionTone,
) {
  if (mode === "early") {
    return `flex h-9 w-9 items-center justify-center rounded-full bg-white/80 shadow-inner ${
      tone === "speech"
        ? "text-emerald-700"
        : tone === "vocabulary"
          ? "text-amber-700"
          : tone === "quiz"
            ? "text-sky-700"
            : "text-violet-700"
    }`;
  }
  if (mode === "young") {
    return "flex h-7 w-7 items-center justify-center rounded-full bg-white/80";
  }
  return "";
}
