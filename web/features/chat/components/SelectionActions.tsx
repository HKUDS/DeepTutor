"use client";

/**
 * What a passage selected in a reply can become.
 *
 * Two actions, kept apart because they go to different places: "Add to chat"
 * quotes the passage into the main composer (it rides the next message as an
 * attachment), and "Ask" opens a side chat about it — with Dito unless the
 * learner picks a partner, a partner group, or a connected agent from the
 * menu beside it. Either way the passage arrives as a quote; nothing is sent
 * until the learner writes their question.
 */

import { useEffect, useState } from "react";
import { ChevronDown, MessagesSquare, TextQuote } from "lucide-react";
import { useTranslation } from "react-i18next";
import ResponderList from "@/components/chat/home/ResponderList";
import { DITO, type SideChatResponder } from "@/lib/side-chat";

export interface SelectionAnchor {
  left: number;
  right: number;
  top: number;
  bottom: number;
}

const BAR_WIDTH = 232;
const BAR_HEIGHT = 36;
const MENU_WIDTH = 248;
const MENU_MAX_HEIGHT = 320;
const EDGE = 12;
const GAP = 8;

/** Below the selection's last line, or above it when the bottom is near. */
function place(anchor: SelectionAnchor) {
  const left = Math.max(
    EDGE,
    Math.min(anchor.right - BAR_WIDTH, window.innerWidth - BAR_WIDTH - EDGE),
  );
  const below = anchor.bottom + GAP;
  const fitsBelow =
    below + BAR_HEIGHT + MENU_MAX_HEIGHT <= window.innerHeight - EDGE;
  const top = fitsBelow ? below : Math.max(EDGE, anchor.top - BAR_HEIGHT - GAP);
  return { left, top, menuAbove: !fitsBelow };
}

export default function SelectionActions({
  anchor,
  agents,
  onAddToChat,
  onAsk,
  onDismiss,
}: {
  anchor: SelectionAnchor;
  /** Connected agents (not partners) this account can talk to. */
  agents: { name: string; kind?: string }[];
  onAddToChat: () => void;
  onAsk: (responder: SideChatResponder) => void;
  onDismiss: () => void;
}) {
  const { t } = useTranslation();
  const [menuOpen, setMenuOpen] = useState(false);
  const { left, top, menuAbove } = place(anchor);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.stopPropagation();
      if (menuOpen) setMenuOpen(false);
      else onDismiss();
    };
    document.addEventListener("keydown", onKey, true);
    return () => document.removeEventListener("keydown", onKey, true);
  }, [menuOpen, onDismiss]);

  const segment =
    "inline-flex h-full items-center gap-1.5 px-2.5 text-[12.5px] font-medium transition-colors hover:bg-[color-mix(in_srgb,var(--background)_14%,transparent)] focus-visible:outline-none focus-visible:bg-[color-mix(in_srgb,var(--background)_18%,transparent)]";

  return (
    <div
      role="toolbar"
      aria-label={t("Selected text")}
      // Keep the selection: a press here must not collapse it before the click.
      onPointerDown={(event) => event.preventDefault()}
      className="fixed z-[45]"
      style={{ left, top, width: BAR_WIDTH }}
    >
      <div
        className="flex items-stretch overflow-hidden rounded-xl bg-[var(--foreground)] text-[var(--background)] shadow-lg"
        style={{ height: BAR_HEIGHT }}
      >
        <button
          type="button"
          onClick={onAddToChat}
          className={`${segment} flex-1 justify-center`}
        >
          <TextQuote size={14} strokeWidth={1.8} aria-hidden="true" />
          {t("Add to chat")}
        </button>
        <span
          aria-hidden="true"
          className="my-2 w-px bg-[color-mix(in_srgb,var(--background)_22%,transparent)]"
        />
        <button
          type="button"
          onClick={() => onAsk(DITO)}
          className={`${segment} pr-1.5`}
        >
          <MessagesSquare size={14} strokeWidth={1.8} aria-hidden="true" />
          {t("Ask Dito")}
        </button>
        <button
          type="button"
          aria-label={t("Ask someone else")}
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen((value) => !value)}
          className={`${segment} px-1.5`}
        >
          <ChevronDown
            size={14}
            strokeWidth={1.8}
            aria-hidden="true"
            className={`transition-transform ${menuOpen ? "rotate-180" : ""}`}
          />
        </button>
      </div>

      {menuOpen ? (
        <div
          role="menu"
          className={`absolute right-0 overflow-y-auto rounded-xl border border-[var(--border)] bg-[var(--popover,var(--card))] p-1 text-[var(--foreground)] shadow-lg ${
            menuAbove ? "bottom-full mb-1.5" : "top-full mt-1.5"
          }`}
          style={{ width: MENU_WIDTH, maxHeight: MENU_MAX_HEIGHT }}
        >
          <ResponderList agents={agents} onPick={onAsk} />
        </div>
      ) : null}
    </div>
  );
}
