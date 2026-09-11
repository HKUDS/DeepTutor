"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertCircle, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useChatAutoScroll } from "@/hooks/useChatAutoScroll";
import { TurnNavigator } from "@/components/chat/home/TurnNavigator";
import {
  getPartnerGroupWhiteboard,
  type PartnerGroup,
  type WhiteboardEntry,
} from "@/lib/partner-groups-api";

import GroupSidePanel, {
  type PanelTab,
  type TraceFocus,
} from "./GroupSidePanel";
import GroupComposer, { type QuotedSpeech } from "./GroupComposer";
import GroupEmptyState from "./GroupEmptyState";
import GroupRound from "./GroupRound";
import { buildGroupOutline } from "./outline";
import { useGroupSession } from "./useGroupSession";

/**
 * The group discussion surface.
 *
 * This component only wires things together: session state lives in
 * ``useGroupSession``, a round renders itself, and the composer owns mention
 * resolution. Keeping the shell thin is what makes the round/seat model
 * readable — the interesting logic is not buried in JSX.
 */
export default function PartnerGroupChat({
  group,
  sessionKey,
  panelOpen,
  onOpenPanel,
  onClosePanel,
}: {
  group: PartnerGroup;
  /** Which discussion thread is open; owned by the page header's picker. */
  sessionKey: string;
  /** Open state is owned by the page header, which holds the toggle. */
  panelOpen: boolean;
  onOpenPanel: () => void;
  onClosePanel: () => void;
}) {
  const { t } = useTranslation();
  const [quote, setQuote] = useState<QuotedSpeech | null>(null);
  const [board, setBoard] = useState<WhiteboardEntry[]>([]);
  const [panelTab, setPanelTab] = useState<PanelTab>("reasoning");
  const [traceFocus, setTraceFocus] = useState<TraceFocus | null>(null);

  const {
    rounds,
    running,
    progress,
    connected,
    loading,
    error,
    setError,
    pendingActions,
    send,
    actOnInvocation,
    askPeer,
    summarizeRound,
    cancel,
  } = useGroupSession(group, sessionKey);

  const lastSeat = rounds[rounds.length - 1]?.seats.slice(-1)[0];
  const seatCount = useMemo(
    () => rounds.reduce((total, round) => total + round.seats.length, 0),
    [rounds],
  );
  const eventCount = useMemo(
    () =>
      rounds.reduce(
        (total, round) =>
          total +
          round.seats.reduce((sum, seat) => sum + seat.events.length, 0),
        0,
      ),
    [rounds],
  );
  const outline = useMemo(() => buildGroupOutline(rounds), [rounds]);
  const { containerRef, handleScroll, scrollToBottom } = useChatAutoScroll({
    hasMessages: rounds.length > 0,
    isStreaming: running,
    composerHeight: 0,
    messageCount: seatCount,
    lastMessageContent: lastSeat?.message?.content ?? lastSeat?.streamed,
    lastEventCount: eventCount,
  });

  /** Scroll a round into view and flash it, mirroring product chat. */
  const jumpToRound = useCallback(
    (key: string) => {
      const container = containerRef.current;
      const target = container?.querySelector<HTMLElement>(
        `[data-turn-key="${key}"]`,
      );
      if (!container || !target) return;
      const offset =
        target.getBoundingClientRect().top -
        container.getBoundingClientRect().top;
      container.scrollTo({
        top: container.scrollTop + offset - 24,
        behavior: "smooth",
      });
      const bubble =
        target.querySelector<HTMLElement>("[data-turn-bubble]") ?? target;
      bubble.classList.remove("turn-flash");
      // Reflow so the animation restarts when the same tick is clicked twice.
      void bubble.offsetWidth;
      bubble.classList.add("turn-flash");
    },
    [containerRef],
  );

  /**
   * Hand one speaker's point to a peer.
   *
   * Phrased in the requester's own voice because the backend publishes it as
   * "<requester> asks you directly in the Group: …" — and kept short so the
   * quoted excerpt does not crowd out the actual question.
   */
  const handleAskPeer = useCallback(
    (requesterId: string, targetId: string, content: string) => {
      const excerpt = content.trim().slice(0, 400);
      const question = t(
        "Here is the point I just made: “{{excerpt}}”. What is your take on it?",
        { excerpt },
      );
      const ok = askPeer(requesterId, targetId, question);
      if (!ok) setError(t("Group is reconnecting"));
      return ok;
    },
    [askPeer, setError, t],
  );

  const refreshBoard = useCallback(() => {
    void getPartnerGroupWhiteboard(group.group_id)
      .then(setBoard)
      .catch(() => setBoard([]));
  }, [group.group_id]);

  useEffect(() => {
    if (panelOpen && panelTab === "context") refreshBoard();
  }, [panelOpen, panelTab, refreshBoard, running]);

  const openTrace = useCallback(
    (turnId: string, partnerId: string) => {
      setPanelTab("reasoning");
      setTraceFocus({ turnId, partnerId });
      onOpenPanel();
    },
    [onOpenPanel],
  );

  return (
    <div className="relative flex min-h-0 flex-1 overflow-hidden">
      <div className="flex min-w-0 flex-1 flex-col">
        {/* The rail is an absolutely-positioned sibling of the scrollport, so
            the two share this wrapper and nothing else lives in it. */}
        <div className="relative flex min-h-0 flex-1 flex-col">
          <div
            ref={containerRef}
            onScroll={handleScroll}
            className="min-h-0 flex-1 overflow-y-auto px-4 py-6 sm:px-8"
          >
            <div className="mx-auto max-w-3xl space-y-7" data-chat-column>
              {loading ? (
                <div className="flex min-h-[320px] items-center justify-center">
                  <Loader2 className="h-4 w-4 animate-spin text-[var(--muted-foreground)]" />
                </div>
              ) : rounds.length === 0 ? (
                <GroupEmptyState
                  members={group.members}
                  mode={group.discussion_mode}
                />
              ) : (
                rounds.map((round) => (
                  <GroupRound
                    key={round.turnId}
                    round={round}
                    members={group.members}
                    progress={round.live ? progress : null}
                    pendingActions={pendingActions}
                    onApprove={(id) => actOnInvocation(id, "approve")}
                    onReject={(id) => actOnInvocation(id, "reject")}
                    onQuote={setQuote}
                    onOpenTrace={openTrace}
                    onAskPeer={handleAskPeer}
                    onSummarize={summarizeRound}
                  />
                ))
              )}
              {error ? (
                // The raw backend reason is kept — it is what makes a failure
                // diagnosable — but it is framed so the user knows what it means.
                <div className="flex items-start gap-2 rounded-xl border border-red-500/25 bg-red-500/[0.04] px-3.5 py-2.5">
                  <AlertCircle
                    size={13}
                    className="mt-0.5 shrink-0 text-red-500"
                  />
                  <div className="min-w-0">
                    <p className="text-[11.5px] font-medium text-red-500">
                      {t("This round could not finish")}
                    </p>
                    <p className="mt-0.5 break-words text-[11px] leading-relaxed text-[var(--muted-foreground)]">
                      {error}
                    </p>
                  </div>
                </div>
              ) : null}
            </div>
          </div>

          <TurnNavigator
            entries={outline}
            scrollRootRef={containerRef}
            onJump={jumpToRound}
            onJumpToBottom={() => scrollToBottom("smooth")}
          />
        </div>

        <GroupComposer
          members={group.members}
          running={running}
          connected={connected}
          quote={quote}
          onClearQuote={() => setQuote(null)}
          onSend={(content, mentions) => {
            const ok = send(content, mentions);
            if (!ok) setError(t("Group is reconnecting"));
            else setError("");
            return ok;
          }}
          onCancel={cancel}
        />
      </div>

      <GroupSidePanel
        open={panelOpen}
        tab={panelTab}
        focus={traceFocus}
        rounds={rounds}
        members={group.members}
        entries={board}
        onTabChange={setPanelTab}
        onClose={onClosePanel}
      />
    </div>
  );
}
