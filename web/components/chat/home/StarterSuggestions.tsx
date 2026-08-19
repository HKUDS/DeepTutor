"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, Sparkles } from "lucide-react";
import { apiFetch, apiUrl } from "@/lib/api";

interface Suggestion {
  /** The line the learner reads — names the specific thing worth doing next. */
  label: string;
  /** What gets sent as the learner's own message when they click. */
  prompt: string;
}

interface SuggestionPayload {
  suggestions: Suggestion[];
  /** True when the backend is regenerating this set behind the request. */
  stale: boolean;
}

/**
 * How long to wait before re-reading a set the backend said was stale, and how
 * many times.
 *
 * The backend answers instantly and regenerates behind the request, so the
 * fresh set exists a moment later — but "a moment" is a model call, which on a
 * cold provider is comfortably longer than one interval. A few spaced re-reads
 * cover that without turning into a poll; they stop as soon as something
 * arrives, and after the last one the manual control takes over.
 */
const RESETTLE_MS = 3500;
const RESETTLE_ATTEMPTS = 4;

/**
 * What the slot is showing.
 *
 * ``idle`` is the important one: it is reached from a cold cache, a generation
 * that produced nothing, a failed request, and a set of re-reads that timed
 * out — every way this can fail to have lines. All of them render the same
 * explicit control, so the answer to "why is there nothing there" is always a
 * button rather than an empty space.
 */
type View =
  | { kind: "loading" }
  | { kind: "ready"; items: Suggestion[] }
  | { kind: "working" }
  | { kind: "idle"; note?: "no-material" };

/**
 * The three things worth exploring next, under the home composer.
 *
 * Each line shows its ``label`` — a specific thing worth understanding, drawn
 * from what this learner has actually been working on — and sends its
 * ``prompt`` as their own message, so a click starts a real conversation
 * rather than prefilling something they still have to finish. Generation,
 * caching and staleness live on the backend; this renders the result, and owns
 * the manual way back when there is nothing to render.
 *
 * There is no generic fallback copy: the value of these lines is that they are
 * about *this* learner's material, and filler in the same slot would teach
 * people to stop reading it. But "no lines" is not the same as "no slot" — a
 * cold cache, a model that failed, or an output-language switch that
 * invalidated the cache all leave a visible control that regenerates on
 * demand.
 *
 * One per line, left-aligned to the composer's own edge, with no border or
 * fill: these name specific ideas, and a specific sentence in a pill reads as
 * a tag rather than as an invitation. The arrow carries the invitation
 * instead, and is the only coloured element at rest.
 */
export default function StarterSuggestions({
  onPick,
  disabled = false,
}: {
  /** Send this text as the learner's message, starting the session. */
  onPick: (prompt: string) => void;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  // Everything generated here is already in the learner's chosen output
  // language (resolved server-side from their model-output setting) and never
  // goes through the i18n table — a label that happened to match a key would
  // be silently replaced by an unrelated translation. Only this component's
  // own chrome is translated.
  const [view, setView] = useState<View>({ kind: "loading" });
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(
    async (signal?: AbortSignal): Promise<SuggestionPayload | null> => {
      try {
        const response = await apiFetch(
          apiUrl("/api/v1/dashboard/suggestions"),
          {
            signal,
            cache: "no-store",
          },
        );
        if (!response.ok) return null;
        return (await response.json()) as SuggestionPayload;
      } catch {
        return null;
      }
    },
    [],
  );

  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      const payload = await load(controller.signal);
      if (controller.signal.aborted) return;
      if (payload?.suggestions.length) {
        setView({ kind: "ready", items: payload.suggestions });
        return;
      }
      // Nothing yet. If the backend says a set is on its way, wait for it and
      // show that something is happening; otherwise hand over the control.
      if (!payload?.stale) {
        setView({ kind: "idle", note: payload ? "no-material" : undefined });
        return;
      }
      setView({ kind: "working" });
      let attempt = 0;
      const collect = () => {
        void load(controller.signal).then((next) => {
          if (controller.signal.aborted) return;
          if (next?.suggestions.length) {
            setView({ kind: "ready", items: next.suggestions });
            return;
          }
          if (++attempt < RESETTLE_ATTEMPTS) {
            timerRef.current = setTimeout(collect, RESETTLE_MS);
            return;
          }
          // Gave it long enough. Stop spinning and let the learner decide.
          setView({ kind: "idle" });
        });
      };
      timerRef.current = setTimeout(collect, RESETTLE_MS);
    })();
    return () => {
      controller.abort();
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [load]);

  const generate = useCallback(async () => {
    if (timerRef.current) clearTimeout(timerRef.current);
    setView({ kind: "working" });
    try {
      const response = await apiFetch(
        apiUrl("/api/v1/dashboard/suggestions/refresh"),
        { method: "POST" },
      );
      if (!response.ok) {
        setView({ kind: "idle" });
        return;
      }
      const payload = (await response.json()) as SuggestionPayload;
      setView(
        payload.suggestions.length
          ? { kind: "ready", items: payload.suggestions }
          : { kind: "idle", note: "no-material" },
      );
    } catch {
      // A failed generation is not worth an error banner; the control stays.
      setView({ kind: "idle" });
    }
  }, []);

  // Only the very first read renders nothing: lines appearing a beat late is
  // calmer than a control that flashes and is immediately replaced.
  if (view.kind === "loading") return null;

  return (
    // max-w-[768px] + px-6 mirrors ChatComposer's own empty-state container, so
    // the lines start exactly at the composer's left edge rather than floating
    // near it.
    <div className="group/starters mx-auto w-full max-w-[768px] px-6 pb-6 animate-fade-in">
      {view.kind === "ready" && (
        <ul className="flex flex-col items-start">
          {view.items.map((item) => (
            <li key={item.label} className="max-w-full">
              <button
                type="button"
                disabled={disabled}
                onClick={() => onPick(item.prompt)}
                title={item.prompt}
                className="group/line flex max-w-full items-baseline gap-2 py-[5px] text-left font-serif text-[15.5px] leading-[1.45] tracking-[-0.005em] text-[color-mix(in_srgb,var(--foreground)_72%,transparent)] transition-colors duration-200 hover:text-[var(--primary)] focus-visible:text-[var(--primary)] focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-40"
              >
                <span className="truncate">{item.label}</span>
                {/* The arrow is the invitation: coloured at rest so the line
                    reads as something to click, and it steps right on hover. */}
                <span
                  aria-hidden="true"
                  className="shrink-0 text-[color-mix(in_srgb,var(--primary)_65%,transparent)] transition-all duration-200 ease-out group-hover/line:translate-x-1 group-hover/line:text-[var(--primary)] group-focus-visible/line:translate-x-1"
                >
                  →
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="flex items-center gap-2.5 pt-1.5">
        <button
          type="button"
          onClick={() => void generate()}
          disabled={view.kind === "working" || disabled}
          className={`inline-flex items-center gap-1.5 text-[11.5px] transition-all duration-200 hover:text-[var(--foreground)] disabled:cursor-default ${
            // While there are lines this is a quiet reroll that surfaces on
            // hover; with nothing to show it is the only way forward, so it
            // stays visible.
            view.kind === "ready"
              ? "text-[color-mix(in_srgb,var(--muted-foreground)_55%,transparent)] opacity-0 focus-visible:opacity-100 group-hover/starters:opacity-100"
              : "text-[var(--muted-foreground)]"
          }`}
        >
          {view.kind === "working" ? (
            <Loader2 size={11} strokeWidth={1.8} className="animate-spin" />
          ) : (
            <Sparkles size={11} strokeWidth={1.8} />
          )}
          {view.kind === "working"
            ? t("Finding what to explore next...")
            : view.kind === "ready"
              ? t("Suggest something else")
              : t("Suggest what to explore next")}
        </button>

        {view.kind === "idle" && view.note === "no-material" && (
          <span className="text-[11.5px] text-[color-mix(in_srgb,var(--muted-foreground)_70%,transparent)]">
            {t("Not enough history yet — have a conversation first.")}
          </span>
        )}
      </div>
    </div>
  );
}
