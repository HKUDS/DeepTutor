"use client";

import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { m, useReducedMotion } from "framer-motion";
import Tooltip from "@/shared/ui/Tooltip";
import {
  ExplainMark,
  ExploreNextMark,
  PlanMark,
  PracticeMark,
  ResearchMark,
  SolveMark,
  type StarterIcon,
} from "./StarterIcons";
import { useOutsideClick } from "@/hooks/use-outside-click";
import { CornerDownLeft, Loader2, RefreshCw } from "lucide-react";
import { activeWorkspaceId, scopedUrl } from "@/lib/workspace-scope";
import { usePageCustomization } from "@/context/PageCustomizationContext";
import { starterPrompts, type StarterGroup } from "@/lib/page-customization";
import { apiFetch, apiUrl } from "@/lib/api";

interface Suggestion {
  /** The line the learner reads — names the specific thing worth doing next. */
  label: string;
  /** What lands in the composer when they pick it. */
  prompt: string;
}

interface SuggestionPayload {
  suggestions: Suggestion[];
  /** True when the backend is regenerating this set behind the request. */
  stale: boolean;
  status?: "ready" | "working" | "no-material" | "error";
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
const RESETTLE_ATTEMPTS = 10;
const REQUEST_TIMEOUT_MS = 8000;
const REFRESH_TIMEOUT_MS = 40000;

/** Empty material and failed generation are different, actionable states. */
type View =
  | { kind: "loading" }
  | { kind: "ready"; item: Suggestion }
  | { kind: "working" }
  /** `asked`: the learner requested this set, so an empty one gets explained. */
  | { kind: "idle"; note?: "no-material" | "error"; asked?: boolean };

// The backend offers one line at a time; take the first should it send more.
const ready = (items: Suggestion[]): View => ({ kind: "ready", item: items[0] });

/**
 * Ways to start, each a handful of complete requests. The prompts say what to
 * ask for when a detail is missing, so a learner can send one as it is and the
 * tutor fills the gap with a question rather than a guess.
 */
const GUIDES: readonly { id: StarterGroup; icon: StarterIcon }[] = [
  { id: "explain", icon: ExplainMark },
  { id: "solve", icon: SolveMark },
  { id: "practice", icon: PracticeMark },
  { id: "plan", icon: PlanMark },
  { id: "research", icon: ResearchMark },
];

/**
 * What to start with, under the home composer.
 *
 * A row of ways to start that suit anyone, each opening a short card of
 * requests only when chosen, and under it one line of the learner's own —
 * a single suggestion drawn from what they have been working on. Asking for
 * another generates a new one, told what was already offered. The two are kept apart because they are different
 * things: the row is a menu, the line is advice. Picking either writes the
 * request into the composer and stops there: the learner can adjust it, and
 * sending stays their decision.
 *
 * Generation, caching and staleness of the personal suggestions live on the
 * backend; this renders the result, and owns the manual way back when there
 * is nothing to render. Their text arrives already in the learner's output
 * language and never goes through the i18n table — a label that happened to
 * match a key would be silently replaced by an unrelated translation.
 */
export default function StarterSuggestions({
  onPick,
  disabled = false,
  workspaceId = activeWorkspaceId(),
}: {
  /** Put this text in the composer for the learner to send. */
  onPick: (prompt: string) => void;
  disabled?: boolean;
  workspaceId?: string;
}) {
  const { t } = useTranslation();
  const { value: { chat } } = usePageCustomization();
  const [view, setView] = useState<View>({ kind: "loading" });
  const [open, setOpen] = useState<string | null>(null);
  const panelId = useId();
  const reduced = useReducedMotion();
  const menuRef = useRef<HTMLDivElement>(null);
  useOutsideClick(menuRef, open !== null, () => setOpen(null));
  const refreshRef = useRef<AbortController | null>(null);
  const generationRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(
    async (signal?: AbortSignal): Promise<SuggestionPayload | null> => {
      try {
        const response = await apiFetch(apiUrl(scopedUrl("/api/dashboard/suggestions", workspaceId)), {
          signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(REQUEST_TIMEOUT_MS)]) : AbortSignal.timeout(REQUEST_TIMEOUT_MS),
          cache: "no-store",
        });
        if (!response.ok) return null;
        return (await response.json()) as SuggestionPayload;
      } catch {
        return null;
      }
    },
    [workspaceId],
  );

  useEffect(() => {
    const generation = ++generationRef.current;
    const controller = new AbortController();
    setView({ kind: "loading" });
    const deadline = setTimeout(() => {
      if (generation !== generationRef.current) return;
      controller.abort();
      if (timerRef.current) clearTimeout(timerRef.current);
      setView(current => current.kind === "ready" || current.kind === "idle" ? current : { kind: "idle", note: "error" });
    }, REFRESH_TIMEOUT_MS);
    void (async () => {
      const payload = await load(controller.signal);
      if (controller.signal.aborted || generation !== generationRef.current) return;
      if (payload?.suggestions.length) {
        setView(ready(payload.suggestions));
        return;
      }
      // Nothing yet. If the backend says a set is on its way, wait for it and
      // show that something is happening; otherwise hand over the control.
      if (!payload?.stale || payload.status === "error" || payload.status === "no-material") {
        setView({ kind: "idle", note: payload?.status === "no-material" ? "no-material" : "error" });
        return;
      }
      setView({ kind: "working" });
      let attempt = 0;
      const collect = () => {
        void load(controller.signal).then((next) => {
          if (controller.signal.aborted || generation !== generationRef.current) return;
          if (next?.suggestions.length) {
            setView(ready(next.suggestions));
            return;
          }
          if (next?.stale && next.status !== "error" && next.status !== "no-material" && ++attempt < RESETTLE_ATTEMPTS) {
            timerRef.current = setTimeout(collect, RESETTLE_MS);
            return;
          }
          // Gave it long enough. Stop spinning and let the learner decide.
          setView({ kind: "idle", note: next?.status === "no-material" ? "no-material" : "error" });
        });
      };
      timerRef.current = setTimeout(collect, RESETTLE_MS);
    })();
    return () => {
      controller.abort();
      clearTimeout(deadline);
      refreshRef.current?.abort();
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [load]);

  const generate = useCallback(async () => {
    if (timerRef.current) clearTimeout(timerRef.current);
    const generation = ++generationRef.current;
    refreshRef.current?.abort();
    const controller = new AbortController();
    refreshRef.current = controller;
    setView({ kind: "working" });
    try {
      const response = await apiFetch(
        apiUrl(scopedUrl("/api/dashboard/suggestions/refresh", workspaceId)),
        { method: "POST", signal: AbortSignal.any([controller.signal, AbortSignal.timeout(REFRESH_TIMEOUT_MS)]) },
      );
      if (!response.ok) throw new Error('Suggestion refresh failed');
      const payload = (await response.json()) as SuggestionPayload;
      if (controller.signal.aborted || generation !== generationRef.current) return;
      setView(payload.suggestions.length
        ? ready(payload.suggestions)
        : { kind: "idle", note: payload.status === "no-material" ? "no-material" : "error", asked: true });
    } catch {
      if (!controller.signal.aborted && generation === generationRef.current)
        setView({ kind: "idle", note: "error", asked: true });
    }
  }, [workspaceId]);

  const suggestion = view.kind === "ready" ? view.item : null;
  let advice: ReactNode = null;
  if (view.kind === "working") {
    advice = (
      <span className="dt-starter-advice-status">
        <Loader2 size={12} strokeWidth={1.8} className="animate-spin" />
        {t("Finding what to explore next...")}
      </span>
    );
  } else if (suggestion) {
    advice = (
      // One strip, one hover: the label, the suggestion and another-please
      // read as a single offer rather than three things side by side.
      <div className="dt-starter-advice-chip">
        <Tooltip label={suggestion.prompt} delay={500} className="min-w-0">
          <button
            type="button"
            disabled={disabled}
            onClick={() => onPick(suggestion.prompt)}
            className="dt-starter-advice-main"
          >
            <ExploreNextMark className="shrink-0" />
            <span className="dt-starter-advice-label">{t("navigation.ideasForYou")}</span>
            <span className="dt-starter-advice-text">{suggestion.label}</span>
          </button>
        </Tooltip>
        <Tooltip label={t("Suggest something else")}>
          <button
            type="button"
            aria-label={t("Suggest something else")}
            disabled={disabled}
            onClick={() => void generate()}
            className="dt-starter-advice-more"
          >
            <RefreshCw size={14} strokeWidth={1.2} absoluteStrokeWidth />
          </button>
        </Tooltip>
      </div>
    );
  } else if (view.kind === "idle") {
    // Missing material is only worth saying when the learner asked; a failure
    // always leaves the way to try again.
    advice = (
      <>
        {view.asked && (
          <span role="status" className="dt-starter-advice-status">
            {t(
              view.note === "no-material"
                ? "Not enough history yet — have a conversation first."
                : "Suggestions could not be generated. Please try again.",
            )}
          </span>
        )}
        {view.note !== "no-material" && (
          <button
            type="button"
            onClick={() => void generate()}
            disabled={disabled}
            className="dt-starter-advice-action"
          >
            <ExploreNextMark />
            {t("Suggest what to explore next")}
          </button>
        )}
      </>
    );
  }
  const guides = GUIDES.filter(entry => starterPrompts(chat, entry.id, t).length > 0);
  const guide = guides.find((entry) => entry.id === open);

  return (
    // max-w-[768px] + px-6 mirrors ChatComposer's own empty-state container.
    <div
      className="dt-starters mx-auto w-full max-w-[768px] px-6 pb-6 animate-fade-in"
      onKeyDown={(event) => {
        if (event.key === "Escape" && open) {
          event.stopPropagation();
          setOpen(null);
        }
      }}
    >
      {/* The card floats over what follows instead of pushing it, so opening
          one never moves the composer the page is centred on. */}
      <div ref={menuRef} className="dt-starter-menu">
        <div className="dt-starter-tabs">
          {guides.map((entry) => (
            <button
              key={entry.id}
              type="button"
              aria-expanded={open === entry.id}
              aria-controls={open === entry.id ? panelId : undefined}
              onClick={() => setOpen(open === entry.id ? null : entry.id)}
              className="dt-starter-tab"
            >
              {/* One highlight that glides to the chosen way, not one per chip. */}
              {open === entry.id && (
                <m.span
                  layoutId={`starter-pill-${panelId}`}
                  className="dt-starter-pill"
                  transition={{ duration: reduced ? 0 : 0.2, ease: [0.16, 1, 0.3, 1] }}
                />
              )}
              <entry.icon />
              <span>{t(`starters.${entry.id}`)}</span>
            </button>
          ))}
        </div>
        {guide && (
          <div id={panelId} role="group" aria-label={t(`starters.${guide.id}`)} className="dt-starter-card">
            {/* Keyed so switching ways swaps the rows in place: the card stays,
                only its content changes. */}
            <div key={guide.id} className="dt-starter-card-body">
              {starterPrompts(chat, guide.id, t).map(({ label, prompt }, n) => {
                return (
                  // The whole request shows on hover: what the box will hold.
                  <Tooltip key={n} label={prompt} side="top" as="div" className="dt-starter-item" delay={500}>
                    <button
                      type="button"
                      disabled={disabled}
                      onClick={() => {
                        onPick(prompt);
                        setOpen(null);
                      }}
                      className="dt-starter-row"
                    >
                      <span className="min-w-0 flex-1 truncate">{label}</span>
                      <CornerDownLeft size={14} strokeWidth={1.8} aria-hidden className="dt-starter-enter" />
                    </button>
                  </Tooltip>
                );
              })}
            </div>
          </div>
        )}
      </div>
      {/* Always laid out, so the page does not shift when advice arrives. */}
      <div className="dt-starter-advice">{advice}</div>
    </div>
  );
}
