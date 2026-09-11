"use client";

import dynamic from "next/dynamic";
import { useState } from "react";
import {
  Check,
  Copy,
  CornerUpRight,
  Loader2,
  Users,
  Waypoints,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import PartnerAvatar from "@/components/partners/PartnerAvatar";
import type { PartnerGroupMember } from "@/lib/partner-groups-api";

import { useSeatKindLabel } from "./labels";
import type { Seat } from "./useGroupSession";

const AssistantResponse = dynamic(
  () => import("@/components/common/AssistantResponse"),
  { ssr: false },
);

/**
 * One speaker's block in a round.
 *
 * The same node carries the speaker from "thinking" to "answered": the body
 * accumulates from stream deltas and the authoritative message simply swaps in
 * when it lands. Nothing is inserted or reordered, so a long panel never jumps
 * under the reader.
 *
 * The private reasoning trace is deliberately NOT inline here — with several
 * speakers answering at once it would bury the answers. The status row opens
 * it in the side panel instead.
 */
export default function PartnerSeat({
  seat,
  member,
  onQuote,
  onOpenTrace,
  peers,
  onAskPeer,
}: {
  seat: Seat;
  member?: PartnerGroupMember;
  /** Ask this speaker's block to be quoted into the composer. */
  onQuote?: (member: PartnerGroupMember | undefined, content: string) => void;
  /** Reveal this speaker's private reasoning in the side panel. */
  onOpenTrace?: () => void;
  /** Peers this speaker can be asked to engage with, and the handler. */
  peers?: PartnerGroupMember[];
  onAskPeer?: (targetId: string) => void;
}) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  const [askOpen, setAskOpen] = useState(false);

  const working = seat.status === "waiting" || seat.status === "working";
  const body = seat.message?.content ?? seat.streamed;
  const name = seat.message?.author_name || member?.name || seat.partnerId;
  const isQuestion = seat.message?.kind === "invocation_question";
  const labelFor = useSeatKindLabel();
  // The follow-up round already carries its own header, so the seat inside it
  // does not repeat the word.
  const kindLabel = isQuestion ? "" : labelFor(seat.message?.kind);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(body);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      // Clipboard access can be denied; the button simply does nothing.
    }
  };

  return (
    <div
      className="group/seat flex items-start gap-2.5"
      data-seat={seat.partnerId}
      data-seat-status={seat.status}
    >
      <PartnerAvatar
        name={name}
        emoji={member?.emoji}
        color={member?.color}
        image={member?.avatar}
        size={28}
        className="mt-0.5 shrink-0"
      />
      <div className="min-w-0 flex-1">
        <div className="mb-1 flex items-center gap-2">
          <span className="text-[11.5px] font-medium text-[var(--foreground)]">
            {name}
          </span>
          {kindLabel ? (
            <span className="shrink-0 rounded-full bg-[var(--muted)] px-1.5 py-0.5 text-[9.5px] text-[var(--muted-foreground)]">
              {kindLabel}
            </span>
          ) : null}
          {working ? (
            <span className="inline-flex items-center gap-1 text-[10.5px] text-[var(--muted-foreground)]">
              <Loader2 size={9} className="animate-spin" />
              {seat.status === "waiting" ? t("Waiting…") : t("Thinking…")}
            </span>
          ) : null}
          {onOpenTrace && seat.events.length ? (
            <button
              type="button"
              onClick={onOpenTrace}
              className="inline-flex items-center gap-1 rounded-md px-1 py-0.5 text-[10.5px] text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            >
              <Waypoints size={10} />
              {t("Reasoning steps")}
            </button>
          ) : null}
        </div>

        {seat.status === "error" ? (
          <p className="rounded-xl border border-red-500/25 bg-red-500/[0.04] px-3.5 py-2.5 text-[12px] text-red-500">
            {body || t("This Partner could not answer.")}
          </p>
        ) : body ? (
          <div
            data-seat-body
            className={`rounded-2xl rounded-tl-md border px-4 py-3 ${
              isQuestion
                ? "border-[var(--border)] bg-transparent"
                : "border-[var(--border)] bg-[var(--card)]"
            }`}
          >
            <AssistantResponse content={body} isStreaming={working} />
          </div>
        ) : null}

        {!working && body ? (
          <div className="mt-1 flex flex-wrap items-center gap-1 transition-opacity focus-within:opacity-100 sm:opacity-0 sm:group-hover/seat:opacity-100">
            <button
              type="button"
              onClick={copy}
              title={t("Copy")}
              className="inline-flex h-6 items-center gap-1 rounded-md px-1.5 text-[10.5px] text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            >
              {copied ? <Check size={11} /> : <Copy size={11} />}
              {copied ? t("Copied") : t("Copy")}
            </button>
            {onQuote ? (
              <button
                type="button"
                onClick={() => onQuote(member, body)}
                title={t("Quote this in a reply")}
                className="inline-flex h-6 items-center gap-1 rounded-md px-1.5 text-[10.5px] text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
              >
                <CornerUpRight size={11} />
                {t("Follow up")}
              </button>
            ) : null}
            {onAskPeer && peers && peers.length ? (
              <div className="relative">
                <button
                  type="button"
                  onClick={() => setAskOpen((value) => !value)}
                  className="inline-flex h-6 items-center gap-1 rounded-md px-1.5 text-[10.5px] text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
                >
                  <Users size={11} />
                  {t("Ask a peer")}
                </button>
                {askOpen ? (
                  <div
                    className="absolute bottom-full left-0 z-30 mb-1 w-[210px] overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--popover)] py-1 shadow-xl"
                    onMouseLeave={() => setAskOpen(false)}
                  >
                    <div className="px-2.5 pb-1 pt-0.5 text-[9.5px] text-[var(--muted-foreground)]">
                      {t("Who should respond to {{name}}?", { name })}
                    </div>
                    {peers.map((peer) => (
                      <button
                        key={peer.partner_id}
                        type="button"
                        onClick={() => {
                          setAskOpen(false);
                          onAskPeer(peer.partner_id);
                        }}
                        className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left transition-colors hover:bg-[var(--muted)]"
                      >
                        <PartnerAvatar
                          name={peer.name}
                          emoji={peer.emoji}
                          color={peer.color}
                          image={peer.avatar}
                          size={18}
                        />
                        <span className="truncate text-[11.5px] text-[var(--foreground)]">
                          {peer.name}
                        </span>
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}
