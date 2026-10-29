"use client";

/**
 * ViewerLauncher — the viewer's "+" tab, and the one place that names
 * everything the panel can hold.
 *
 * - A web address bar on top, browser-style.
 * - Tools: what can be opened from nothing — a side chat (with Dito, or
 *   whoever the menu beside it names), a Markdown note, a local file, a
 *   blank GeoGebra board.
 * - This conversation: what it already has that is not on screen — its
 *   side chats and the tabs closed a moment ago.
 * - A closing line for what only ever opens on its own (a quiz follow-up, a
 *   subagent run, a figure, a file or link in a reply, a selected passage),
 *   so those are discoverable without pretending they can start from here.
 */

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
} from "react";
import {
  ArrowRight,
  ChevronDown,
  Compass,
  FileUp,
  Globe,
  MessagesSquare,
  NotebookPen,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  ACTIVITY_LABEL,
  ACTIVITY_ROW_HOVER,
  ACTIVITY_TILE,
} from "@/components/chat/home/SessionActivityPanel";
import ResponderList from "@/components/chat/home/ResponderList";
import { RecordTime } from "@/components/sidebar/RecordList";
import { DITO, type SideChatResponder } from "@/lib/side-chat";
import { isMacPlatform, shortcutKeys, type Shortcut } from "@/lib/shortcuts";
import Tooltip from "@/shared/ui/Tooltip";

/** A side chat of this conversation that is not open as a tab. */
export interface LauncherThread {
  id: string;
  title: string;
  /** Who answers it. */
  detail: string;
  icon: LucideIcon;
  /** Seconds since the epoch. */
  updatedAt: number;
}

/** A tab closed in this conversation, offered back once. */
export interface LauncherClosedTab {
  id: string;
  label: string;
  icon: LucideIcon;
}

interface ViewerLauncherProps {
  onOpenUrl: (url: string) => void;
  onOpenLocalFile: (file: File) => void;
  onOpenMarkdownNote: () => void;
  onOpenGeogebraBoard: () => void;
  /** Open a side chat with whoever is picked (Dito from the tile itself). */
  onOpenSideChat: (responder: SideChatResponder) => void;
  /** There is a conversation for the side chat to be about yet. */
  sideChatAboutConversation?: boolean;
  /** Connected agents a side chat can be opened with. */
  sideChatAgents?: { name: string; kind?: string }[];
  sideChatShortcut?: Shortcut;
  threads: LauncherThread[];
  onOpenThread: (id: string) => void;
  closedTabs: LauncherClosedTab[];
  onReopenTab: (id: string) => void;
}

const ROW_FOCUS =
  "focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-[var(--ring)]";

export default function ViewerLauncher({
  onOpenUrl,
  onOpenLocalFile,
  onOpenMarkdownNote,
  onOpenGeogebraBoard,
  onOpenSideChat,
  sideChatAboutConversation = true,
  sideChatAgents = [],
  sideChatShortcut,
  threads,
  onOpenThread,
  closedTabs,
  onReopenTab,
}: ViewerLauncherProps) {
  const { t } = useTranslation();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileSelect = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0];
      if (file) onOpenLocalFile(file);
      event.target.value = "";
    },
    [onOpenLocalFile],
  );

  const hasConversationItems = threads.length > 0 || closedTabs.length > 0;

  return (
    <div className="h-full space-y-5 overflow-y-auto px-3 pb-8 pt-1 sm:px-3.5">
      <AddressBar onOpenUrl={onOpenUrl} />

      <section>
        <h2 className={ACTIVITY_LABEL}>{t("Tools")}</h2>
        <div className="grid grid-cols-2 gap-1.5">
          <SideChatTile
            description={
              sideChatAboutConversation
                ? t("A side chat about this conversation. Nothing asked there is added to it.")
                : t("A conversation of its own, beside this one.")
            }
            aboutConversation={sideChatAboutConversation}
            agents={sideChatAgents}
            shortcut={sideChatShortcut}
            onOpen={onOpenSideChat}
          />
          <ToolTile
            icon={NotebookPen}
            label={t("Markdown note")}
            description={t("A scratch page kept with this conversation.")}
            onClick={onOpenMarkdownNote}
          />
          <ToolTile
            icon={FileUp}
            label={t("Open a local file")}
            description={t("Preview a PDF, image, video, document or code file.")}
            onClick={() => fileInputRef.current?.click()}
          />
          <ToolTile
            icon={Compass}
            label={t("GeoGebra board")}
            description={t("A blank board for drawing figures and graphing functions.")}
            onClick={onOpenGeogebraBoard}
          />
        </div>
      </section>

      {hasConversationItems ? (
        <section>
          <h2 className={ACTIVITY_LABEL}>{t("This conversation")}</h2>
          <ul className={`${ACTIVITY_TILE} p-1`}>
            {threads.map((thread) => (
              <li key={thread.id}>
                <button
                  type="button"
                  onClick={() => onOpenThread(thread.id)}
                  className={`flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors ${ACTIVITY_ROW_HOVER} ${ROW_FOCUS}`}
                >
                  <thread.icon
                    size={15}
                    strokeWidth={1.7}
                    aria-hidden="true"
                    className="shrink-0 text-[var(--muted-foreground)]"
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[12.5px] font-medium text-[var(--foreground)]">
                      {thread.title}
                    </span>
                    <span className="block truncate text-[11px] text-[var(--muted-foreground)]">
                      {thread.detail}
                    </span>
                  </span>
                  <RecordTime
                    seconds={thread.updatedAt}
                    className="shrink-0 text-[11px] tabular-nums text-[var(--muted-foreground)]"
                  />
                </button>
              </li>
            ))}
            {closedTabs.map((tab) => (
              <li key={tab.id}>
                <button
                  type="button"
                  onClick={() => onReopenTab(tab.id)}
                  className={`flex min-h-10 w-full items-center gap-2.5 rounded-lg px-2.5 text-left transition-colors ${ACTIVITY_ROW_HOVER} ${ROW_FOCUS}`}
                >
                  <tab.icon
                    size={15}
                    strokeWidth={1.7}
                    aria-hidden="true"
                    className="shrink-0 text-[var(--muted-foreground)]"
                  />
                  <span className="min-w-0 flex-1 truncate text-[12.5px] font-medium text-[var(--foreground)]">
                    {tab.label}
                  </span>
                  <span className="shrink-0 text-[11px] text-[var(--muted-foreground)]">
                    {t("Recently closed")}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <p className="px-1.5 text-[11.5px] leading-[1.65] text-[var(--muted-foreground)]">
        {t(
          "Quiz follow-ups, subagent runs, figures, and the files and links in a reply open here on their own. Select text in a reply to ask Dito, a partner or an agent about just that passage.",
        )}
      </p>

      <input
        ref={fileInputRef}
        type="file"
        className="hidden"
        onChange={handleFileSelect}
        aria-hidden="true"
        tabIndex={-1}
      />
    </div>
  );
}

function AddressBar({ onOpenUrl }: { onOpenUrl: (url: string) => void }) {
  const { t } = useTranslation();
  const [value, setValue] = useState("");

  const submit = () => {
    const trimmed = value.trim();
    if (!trimmed) return;
    onOpenUrl(/^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`);
    setValue("");
  };

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
      className={`flex h-10 items-center gap-2.5 px-3 transition-[background-color,box-shadow] ${ACTIVITY_TILE} focus-within:bg-[var(--card)] focus-within:shadow-[0_0_0_1px_color-mix(in_srgb,var(--ring)_55%,transparent)]`}
    >
      <Globe
        size={15}
        strokeWidth={1.7}
        aria-hidden="true"
        className="shrink-0 text-[var(--muted-foreground)]"
      />
      <input
        type="text"
        value={value}
        onChange={(event) => setValue(event.target.value)}
        aria-label={t("Open URL")}
        placeholder={t("Enter a web address")}
        autoFocus
        className="min-w-0 flex-1 bg-transparent text-[13px] text-[var(--foreground)] outline-none placeholder:text-[color-mix(in_srgb,var(--muted-foreground)_75%,transparent)]"
      />
      <button
        type="submit"
        disabled={!value.trim()}
        aria-label={t("Open URL")}
        className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-[var(--primary)] text-[var(--primary-foreground)] transition-[opacity,background-color] hover:opacity-85 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)] disabled:bg-transparent disabled:text-[var(--muted-foreground)] disabled:opacity-50"
      >
        <ArrowRight size={13} strokeWidth={2} />
      </button>
    </form>
  );
}

function ToolTile({
  icon: Icon,
  label,
  description,
  shortcut,
  onClick,
}: {
  icon: LucideIcon;
  label: string;
  description: string;
  shortcut?: Shortcut;
  /** Absent renders the tile disabled; the tooltip says why. */
  onClick?: () => void;
}) {
  return (
    <Tooltip
      label={label}
      description={description}
      shortcut={shortcut}
      as="div"
      className="flex min-w-0"
    >
      <button
        type="button"
        onClick={onClick}
        aria-disabled={!onClick}
        className={`group flex min-h-11 w-full min-w-0 items-center gap-2.5 rounded-xl px-3 text-left text-[12.5px] font-medium text-[var(--foreground)] transition-colors ${ACTIVITY_TILE} ${
          onClick
            ? ACTIVITY_ROW_HOVER
            : "cursor-default text-[var(--muted-foreground)] opacity-60"
        } ${ROW_FOCUS}`}
      >
        <Icon
          size={15}
          strokeWidth={1.7}
          aria-hidden="true"
          className="shrink-0 text-[var(--muted-foreground)]"
        />
        <span className="min-w-0 flex-1 truncate">{label}</span>
        {shortcut ? <ShortcutChip shortcut={shortcut} /> : null}
      </button>
    </Tooltip>
  );
}

/**
 * "Ask Dito", with everyone else a side chat can be opened with one click
 * away: the tile itself opens Dito, the chevron on its edge lists partners,
 * partner groups and agents.
 */
function SideChatTile({
  description,
  aboutConversation,
  agents,
  shortcut,
  onOpen,
}: {
  description: string;
  aboutConversation: boolean;
  agents: { name: string; kind?: string }[];
  shortcut?: Shortcut;
  onOpen: (responder: SideChatResponder) => void;
}) {
  const { t } = useTranslation();
  const [menuOpen, setMenuOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!menuOpen) return;
    const away = (event: PointerEvent) => {
      if (!boxRef.current?.contains(event.target as Node)) setMenuOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMenuOpen(false);
    };
    document.addEventListener("pointerdown", away);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", away);
      document.removeEventListener("keydown", escape);
    };
  }, [menuOpen]);
  return (
    <div ref={boxRef} className="relative flex min-w-0">
      <div
        className={`flex min-h-11 w-full min-w-0 items-stretch rounded-xl ${ACTIVITY_TILE}`}
      >
        <Tooltip
          label={t("Ask Dito")}
          description={description}
          shortcut={shortcut}
          as="div"
          className="flex min-w-0 flex-1"
        >
          <button
            type="button"
            onClick={() => onOpen(DITO)}
            className={`flex w-full min-w-0 items-center gap-2.5 rounded-l-xl pl-3 pr-1 text-left text-[12.5px] font-medium text-[var(--foreground)] transition-colors ${ACTIVITY_ROW_HOVER} ${ROW_FOCUS}`}
          >
            <MessagesSquare
              size={15}
              strokeWidth={1.7}
              aria-hidden="true"
              className="shrink-0 text-[var(--muted-foreground)]"
            />
            <span className="min-w-0 flex-1 truncate">{t("Ask Dito")}</span>
          </button>
        </Tooltip>
        <button
          type="button"
          aria-label={t("Ask someone else")}
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen((value) => !value)}
          className={`flex w-8 shrink-0 items-center justify-center rounded-r-xl text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)] ${ACTIVITY_ROW_HOVER} ${ROW_FOCUS}`}
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
          className="absolute left-0 top-full z-20 mt-1.5 max-h-[320px] w-[248px] overflow-y-auto rounded-xl border border-[var(--border)] bg-[var(--popover,var(--card))] p-1 text-[var(--foreground)] shadow-lg"
        >
          <ResponderList
            agents={agents}
            aboutConversation={aboutConversation}
            onPick={(responder) => {
              setMenuOpen(false);
              onOpen(responder);
            }}
          />
        </div>
      ) : null}
    </div>
  );
}

function ShortcutChip({ shortcut }: { shortcut: Shortcut }) {
  return (
    <kbd className="shrink-0 rounded-md bg-[var(--card)] px-1.5 py-0.5 font-sans text-[10.5px] font-medium tracking-[0.04em] text-[var(--muted-foreground)]">
      {shortcutKeys(shortcut).join(isMacPlatform() ? "" : "+")}
    </kbd>
  );
}
