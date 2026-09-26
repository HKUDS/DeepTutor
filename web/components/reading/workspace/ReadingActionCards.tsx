"use client";

import { useEffect, useRef, useState } from "react";
import {
  CircleAlert,
  Loader2,
  MessageSquareQuote,
  RotateCcw,
  Sparkles,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { ExtensionResult } from "@/components/reading/ReadingExtensionBar";
import {
  useReadingActions,
  type ReadingActionCard,
} from "@/components/reading/reading-actions-context";

/**
 * Where a reading action's answer lands: under the conversation, in the same
 * column the learner already reads answers in.
 *
 * A card is not a chat message — nothing here is sent to the model or kept
 * with the conversation — so it looks like a note pinned under the thread,
 * with the passage it answers quoted at the top and a way to carry the
 * question into the conversation proper.
 */
export function ReadingActionCards({
  sessionId,
  onFollowUp,
}: {
  sessionId?: string | null;
  /** Take the card's passage into the composer as the next question's context. */
  onFollowUp: (card: ReadingActionCard) => void;
}) {
  const shared = useReadingActions();
  if (!shared || shared.cards.length === 0) return null;
  return (
    <div className="mt-4 space-y-3 first:mt-0">
      {shared.cards.map((card) => (
        <ActionCard
          key={card.id}
          card={card}
          sessionId={sessionId}
          onDismiss={() => shared.dismiss(card.id)}
          onRetry={() => {
            const entry = shared.actions.find((row) => row.key === card.key);
            if (!entry) return;
            shared.dismiss(card.id);
            void shared.run(entry, {
              locator: card.locator,
              selection: card.quote,
            });
          }}
          onFollowUp={() => onFollowUp(card)}
        />
      ))}
    </div>
  );
}

function ActionCard({
  card,
  sessionId,
  onDismiss,
  onRetry,
  onFollowUp,
}: {
  card: ReadingActionCard;
  sessionId?: string | null;
  onDismiss: () => void;
  onRetry: () => void;
  onFollowUp: () => void;
}) {
  const { t } = useTranslation();
  const ref = useRef<HTMLElement | null>(null);
  // Quiz answers are saved from inside the card; a failed save belongs to the
  // card it happened in, not to a banner somewhere else on the page.
  const [innerError, setInnerError] = useState("");

  // Brought into view when it appears and again when its answer arrives: the
  // learner pressed a button in the document, and the result is in another
  // column that may be scrolled far up a long conversation.
  useEffect(() => {
    ref.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [card.status]);

  const title = card.result?.title || card.label;
  return (
    <article
      ref={ref}
      data-reading-action-card={card.status}
      className="overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--background)]"
    >
      <header className="flex items-center gap-2 px-3 pb-1 pt-2.5">
        <Sparkles size={12} className="shrink-0 text-[var(--primary)]" />
        <h3 className="min-w-0 flex-1 truncate text-[12px] font-semibold text-[var(--foreground)]">
          {title}
        </h3>
        <button
          type="button"
          onClick={onDismiss}
          aria-label={t("Dismiss")}
          title={t("Dismiss")}
          className="inline-flex size-6 shrink-0 items-center justify-center rounded-md text-[var(--muted-foreground)] transition hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
        >
          <X size={12} />
        </button>
      </header>
      {card.quote ? (
        <blockquote className="mx-3 mt-1 line-clamp-3 border-l-2 border-[var(--primary)] pl-2.5 text-[11.5px] leading-relaxed text-[var(--muted-foreground)]">
          {card.quote}
        </blockquote>
      ) : null}
      <div className="px-3 pb-3 pt-2.5">
        {card.status === "running" ? (
          <div role="status" className="space-y-2">
            <p className="flex items-center gap-1.5 text-[11.5px] text-[var(--muted-foreground)]">
              <Loader2 size={12} className="animate-spin" />
              {t("Working on it…")}
            </p>
            <div className="h-2 w-11/12 animate-pulse rounded bg-[var(--muted)]" />
            <div className="h-2 w-8/12 animate-pulse rounded bg-[var(--muted)]" />
          </div>
        ) : card.status === "error" ? (
          <div className="flex items-start gap-2 text-[12px] text-[var(--destructive)]">
            <CircleAlert size={13} className="mt-0.5 shrink-0" />
            <p className="min-w-0 flex-1 break-words">{card.error}</p>
          </div>
        ) : card.result ? (
          <ExtensionResult
            variant="card"
            result={card.result}
            materialId={card.materialId}
            locator={card.locator}
            sessionId={sessionId}
            closeLabel={t("Dismiss")}
            onClose={onDismiss}
            onError={setInnerError}
          />
        ) : null}
        {innerError ? (
          <p className="mt-2 text-[11.5px] text-[var(--destructive)]">
            {innerError}
          </p>
        ) : null}
      </div>
      {card.status !== "running" ? (
        <footer className="flex items-center gap-1 border-t border-[var(--border)] px-2 py-1.5">
          {card.status === "error" ? (
            <CardButton icon={RotateCcw} label={t("Try again")} onClick={onRetry} />
          ) : null}
          <CardButton
            icon={MessageSquareQuote}
            label={t("Ask a follow-up")}
            onClick={onFollowUp}
          />
        </footer>
      ) : null}
    </article>
  );
}

function CardButton({
  icon: Icon,
  label,
  onClick,
}: {
  icon: typeof X;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex h-7 items-center gap-1.5 rounded-md px-2 text-[11.5px] font-medium text-[var(--muted-foreground)] transition hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
    >
      <Icon size={12} />
      {label}
    </button>
  );
}
