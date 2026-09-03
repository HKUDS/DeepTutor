"use client";

import { memo, useState } from "react";
import { useRouter } from "next/navigation";
import { GraduationCap, RotateCcw, Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";

import { ActivityMark } from "@/components/activity";
import { formatRelative } from "@/components/space/learning/format";
import {
  masteryHandoffHref,
  type MasteryHandoffPayload,
} from "@/lib/mastery-handoff";
import { setPendingPrompt } from "@/lib/pending-prompt";

/**
 * The card chat uses to hand the learner into a mastery study session.
 *
 * Chat can find the learner's topics and lessons but has no map, no outline
 * and no gate, so the answer to "take me back through lesson one" is a
 * doorway, not a lesson. This is that doorway: the destination, the reason,
 * and the opening message all visible before anything happens.
 *
 * Three decisions worth keeping:
 *
 * **The opening line is editable.** It is the assistant's proposal for how to
 * start, not an instruction. A learner who wants to arrive asking something
 * slightly different should not have to arrive, clear the box, and retype.
 *
 * **Nothing navigates on its own.** Taking the card is the only thing that
 * moves the page.
 *
 * **The progress belongs to the topic, not to the card.** Showing where the
 * path actually stands is what makes a hand-off legible: "review lesson 1" of
 * a course that is 9/12 mastered is a different offer from the same words on
 * a course barely begun.
 *
 * Mirrors `deeptutor/tools/mastery_nav.py`; the payload is read by
 * `extractMasteryHandoffs` in `lib/mastery-handoff.ts`.
 */

/**
 * The topic's mark: its own emoji when it has one, the path glyph otherwise.
 *
 * The ring and the soft inner wash are deliberately the same vocabulary the
 * thought-orbs use — a round, low-contrast mark that reads as part of the
 * product's own surface rather than as an icon dropped onto a chat bubble.
 */
function TopicSigil({ emoji, kind }: { emoji: string; kind: string }) {
  const Glyph = kind === "new" ? Sparkles : GraduationCap;
  return (
    <span
      aria-hidden
      className="relative flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-[color-mix(in_srgb,var(--primary)_22%,transparent)] bg-[radial-gradient(circle_at_30%_25%,color-mix(in_srgb,var(--primary)_14%,transparent),transparent_70%)] text-[15px] leading-none"
    >
      {emoji ? (
        <span className="translate-y-[0.5px]">{emoji}</span>
      ) : (
        <Glyph size={15} strokeWidth={1.7} className="text-[var(--primary)]" />
      )}
    </span>
  );
}

/**
 * How much of the path is cleared: a short bar, beside the number it draws.
 *
 * Mastery is a per-objective gate, so the honest figure is "9 of 12 cleared",
 * never an average. The bar is that same fact drawn, and it is deliberately
 * short and adjacent rather than spanning the card — a full-width bar over a
 * hand-off reads as a progress *indicator* for the card itself, as though
 * something were loading.
 */
function PathProgress({
  mastered,
  objectives,
}: {
  mastered: number;
  objectives: number;
}) {
  if (objectives <= 0) return null;
  const share = Math.max(0, Math.min(1, mastered / objectives));
  return (
    <span
      aria-hidden
      className="inline-block h-[3px] w-11 shrink-0 overflow-hidden rounded-full bg-[color-mix(in_srgb,var(--foreground)_12%,transparent)]"
    >
      <span
        className="block h-full rounded-full bg-[var(--primary)] transition-[width] duration-500 ease-out"
        style={{ width: `${Math.round(share * 100)}%` }}
      />
    </span>
  );
}

const MasteryHandoff = memo(function MasteryHandoff({
  data,
}: {
  data: MasteryHandoffPayload;
}) {
  const { t, i18n } = useTranslation();
  const zh = Boolean(i18n.language?.toLowerCase().startsWith("zh"));
  const router = useRouter();
  const [draft, setDraft] = useState(data.opening_message);

  const resuming = data.kind === "open";
  const headline =
    data.reason ||
    (resuming
      ? t("Pick this back up where you left it")
      : t("Start a fresh session on this path"));

  const go = () => {
    const opening = draft.trim();
    // Scoped to the mastery surface and consumed once, so an offer the
    // learner declined never resurfaces in whichever screen they open next.
    if (opening) setPendingPrompt(opening, "mastery_path");
    router.push(masteryHandoffHref(data));
  };

  const stats = [
    data.objectives > 0
      ? `${data.mastered}/${data.objectives} ${t("mastered")}`
      : "",
    data.due_reviews > 0
      ? `${data.due_reviews} ${t("due for review")}`
      : "",
  ].filter(Boolean);

  return (
    <div className="mt-3 overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-[0_1px_2px_rgba(0,0,0,0.04),0_4px_14px_rgba(0,0,0,0.04)]">
      <div className="flex items-start gap-3 p-4">
        <TopicSigil emoji={data.emoji} kind={data.kind} />
        <div className="min-w-0 flex-1">
          <div className="text-[13px] font-medium leading-snug text-[var(--foreground)]">
            {headline}
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[11px] leading-relaxed text-[var(--muted-foreground)]">
            <span className="truncate">
              {data.path_name || t("Mastery Path")}
            </span>
            {data.module_name ? (
              <>
                <span aria-hidden>·</span>
                {/* The lesson is the whole point of a request like "review
                    lesson one", so it is a chip rather than more grey prose. */}
                <span className="rounded-full bg-[color-mix(in_srgb,var(--primary)_10%,transparent)] px-1.5 py-[1px] text-[10.5px] font-medium text-[color-mix(in_srgb,var(--primary)_75%,var(--foreground))]">
                  {data.module_name}
                </span>
              </>
            ) : null}
          </div>
          {stats.length ? (
            <div className="mt-1.5 flex items-center gap-1.5 text-[11px] text-[var(--muted-foreground)]">
              <PathProgress
                mastered={data.mastered}
                objectives={data.objectives}
              />
              <span>{stats.join(" · ")}</span>
            </div>
          ) : null}

          {draft || data.opening_message ? (
            <label className="mt-3 block">
              <span className="text-[10.5px] text-[color-mix(in_srgb,var(--muted-foreground)_80%,transparent)]">
                {t("Opens with")}
              </span>
              <textarea
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                rows={2}
                className="mt-1 w-full resize-none rounded-xl border border-[var(--border)] bg-[var(--background)] px-2.5 py-2 text-[12px] leading-relaxed text-[var(--foreground)] outline-none transition-colors focus:border-[var(--ring)]"
              />
            </label>
          ) : null}

          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={go}
              className="inline-flex items-center gap-1.5 rounded-full bg-[var(--primary)] px-3 py-1.5 text-[11.5px] font-medium text-[var(--primary-foreground)] transition hover:opacity-90"
            >
              {resuming ? (
                <RotateCcw size={12} strokeWidth={2} />
              ) : (
                <Sparkles size={12} strokeWidth={2} />
              )}
              {resuming ? t("Continue this session") : t("Begin a session")}
            </button>
            {resuming ? (
              <span className="flex min-w-0 items-center gap-1.5 text-[11px] text-[var(--muted-foreground)]">
                {/* The same mark the sidebar and the trace use, so "there is a
                    question waiting in there" reads the same everywhere. */}
                <ActivityMark
                  state={
                    data.session_running
                      ? "running"
                      : data.session_awaiting
                        ? "awaiting"
                        : "done"
                  }
                  size={11}
                />
                <span className="truncate">
                  {data.session_title || t("Untitled session")}
                </span>
                {data.session_awaiting ? (
                  <span className="shrink-0 text-[var(--warning)]">
                    {t("a question is waiting")}
                  </span>
                ) : data.session_updated_at > 0 ? (
                  <span className="shrink-0">
                    {formatRelative(data.session_updated_at, zh)}
                  </span>
                ) : null}
              </span>
            ) : (
              <span className="text-[11px] text-[var(--muted-foreground)]">
                {t("The path keeps all of its progress")}
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
});
MasteryHandoff.displayName = "MasteryHandoff";

export const MasteryHandoffCards = memo(function MasteryHandoffCards({
  handoffs,
}: {
  handoffs: MasteryHandoffPayload[];
}) {
  if (handoffs.length === 0) return null;
  return (
    <>
      {handoffs.map((handoff) => (
        <MasteryHandoff
          key={`${handoff.kind}:${handoff.path_id}:${handoff.session_id}:${handoff.module_id}`}
          data={handoff}
        />
      ))}
    </>
  );
});
MasteryHandoffCards.displayName = "MasteryHandoffCards";
