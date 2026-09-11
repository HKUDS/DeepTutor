"use client";

import { useState } from "react";
import { ChevronDown } from "lucide-react";
import { useTranslation } from "react-i18next";

import type {
  PartnerGroupMember,
  PartnerInvocation,
} from "@/lib/partner-groups-api";

import InvocationCard from "./InvocationCard";
import RoundSummaryAction from "./RoundSummaryAction";
import PartnerSeat from "./PartnerSeat";
import type { QuotedSpeech } from "./GroupComposer";
import type { Round, Seat } from "./useGroupSession";

interface RoundProps {
  round: Round;
  members: PartnerGroupMember[];
  /** Live completion counter, only for the running round. */
  progress: { done: number; total: number; clash?: boolean } | null;
  pendingActions: Set<string>;
  onApprove: (invocationId: string) => void;
  onReject: (invocationId: string) => void;
  onQuote: (quote: QuotedSpeech) => void;
  /** Reveal one speaker's private reasoning in the side panel. */
  onOpenTrace: (turnId: string, partnerId: string) => void;
  /** Ask another member to respond to this speaker's answer. */
  onAskPeer: (requesterId: string, targetId: string, content: string) => void;
  /** Have one member close this round with consensus / disagreement. */
  onSummarize: (turnId: string, partnerId: string) => void;
}

/**
 * One round of the discussion.
 *
 * A parallel panel is N answers to one question, so the question and its
 * answers are grouped visually instead of being flattened into a stream of
 * unrelated messages. An approved partner-to-partner exchange is a consequence
 * of the round rather than something the user asked for, so it hangs off the
 * round as a collapsible aside.
 */
export default function GroupRound(props: RoundProps) {
  const { round, progress, members, onSummarize } = props;
  const { t } = useTranslation();

  if (round.followup) return <FollowupRound {...props} />;

  // Two or more finished answers is what makes a summary meaningful; one
  // speaker summarising themselves is noise. A round already summarised, or
  // still running, does not offer it again.
  const answered = round.seats.filter(
    (seat) => seat.status === "done" && seat.message?.kind !== "round_summary",
  );
  const summarised = round.seats.some(
    (seat) => seat.message?.kind === "round_summary",
  );
  const canSummarise =
    !round.live && !round.stopped && !summarised && answered.length > 1;

  return (
    <section data-turn-key={round.turnId} className="group/round space-y-4">
      {round.user ? (
        <div className="flex justify-end">
          <div
            data-turn-bubble
            className="max-w-[82%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-[var(--primary)] px-4 py-2.5 text-[13px] leading-relaxed text-[var(--primary-foreground)]"
          >
            {round.user.content}
          </div>
        </div>
      ) : null}

      {round.live && progress && progress.total > 1 ? (
        <div className="flex items-center gap-2 text-[10.5px] text-[var(--muted-foreground)]">
          <span>
            {progress.clash
              ? t("Clash round · {{done}} of {{total}}", progress)
              : t("{{done}} of {{total}} answered", progress)}
          </span>
          <span className="h-px flex-1 bg-[var(--border)]" />
        </div>
      ) : null}

      <SeatList {...props} />

      {canSummarise ? (
        <RoundSummaryAction
          members={members.filter((member) =>
            answered.some((seat) => seat.partnerId === member.partner_id),
          )}
          onSummarize={(partnerId) => onSummarize(round.turnId, partnerId)}
        />
      ) : null}

      {round.stopped ? (
        <div className="flex items-center gap-2 text-[10.5px] text-[var(--muted-foreground)]">
          <span className="h-px flex-1 bg-[var(--border)]" />
          <span>{t("You stopped this round")}</span>
          <span className="h-px flex-1 bg-[var(--border)]" />
        </div>
      ) : null}
    </section>
  );
}

/**
 * The follow-up exchange, collapsible and titled by who asked whom.
 *
 * No invocation card is rendered here: the question already appears as this
 * round's first bubble, and repeating it under the answer was pure duplication.
 */
function FollowupRound(props: RoundProps) {
  const { round, members } = props;
  const { t } = useTranslation();
  const [open, setOpen] = useState(true);

  const invocation = round.seats.find((seat) => seat.message?.invocation)
    ?.message?.invocation;
  const requester =
    invocation?.requester_partner_name ||
    round.seats[0]?.message?.author_name ||
    "";
  const target =
    invocation?.target_partner_name ||
    members.find(
      (member) => member.partner_id === round.seats[0]?.message?.mentions?.[0],
    )?.name ||
    "";

  return (
    // The aside is indented to read as a consequence of the round above, but a
    // narrow viewport needs that width for the prose itself.
    <section data-turn-key={round.turnId} className="ml-2 sm:ml-[38px]">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        data-turn-bubble
        className="group/head flex w-full items-center gap-1.5 rounded py-1 text-left text-[10.5px] text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
      >
        <ChevronDown
          size={12}
          className={`shrink-0 transition-transform ${open ? "" : "-rotate-90"}`}
        />
        <span className="truncate">
          {requester && target
            ? t("{{requester}} asked {{target}}", { requester, target })
            : t("Follow-up discussion")}
        </span>
        <span className="h-px flex-1 bg-[var(--border)]" />
      </button>
      {open ? (
        <div className="mt-2 border-l border-[var(--border)] pl-2.5 sm:pl-4">
          <SeatList {...props} hideInvocations />
        </div>
      ) : null}
    </section>
  );
}

function SeatList({
  round,
  members,
  pendingActions,
  onApprove,
  onReject,
  onQuote,
  onOpenTrace,
  onAskPeer,
  hideInvocations = false,
}: RoundProps & { hideInvocations?: boolean }) {
  const memberOf = (partnerId: string) =>
    members.find((item) => item.partner_id === partnerId);

  return (
    <div className="space-y-5">
      {round.seats.map((seat) => (
        <div key={seat.message?.event_id ?? seat.partnerId}>
          <PartnerSeat
            seat={seat}
            member={memberOf(seat.partnerId)}
            onOpenTrace={() => onOpenTrace(round.turnId, seat.partnerId)}
            peers={
              // A summary closes the round; inviting a reply to it would
              // reopen what it just closed.
              seat.status === "done" &&
              !round.followup &&
              seat.message?.kind !== "round_summary"
                ? members.filter((item) => item.partner_id !== seat.partnerId)
                : undefined
            }
            onAskPeer={(targetId) =>
              onAskPeer(
                seat.partnerId,
                targetId,
                seat.message?.content ?? seat.streamed,
              )
            }
            onQuote={
              seat.status === "done"
                ? (member, content) =>
                    onQuote({
                      name:
                        member?.name ||
                        seat.message?.author_name ||
                        seat.partnerId,
                      content,
                    })
                : undefined
            }
          />
          {!hideInvocations &&
          seat.message?.invocation &&
          seat.message.invocation.status !== "completed" ? (
            <div className="mt-1 sm:pl-[38px]">
              <InvocationCard
                invocation={seat.message.invocation}
                busy={pendingActions.has(seat.message.invocation.invocation_id)}
                showQuestion={questionNeedsEcho(seat.message.invocation)}
                onApprove={() =>
                  onApprove(seat.message!.invocation!.invocation_id)
                }
                onReject={() =>
                  onReject(seat.message!.invocation!.invocation_id)
                }
              />
            </div>
          ) : null}
        </div>
      ))}
    </div>
  );
}

/**
 * Whether the card must carry the question text itself.
 *
 * Once approved, the question is published as its own bubble in the follow-up
 * round, so echoing it here would show the same paragraph twice. It is only
 * shown while the decision is open, or when the exchange never happened.
 *
 * A ``completed`` invocation is not rendered at all (see the call site): the
 * follow-up round's own header already says who asked whom.
 */
function questionNeedsEcho(invocation: PartnerInvocation): boolean {
  return invocation.status === "pending" || invocation.status === "rejected";
}

export type { Seat };
