"use client";

import { Fragment, memo, useEffect, useRef, useState } from "react";
import {
  BookOpen,
  Bot,
  ChevronRight,
  Database,
  Paperclip,
  UserRound,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { SPACE_ITEMS } from "@/lib/space-items";
import { setPickerOrigin } from "@/lib/picker-origin";

type SelectableSpaceKey =
  | "attach"
  | "knowledge"
  | "chat_history"
  | "my_agents"
  | "books"
  | "notebooks"
  | "question_bank"
  | "persona"
  | "memory";

export interface ChatSpaceSelectionCounts {
  attachments: number;
  knowledge: number;
  chatHistory: number;
  myAgents: number;
  books: number;
  notebooks: number;
  questionBank: number;
  persona: number;
  memory: number;
}

interface ChatSpaceMenuProps {
  variant: "toolbar" | "mention";
  selectedCounts: ChatSpaceSelectionCounts;
  /** Hide the Knowledge entry when no knowledge bases are configured. */
  knowledgeAvailable?: boolean;
  /**
   * Hide the Persona entry. The main chat sets this to false — its
   * persona lives in the standalone toolbar selector (and `/persona`),
   * not in this menu. The quiz follow-up keeps the entry: this menu is
   * its only persona entry point.
   */
  personaAvailable?: boolean;
  /** Hide the My Agents entry (e.g. the quiz follow-up surface). */
  agentsAvailable?: boolean;
  onSelectItem: (key: SelectableSpaceKey) => void;
}

const ITEM_ORDER: SelectableSpaceKey[] = [
  "attach",
  "knowledge",
  "chat_history",
  "my_agents",
  "books",
  "notebooks",
  "question_bank",
  "persona",
  "memory",
];

function countFor(
  key: SelectableSpaceKey,
  counts: ChatSpaceSelectionCounts,
): number {
  switch (key) {
    case "attach":
      return counts.attachments;
    case "knowledge":
      return counts.knowledge;
    case "chat_history":
      return counts.chatHistory;
    case "my_agents":
      return counts.myAgents;
    case "books":
      return counts.books;
    case "notebooks":
      return counts.notebooks;
    case "question_bank":
      return counts.questionBank;
    case "persona":
      return counts.persona;
    case "memory":
      return counts.memory;
    default:
      return 0;
  }
}

export default memo(function ChatSpaceMenu({
  variant,
  selectedCounts,
  knowledgeAvailable = true,
  personaAvailable = true,
  agentsAvailable = true,
  onSelectItem,
}: ChatSpaceMenuProps) {
  const { t } = useTranslation();
  const compact = variant === "toolbar";
  const isMention = variant === "mention";

  // Render the items in a fixed, hand-tuned order so the menu always reads
  // the same regardless of how SPACE_ITEMS may be reordered for navigation.
  const items = ITEM_ORDER.filter((key) => {
    if (key === "knowledge") return knowledgeAvailable;
    if (key === "persona") return personaAvailable;
    if (key === "my_agents") return agentsAvailable;
    return true;
  })
    .map((key) => {
      // The first two entries are composer-only concepts (not Space pages),
      // so they are defined here rather than in SPACE_ITEMS.
      if (key === "attach") {
        return {
          key,
          label: "Attach files",
          description: "Upload images, Office docs, code & text.",
          icon: Paperclip,
        };
      }
      if (key === "knowledge") {
        return {
          key,
          label: "Knowledge",
          description: "Search the selected knowledge bases.",
          icon: Database,
        };
      }
      if (key === "my_agents") {
        return {
          key,
          label: "My Agents",
          description: "Reference imported Claude Code / Codex conversations.",
          icon: Bot,
        };
      }
      if (key === "books") {
        return {
          key,
          label: "Books",
          description: "Reference generated book chapters in chat.",
          icon: BookOpen,
        };
      }
      if (key === "persona") {
        return {
          key,
          label: "Persona",
          description: "Apply a behavior persona for this turn.",
          icon: UserRound,
        };
      }
      return SPACE_ITEMS.find((it) => it.key === key)!;
    })
    .filter(Boolean);

  // Active row index for keyboard navigation. Only meaningful in the
  // mention variant — the toolbar variant is mouse/click driven.
  const [activeIdx, setActiveIdx] = useState(0);
  // The keydown handler closes over `activeIdx`/`items`/`onSelectItem`;
  // stash them in refs so the document-level listener identity stays
  // stable and we don't re-attach it on every render. Refs are synced
  // in an effect (not during render) to satisfy `react-hooks/refs`.
  const activeIdxRef = useRef(activeIdx);
  const itemsRef = useRef(items);
  const onSelectItemRef = useRef(onSelectItem);
  useEffect(() => {
    activeIdxRef.current = activeIdx;
  }, [activeIdx]);
  useEffect(() => {
    itemsRef.current = items;
  }, [items]);
  useEffect(() => {
    onSelectItemRef.current = onSelectItem;
  }, [onSelectItem]);

  // Reset to the top whenever the menu first mounts (i.e. user typed `@`
  // and the popup appeared). The parent unmounts/remounts this component
  // on each open, so a fresh `useState(0)` initial value already gives us
  // the right behavior — no extra effect needed.

  // Attach a document-level keydown so Arrow/Enter while the textarea
  // still has focus drive the menu. The textarea's own handleKeyDown
  // continues to handle Escape and submit.
  useEffect(() => {
    if (!isMention) return;
    const handler = (e: KeyboardEvent) => {
      const list = itemsRef.current;
      if (list.length === 0) return;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setActiveIdx((i) => (i + 1) % list.length);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setActiveIdx((i) => (i - 1 + list.length) % list.length);
      } else if (e.key === "Enter") {
        const item = list[activeIdxRef.current];
        if (!item) return;
        e.preventDefault();
        onSelectItemRef.current(item.key as SelectableSpaceKey);
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [isMention]);

  return (
    <div
      role={isMention ? "listbox" : undefined}
      aria-label={isMention ? t("Reference space") : undefined}
      className={`rounded-xl border border-[var(--border)] bg-[var(--popover)] shadow-lg backdrop-blur-md ${
        compact ? "w-[280px] py-1.5" : "w-64 p-2"
      }`}
    >
      <div className={compact ? "" : "space-y-1"}>
        {items.map(({ key, label, description, icon: Icon }, idx) => {
          const count = countFor(key as SelectableSpaceKey, selectedCounts);
          const isActive = isMention && idx === activeIdx;
          // Two kinds of rows, Claude-style: "attach" is a direct action
          // (opens the file dialog), everything after it opens a
          // second-level picker — those get a trailing chevron, and a
          // divider separates the two groups.
          const opensPicker = key !== "attach";
          return (
            <Fragment key={key}>
              {idx === 1 && items[0]?.key === "attach" && (
                <div
                  className={`border-t border-[var(--border)]/60 ${
                    compact ? "mx-3 my-1" : "mx-1 my-1"
                  }`}
                />
              )}
              <button
                type="button"
                role={isMention ? "option" : undefined}
                aria-selected={isMention ? isActive : undefined}
                onMouseEnter={isMention ? () => setActiveIdx(idx) : undefined}
                onClick={(e) => {
                  // Record the row's rect so the fullscreen picker can expand
                  // outward from exactly this clickable box.
                  setPickerOrigin(e.currentTarget.getBoundingClientRect());
                  onSelectItem(key as SelectableSpaceKey);
                }}
                className={`flex w-full items-center gap-2.5 text-left transition-colors active:bg-[var(--muted)]/70 ${
                  isActive
                    ? "bg-[var(--muted)]/60"
                    : "hover:bg-[var(--muted)]/40"
                } ${
                  compact
                    ? "px-3.5 py-2 text-[13px]"
                    : "rounded-xl px-3 py-2.5 text-[13px]"
                }`}
              >
                <Icon
                  size={15}
                  strokeWidth={1.7}
                  className="shrink-0 text-[var(--muted-foreground)]"
                />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium text-[var(--foreground)]">
                    {t(label)}
                  </span>
                  {!compact && (
                    <span className="mt-0.5 block truncate text-[11px] text-[var(--muted-foreground)]">
                      {t(description)}
                    </span>
                  )}
                </span>
                {count > 0 && (
                  <span className="shrink-0 rounded-full bg-[var(--primary)]/10 px-1.5 py-px text-[9px] font-semibold text-[var(--primary)]">
                    {count}
                  </span>
                )}
                {opensPicker && (
                  <ChevronRight
                    size={14}
                    strokeWidth={1.8}
                    className="shrink-0 text-[var(--muted-foreground)]/55"
                  />
                )}
              </button>
            </Fragment>
          );
        })}
      </div>
    </div>
  );
});
