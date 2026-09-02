"use client";

import { useEffect, useMemo, useRef } from "react";
import { X } from "lucide-react";
import { useTranslation } from "react-i18next";

import PartnerAvatar from "@/components/partners/PartnerAvatar";
import { AssistantActivity } from "@/features/chat/trace";
import type {
  PartnerGroupMember,
  WhiteboardEntry,
} from "@/lib/partner-groups-api";

import { useSeatKindLabel } from "./labels";
import type { Round } from "./useGroupSession";

export type PanelTab = "reasoning" | "context";

/** Which speaker's trace the panel should reveal, if any. */
export interface TraceFocus {
  turnId: string;
  partnerId: string;
}

/**
 * The group's side panel: how they thought, and what they all know.
 *
 * Reasoning traces are private to each speaker and only the group owner sees
 * them, so they do not belong in the public transcript column — with a
 * parallel panel of four, four inline trace blocks would push the answers
 * themselves off screen. They live here instead, and a seat's status row
 * opens this panel focused on that speaker.
 */
export default function GroupSidePanel({
  open,
  tab,
  focus,
  rounds,
  members,
  entries,
  onTabChange,
  onClose,
}: {
  open: boolean;
  tab: PanelTab;
  focus: TraceFocus | null;
  rounds: Round[];
  members: PartnerGroupMember[];
  entries: WhiteboardEntry[];
  onTabChange: (tab: PanelTab) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const labelFor = useSeatKindLabel();
  const scrollRef = useRef<HTMLDivElement | null>(null);

  // Reveal the requested speaker once the panel is actually mounted.
  useEffect(() => {
    if (!open || tab !== "reasoning" || !focus) return;
    const root = scrollRef.current;
    const target = root?.querySelector<HTMLElement>(
      `[data-trace="${focus.turnId}:${focus.partnerId}"]`,
    );
    if (!root || !target) return;
    root.scrollTo({
      top:
        root.scrollTop +
        target.getBoundingClientRect().top -
        root.getBoundingClientRect().top -
        8,
      behavior: "smooth",
    });
  }, [open, tab, focus]);

  // Recomputed only when the rounds change: a live turn re-renders this panel
  // many times a second as deltas arrive.
  const traced = useMemo(
    () =>
      rounds
        .flatMap((round) => round.seats.map((seat) => ({ round, seat })))
        .filter(
          ({ seat }) => seat.events.length > 0 || seat.status === "working",
        ),
    [rounds],
  );

  if (!open) return null;

  return (
    <aside
      data-group-panel
      className="absolute inset-y-0 right-0 z-30 flex w-[min(380px,88vw)] flex-col border-l border-[var(--border)] bg-[var(--background)] shadow-xl lg:static lg:w-[360px] lg:shadow-none"
    >
      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-[var(--border)] px-3 py-2">
        <div className="flex items-center gap-1">
          <TabButton
            active={tab === "reasoning"}
            onClick={() => onTabChange("reasoning")}
          >
            {t("Reasoning steps")}
          </TabButton>
          <TabButton
            active={tab === "context"}
            onClick={() => onTabChange("context")}
          >
            {t("Shared context")}
          </TabButton>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label={t("Close")}
          className="shrink-0 text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
        >
          <X size={15} />
        </button>
      </div>

      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto p-3">
        {tab === "reasoning" ? (
          traced.length === 0 ? (
            <Empty>{t("No reasoning to show yet")}</Empty>
          ) : (
            <div className="space-y-2.5">
              {traced.map(({ round, seat }) => {
                const member = members.find(
                  (item) => item.partner_id === seat.partnerId,
                );
                const name =
                  seat.message?.author_name || member?.name || seat.partnerId;
                const focused =
                  focus?.turnId === round.turnId &&
                  focus?.partnerId === seat.partnerId;
                return (
                  <div
                    key={`${round.turnId}:${seat.partnerId}`}
                    data-trace={`${round.turnId}:${seat.partnerId}`}
                    className={`rounded-xl border p-2.5 transition-colors ${
                      focused
                        ? "border-[var(--ring)] bg-[var(--muted)]/30"
                        : "border-[var(--border)]"
                    }`}
                  >
                    <div className="mb-1.5 flex items-center gap-1.5">
                      <PartnerAvatar
                        name={name}
                        emoji={member?.emoji}
                        color={member?.color}
                        image={member?.avatar}
                        size={18}
                      />
                      <span className="truncate text-[11px] font-medium text-[var(--foreground)]">
                        {name}
                      </span>
                      {(() => {
                        const label = round.followup
                          ? t("Follow-up")
                          : labelFor(seat.message?.kind);
                        return label ? (
                          <span className="shrink-0 text-[9.5px] text-[var(--muted-foreground)]">
                            {label}
                          </span>
                        ) : null;
                      })()}
                    </div>
                    <AssistantActivity
                      events={seat.events}
                      isStreaming={seat.status === "working"}
                      content={seat.message?.content ?? seat.streamed}
                      agentName={name}
                      showMark={false}
                      headerClassName="min-h-[20px]"
                    />
                  </div>
                );
              })}
            </div>
          )
        ) : entries.length === 0 ? (
          <Empty>{t("Nothing shared yet")}</Empty>
        ) : (
          <div className="space-y-2">
            <p className="px-0.5 pb-1 text-[10px] leading-relaxed text-[var(--muted-foreground)]">
              {t("Visible to every Partner in this group")}
            </p>
            {entries.map((entry) => (
              <div
                key={entry.entry_id}
                className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-3"
              >
                <p className="whitespace-pre-wrap text-[11px] leading-relaxed text-[var(--foreground)]">
                  {entry.content}
                </p>
              </div>
            ))}
          </div>
        )}
      </div>
    </aside>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-lg px-2.5 py-1.5 text-[11.5px] font-medium transition-colors ${
        active
          ? "bg-[var(--muted)] text-[var(--foreground)]"
          : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
      }`}
    >
      {children}
    </button>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <p className="py-10 text-center text-[11px] text-[var(--muted-foreground)]">
      {children}
    </p>
  );
}
