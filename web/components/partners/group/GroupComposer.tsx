"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowUp, AtSign, Square, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import PartnerAvatar from "@/components/partners/PartnerAvatar";
import { shouldSubmitOnEnter } from "@/lib/composer-keyboard";
import { useAutoSizedTextarea } from "@/lib/use-auto-sized-textarea";
import { useImeComposing } from "@/lib/use-ime-composing";
import type { PartnerGroupMember } from "@/lib/partner-groups-api";

import {
  activeMentionQuery,
  completeMention,
  mentionSuggestions,
  resolveMentions,
} from "./mentions";

export interface QuotedSpeech {
  name: string;
  content: string;
}

/**
 * The group composer.
 *
 * Two rules make it feel like a chat box rather than a form: the textarea is
 * never disabled while a round runs (the user can draft their next question
 * during a long panel, and the caret is never stolen), and Enter belongs to
 * the open @suggestion list before it belongs to submit.
 */
export default function GroupComposer({
  members,
  running,
  connected,
  quote,
  onClearQuote,
  onSend,
  onCancel,
}: {
  members: PartnerGroupMember[];
  running: boolean;
  connected: boolean;
  quote: QuotedSpeech | null;
  onClearQuote: () => void;
  onSend: (content: string, mentions: string[] | null) => boolean;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const [input, setInput] = useState("");
  const [highlight, setHighlight] = useState(0);
  const [dismissed, setDismissed] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const { isComposingRef, onCompositionStart, onCompositionEnd } =
    useImeComposing();

  const query = activeMentionQuery(input);
  const suggestions = useMemo(
    () =>
      query === null || dismissed ? [] : mentionSuggestions(query, members),
    [dismissed, members, query],
  );
  const resolved = useMemo(
    () => resolveMentions(input, members),
    [input, members],
  );

  // Grows with the draft instead of scrolling a one-line box. The bounds live
  // here rather than in CSS min-h/max-h, which would fight the inline height.
  useAutoSizedTextarea(textareaRef, input, { min: 24, max: 176 });

  /** Typing owns the suggestion state — deriving it in an effect would make
   *  every keystroke a second render pass. */
  const handleChange = (value: string) => {
    setInput(value);
    setHighlight(0);
    // Escape hides the list for the mention being typed; finishing that
    // mention makes the list relevant again.
    if (activeMentionQuery(value) === null) setDismissed(false);
  };

  useEffect(() => {
    if (quote) textareaRef.current?.focus();
  }, [quote]);

  const pick = (member: PartnerGroupMember) => {
    setInput((current) => completeMention(current, member));
    setDismissed(false);
    requestAnimationFrame(() => textareaRef.current?.focus());
  };

  const submit = () => {
    const draft = input.trim();
    if (!draft || !connected) return;
    // A quoted speech is prepended as markdown so the panel sees exactly what
    // the user is responding to — the group transcript stays self-contained.
    const content = quote
      ? `> ${quote.name}: ${quote.content.replace(/\n+/g, " ").slice(0, 400)}\n\n${draft}`
      : draft;
    const mentions = resolved.everyone
      ? []
      : resolved.targets.length
        ? resolved.targets
        : null;
    if (!onSend(content, mentions)) return;
    setInput("");
    onClearQuote();
  };

  const addressed = resolved.everyone ? [] : resolved.members;

  return (
    <div className="border-t border-[var(--border)] bg-[var(--background)] px-4 py-3 sm:px-8">
      <div className="relative mx-auto max-w-3xl">
        {suggestions.length > 0 ? (
          <div className="absolute bottom-full left-0 z-20 mb-2 w-72 overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--popover)] p-1 shadow-xl">
            {suggestions.map((member, index) => (
              <button
                key={member.partner_id}
                type="button"
                onMouseDown={(event) => event.preventDefault()}
                onMouseEnter={() => setHighlight(index)}
                onClick={() => pick(member)}
                className={`flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left ${
                  index === highlight ? "bg-[var(--muted)]" : ""
                }`}
              >
                <PartnerAvatar
                  name={member.name}
                  emoji={member.emoji}
                  color={member.color}
                  image={member.avatar}
                  size={22}
                />
                <span className="min-w-0 flex-1 truncate text-[12px] text-[var(--foreground)]">
                  {member.name}
                </span>
              </button>
            ))}
          </div>
        ) : null}

        <div className="mb-2 flex min-h-[16px] items-center justify-between gap-3 text-[10.5px] text-[var(--muted-foreground)]">
          <span className="inline-flex min-w-0 items-center gap-1">
            <AtSign size={11} className="shrink-0" />
            <span className="truncate">
              {addressed.length
                ? t("Talking to {{names}}", {
                    names: addressed.map((item) => item.name).join("、"),
                  })
                : t("No mention · everyone will answer")}
            </span>
          </span>
          {resolved.unknown.length ? (
            <span className="shrink-0 text-amber-600 dark:text-amber-500">
              {t("Unrecognized: {{names}}", {
                names: resolved.unknown.map((item) => `@${item}`).join(" "),
              })}
            </span>
          ) : null}
        </div>

        {quote ? (
          <div className="mb-2 flex items-start gap-2 rounded-xl border border-[var(--border)] bg-[var(--muted)]/40 px-3 py-2">
            <div className="min-w-0 flex-1">
              <div className="text-[10px] font-medium text-[var(--muted-foreground)]">
                {t("Following up on {{name}}", { name: quote.name })}
              </div>
              <p className="mt-0.5 line-clamp-2 text-[11px] leading-relaxed text-[var(--foreground)]">
                {quote.content}
              </p>
            </div>
            <button
              type="button"
              onClick={onClearQuote}
              className="mt-0.5 shrink-0 text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
            >
              <X size={13} />
            </button>
          </div>
        ) : null}

        <div className="flex items-end gap-2 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-2 shadow-sm focus-within:border-[var(--ring)]">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(event) => handleChange(event.target.value)}
            onCompositionStart={onCompositionStart}
            onCompositionEnd={onCompositionEnd}
            onKeyDown={(event) => {
              if (suggestions.length) {
                if (event.key === "ArrowDown") {
                  event.preventDefault();
                  setHighlight((value) => (value + 1) % suggestions.length);
                  return;
                }
                if (event.key === "ArrowUp") {
                  event.preventDefault();
                  setHighlight(
                    (value) =>
                      (value - 1 + suggestions.length) % suggestions.length,
                  );
                  return;
                }
                if (event.key === "Escape") {
                  event.preventDefault();
                  setDismissed(true);
                  return;
                }
                // The open list owns Enter; submitting is one Escape away.
                if (
                  event.key === "Enter" &&
                  !event.shiftKey &&
                  !isComposingRef.current
                ) {
                  event.preventDefault();
                  pick(suggestions[highlight] ?? suggestions[0]);
                  return;
                }
              }
              if (shouldSubmitOnEnter(event, isComposingRef.current)) {
                event.preventDefault();
                submit();
              }
            }}
            rows={1}
            placeholder={t("Message the group · type @ to choose Partners")}
            className="flex-1 resize-none bg-transparent px-2 py-2 text-[13px] leading-relaxed text-[var(--foreground)] outline-none placeholder:text-[var(--muted-foreground)]"
          />
          {running ? (
            <button
              type="button"
              onClick={onCancel}
              title={t("Stop")}
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-[var(--border)] text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
            >
              <Square size={11} fill="currentColor" />
            </button>
          ) : (
            <button
              type="button"
              onClick={submit}
              disabled={!input.trim() || !connected}
              title={connected ? t("Send") : t("Connecting…")}
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[var(--primary)] text-[var(--primary-foreground)] transition-opacity disabled:opacity-35"
            >
              <ArrowUp size={15} />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
