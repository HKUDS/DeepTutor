"use client";

import {
  memo,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type RefObject,
} from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowUp,
  BookOpen,
  Bot,
  Brain,
  Check,
  ChevronDown,
  ChevronRight,
  ClipboardList,
  Loader2,
  MessageSquare,
  Mic,
  Paperclip,
  Plus,
  Sparkles,
  Square,
  UserRound,
  X,
  type LucideIcon,
} from "lucide-react";
import {
  ATTACHMENT_ACCEPT,
  docIconFor,
  formatBytes,
  isSvgFilename,
} from "@/lib/doc-attachments";
import { useTranslation } from "react-i18next";
import { useAuthStatus } from "@/hooks/useAuthStatus";
import { showEncoreAdminNav } from "@/lib/encore-admin-nav";
import type { SelectedHistorySession } from "@/components/chat/HistorySessionPicker";
import type { SelectedQuestionEntry } from "@/components/chat/QuestionBankPicker";
import type { SelectedRecord } from "@/lib/notebook-selection-types";
import type { LLMSelection } from "@/lib/unified-ws";
import type { LLMOption } from "@/lib/llm-options";
import ChatSpaceMenu from "@/components/chat/space/ChatSpaceMenu";
import type { SpaceMemoryFile } from "@/lib/space-items";
import type { SelectedBookReference } from "@/lib/book-references";
import AgentSelector from "./AgentSelector";
import ContextBudgetChip, { type ContextBudget } from "./ContextBudgetChip";
import KnowledgeSelector from "./KnowledgeSelector";
import ModelSelector from "./ModelSelector";
import PersonaSelector from "./PersonaSelector";

type SpaceSelectionCounts = {
  attachments: number;
  knowledge: number;
  chatHistory: number;
  myAgents: number;
  books: number;
  notebooks: number;
  questionBank: number;
  persona: number;
  memory: number;
};
import ContextReferenceTree, {
  type ContextTreeItem,
} from "./ContextReferenceTree";
import { ComposerInput, type ComposerInputHandle } from "./ComposerInput";
import { useVoiceRecorder } from "@/hooks/useVoiceRecorder";

interface PendingAttachment {
  type: string;
  filename: string;
  base64?: string;
  previewUrl?: string;
  size?: number;
  mimeType?: string;
}

interface KnowledgeBase {
  name: string;
}

interface CapabilityDef {
  value: string;
  label: string;
  description: string;
  icon: LucideIcon;
  allowedTools: string[];
  // Loop-engine capabilities (solve / mastery) run on the chat agent loop and
  // are collapsed into the "More" flyout instead of listed directly.
  secondary?: boolean;
}

/** One row in the capability picker — shared by the built-in list and the
 *  "More" flyout so both render identically. */
function CapMenuItem({
  cap,
  selected,
  onSelect,
}: {
  cap: CapabilityDef;
  selected: boolean;
  onSelect: (value: string) => void;
}) {
  const { t } = useTranslation();
  const Icon = cap.icon;
  return (
    <button
      type="button"
      onClick={() => onSelect(cap.value)}
      className={`flex w-full items-center gap-2.5 px-3 py-1.5 text-left transition-colors active:bg-[var(--muted)]/70 ${
        selected ? "bg-[var(--primary)]/[0.06]" : "hover:bg-[var(--muted)]/45"
      }`}
    >
      <Icon
        size={15}
        strokeWidth={1.7}
        className={`shrink-0 ${selected ? "text-[var(--primary)]" : "text-[var(--muted-foreground)]"}`}
      />
      <div className="min-w-0 flex-1">
        <div className="truncate text-[12.5px] font-medium leading-snug text-[var(--foreground)]">
          {t(cap.label)}
        </div>
        <div className="truncate text-[11px] leading-snug text-[var(--muted-foreground)]">
          {t(cap.description)}
        </div>
      </div>
      {selected && (
        <Check
          size={14}
          strokeWidth={2}
          className="shrink-0 text-[var(--primary)]"
        />
      )}
    </button>
  );
}

/**
 * The composer's primary action is a single control that spans the whole
 * turn — send, working, stop — rather than two buttons that swap places at
 * the moment of the click. These are its four states; only the skin changes.
 */
type SendState = "idle" | "blocked" | "ready" | "streaming";

/**
 * `idle` keeps a legible glyph on a hairline ring instead of fading the whole
 * button down: a translucent arrow on an equally translucent fill left the
 * arrow invisible in every theme. Readiness is carried by colour (neutral →
 * primary), not by opacity.
 *
 * Translucency goes through `color-mix` rather than Tailwind's `/NN` opacity
 * modifier. Tailwind 3 can only apply that modifier to colours it can split
 * into channels, so `bg-[var(--primary)]/90` — where the variable holds a hex
 * literal — compiles to nothing at all. `hover:ring-[5px]` and the lift carry
 * the hover state here; the fill deliberately doesn't shift, which also keeps
 * it from having to mix in a direction that reads right on all four themes.
 */
const SEND_STATE_CLASS: Record<SendState, string> = {
  idle: "cursor-default text-[var(--muted-foreground)] ring-1 ring-inset ring-[var(--border)]",
  // The glyph goes to `--foreground`, not `--primary-foreground`: this fill is
  // a wash of `--muted-foreground` and therefore sits near the background, so
  // only the foreground colour is guaranteed to read against it on all four
  // themes. (Inherited as `--primary-foreground`, which was white on pale grey
  // — invisible — but never showed because the old `/30` compiled to nothing.)
  blocked:
    "bg-[color-mix(in_srgb,var(--muted-foreground)_30%,transparent)] text-[var(--foreground)] hover:bg-[color-mix(in_srgb,var(--muted-foreground)_45%,transparent)]",
  ready:
    "bg-[var(--primary)] text-[var(--primary-foreground)] ring-[3px] ring-[color-mix(in_srgb,var(--primary)_18%,transparent)] hover:-translate-y-px hover:ring-[5px]",
  streaming: "bg-[var(--primary)] text-[var(--primary-foreground)]",
};

export default memo(function ChatComposer({
  composerRef,
  capMenuRef,
  capBtnRef,
  spaceMenuRef,
  spaceBtnRef,
  dragCounter,
  dragging,
  capMenuOpen,
  spaceMenuOpen,
  hasMessages,
  attachments,
  attachmentError,
  activeCap,
  knowledgeBases,
  connectedAgents = [],
  selectedAgent = null,
  onSelectAgent,
  subagentBudget = null,
  onSubagentBudgetChange,
  llmOptions,
  activeLLMDefault,
  llmSelection,
  llmOptionsLoading,
  llmOptionsError,
  onRefreshLLMOptions,
  contextBudget = null,
  selectedNotebookRecords,
  selectedBookReferences,
  selectedHistorySessions,
  selectedAgentSessions,
  selectedQuestionEntries,
  notebookReferenceGroups,
  selectedPersona,
  selectedMemoryFiles,
  selectedKnowledgeBases,
  isStreaming,
  isVisualizeMode,
  capabilityNeedsConfig,
  capabilityConfigConfirmed,
  onRequestConfigConfirm,
  capabilities,
  onSetCapMenuOpen,
  onSetSpaceMenuOpen,
  onToggleKB,
  onSelectLLM,
  onSelectNotebookPicker,
  onSelectBookPicker,
  onSelectHistoryPicker,
  onSelectAgentsPicker,
  onSelectQuestionBankPicker,
  onSelectPersonaPicker,
  onSelectMemoryPicker,
  onClearPersona,
  personaSelection,
  onPersonaSelectionChange,
  personaSelectorOpen,
  onPersonaSelectorOpenChange,
  agentsAvailable = true,
  onToggleMemoryFile,
  onSend,
  onRemoveAttachment,
  onPreviewAttachment,
  onRemoveHistory,
  onRemoveAgent,
  onRemoveBookReference,
  onRemoveNotebook,
  onRemoveQuestion,
  onDragEnter,
  onDragLeave,
  onDragOver,
  onDrop,
  onPaste,
  onAddFiles,
  onSelectCapability,
  onCancelStreaming,
  prefillInputRef,
  inputPlaceholder,
}: {
  composerRef: RefObject<HTMLDivElement | null>;
  capMenuRef: RefObject<HTMLDivElement | null>;
  capBtnRef: RefObject<HTMLButtonElement | null>;
  spaceMenuRef: RefObject<HTMLDivElement | null>;
  spaceBtnRef: RefObject<HTMLButtonElement | null>;
  dragCounter: RefObject<number>;
  dragging: boolean;
  capMenuOpen: boolean;
  spaceMenuOpen: boolean;
  hasMessages: boolean;
  attachments: PendingAttachment[];
  attachmentError: string | null;
  activeCap: CapabilityDef;
  knowledgeBases: KnowledgeBase[];
  /** Connected local subagents (Claude Code / Codex) selectable for this turn. */
  connectedAgents?: { name: string; kind?: string }[];
  /** The connected agent selected for this turn, if any (single-select). */
  selectedAgent?: string | null;
  onSelectAgent?: (name: string | null) => void;
  /** Max times DeepTutor may consult the selected agent this turn. */
  subagentBudget?: number | null;
  onSubagentBudgetChange?: (budget: number) => void;
  llmOptions: LLMOption[];
  activeLLMDefault: LLMSelection | null;
  llmSelection: LLMSelection | null;
  llmOptionsLoading: boolean;
  llmOptionsError: boolean;
  onRefreshLLMOptions?: () => void;
  /**
   * Context-window breakdown measured on the last turn that reported one.
   * Omitted by surfaces that don't track it (quiz follow-up) and null until
   * the first turn completes — the chip is skipped entirely in both cases.
   */
  contextBudget?: ContextBudget | null;
  selectedNotebookRecords: SelectedRecord[];
  selectedBookReferences: SelectedBookReference[];
  selectedHistorySessions: SelectedHistorySession[];
  selectedAgentSessions: SelectedHistorySession[];
  selectedQuestionEntries: SelectedQuestionEntry[];
  notebookReferenceGroups: Array<{
    notebookId: string;
    notebookName: string;
    count: number;
  }>;
  selectedPersona: string | null;
  selectedMemoryFiles: SpaceMemoryFile[];
  selectedKnowledgeBases: string[];
  isStreaming: boolean;
  isVisualizeMode: boolean;
  /**
   * True when the active capability (e.g. Quiz / Visualize / Research)
   * requires explicit configuration before sending. When true, `canSend`
   * is gated on `capabilityConfigConfirmed`.
   */
  capabilityNeedsConfig: boolean;
  capabilityConfigConfirmed: boolean;
  /**
   * Called when the user clicks the send button while config is required
   * but not yet confirmed. The page uses this to surface the config card
   * (open the Activity panel, scroll to it, etc.).
   */
  onRequestConfigConfirm: () => void;
  capabilities: CapabilityDef[];
  onSetCapMenuOpen: (open: boolean | ((prev: boolean) => boolean)) => void;
  onSetSpaceMenuOpen: (open: boolean | ((prev: boolean) => boolean)) => void;
  onToggleKB: (name: string) => void;
  onSelectLLM: (selection: LLMSelection | null) => void;
  onSelectNotebookPicker: () => void;
  onSelectBookPicker: () => void;
  onSelectHistoryPicker: () => void;
  onSelectAgentsPicker: () => void;
  onSelectQuestionBankPicker: () => void;
  onSelectPersonaPicker: () => void;
  onSelectMemoryPicker: () => void;
  onClearPersona: () => void;
  /**
   * Session-persona wiring (main chat only). When `onPersonaSelectionChange`
   * is provided, the toolbar shows a PersonaSelector chip and the composer
   * accepts the `/persona` slash command. The quiz follow-up surface omits
   * these and keeps its per-turn persona picker flow.
   */
  personaSelection?: string;
  onPersonaSelectionChange?: (persona: string) => void;
  personaSelectorOpen?: boolean;
  onPersonaSelectorOpenChange?: (open: boolean) => void;
  /** Hide the My Agents reference entry (e.g. the quiz follow-up surface). */
  agentsAvailable?: boolean;
  onToggleMemoryFile: (file: SpaceMemoryFile) => void;
  onSend: (content: string) => void;
  onRemoveAttachment: (index: number) => void;
  onPreviewAttachment?: (index: number) => void;
  onRemoveHistory: (sessionId: string) => void;
  onRemoveAgent: (sessionId: string) => void;
  onRemoveBookReference: (bookId: string) => void;
  onRemoveNotebook: (notebookId: string) => void;
  onRemoveQuestion: (entryId: number) => void;
  onDragEnter: (event: React.DragEvent) => void;
  onDragLeave: (event: React.DragEvent) => void;
  onDragOver: (event: React.DragEvent) => void;
  onDrop: (event: React.DragEvent) => void;
  onPaste: (event: React.ClipboardEvent) => void;
  onAddFiles: (files: File[]) => void;
  onSelectCapability: (value: string) => void;
  onCancelStreaming: () => void;
  /**
   * Optional ref the composer writes its ``prefillInput`` function into
   * once mounted, so the message-list side (specifically
   * ``AskUserOptions`` chips) can drop a string into the textarea
   * without owning the composer's imperative handle directly.
   */
  prefillInputRef?: React.MutableRefObject<((text: string) => void) | null>;
  /** Override the composer placeholder (e.g. quiz follow-up). */
  inputPlaceholder?: string;
}) {
  const { t } = useTranslation();
  const { enabled, isAdmin, loading: authLoading } = useAuthStatus();
  const showModelControls = showEncoreAdminNav({
    loading: authLoading,
    enabled,
    isAdmin,
  });
  const CapIcon = activeCap.icon;

  const [hasContent, setHasContent] = useState(false);
  const [moreCapsOpen, setMoreCapsOpen] = useState(false);
  const [lastCapMenuOpen, setLastCapMenuOpen] = useState(capMenuOpen);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const restoreFocusOnReturnRef = useRef(false);
  const inputHandleRef = useRef<ComposerInputHandle>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  if (lastCapMenuOpen !== capMenuOpen) {
    setLastCapMenuOpen(capMenuOpen);
    if (!capMenuOpen) setMoreCapsOpen(false);
  }

  useEffect(() => {
    if (!prefillInputRef) return;
    prefillInputRef.current = (text: string) => {
      inputHandleRef.current?.setValue(text);
    };
    return () => {
      if (prefillInputRef) prefillInputRef.current = null;
    };
  }, [prefillInputRef]);

  // Microphone → speech-to-text. Appends the transcript to whatever is already
  // in the composer so a dictated phrase can be combined with typed text.
  const handleTranscript = useCallback((text: string) => {
    const current = inputHandleRef.current?.getValue() || "";
    const next = current.trim() ? `${current.trimEnd()} ${text}` : text;
    inputHandleRef.current?.setValue(next);
  }, []);
  const recorder = useVoiceRecorder(handleTranscript);

  // Composer-row compaction: when the available width drops below ~620 px
  // (e.g. the Viewer panel is open or the user is on a narrow viewport),
  // the cap chip + Tools/Attach/Space labels collide. We measure the
  // composer itself and flip those labels to icon-only below the
  // threshold. Count-badges stay visible so users still see how many
  // things are selected.
  const [composerCompact, setComposerCompact] = useState(false);
  useEffect(() => {
    const el = composerRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    setComposerCompact(el.getBoundingClientRect().width < 620);
    const observer = new ResizeObserver(() => {
      if (composerRef.current) {
        setComposerCompact(
          composerRef.current.getBoundingClientRect().width < 620,
        );
      }
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [composerRef]);

  const handlePickFiles = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  const handleFileInputChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      const picked = Array.from(event.target.files ?? []);
      if (picked.length) onAddFiles(picked);
      // Reset so picking the same file twice still triggers `change`.
      event.target.value = "";
    },
    [onAddFiles],
  );

  const focusTextarea = useCallback(() => {
    requestAnimationFrame(() => textareaRef.current?.focus());
  }, []);

  useEffect(() => {
    const rememberFocus = () => {
      restoreFocusOnReturnRef.current =
        document.activeElement === textareaRef.current;
    };
    const restoreFocus = () => {
      if (
        restoreFocusOnReturnRef.current &&
        document.visibilityState === "visible"
      ) {
        focusTextarea();
      }
    };

    window.addEventListener("blur", rememberFocus);
    window.addEventListener("focus", restoreFocus);
    document.addEventListener("visibilitychange", restoreFocus);
    return () => {
      window.removeEventListener("blur", rememberFocus);
      window.removeEventListener("focus", restoreFocus);
      document.removeEventListener("visibilitychange", restoreFocus);
    };
  }, [focusTextarea]);

  useEffect(() => {
    if (!hasMessages) focusTextarea();
  }, [hasMessages, focusTextarea]);

  const handleSelectCapability = useCallback(
    (value: string) => {
      setMoreCapsOpen(false);
      onSelectCapability(value);
    },
    [onSelectCapability],
  );

  // Functional-update form keeps `handleInputChange` identity stable across
  // every keystroke (no `hasContent` in deps), so the memoized ComposerInput
  // doesn't get re-rendered just because we observed a content-empty toggle.
  const handleInputChange = useCallback((val: string) => {
    const next = !!val.trim();
    setHasContent((prev) => (prev === next ? prev : next));
  }, []);

  const doSend = useCallback(
    (content: string) => {
      onSend(content);
      setHasContent(false);
      inputHandleRef.current?.clear();
      // Sending can move focus to the button or rerender the empty-state
      // composer into the conversation layout. Restore it after that update
      // so the user can keep typing, including after switching back to the tab.
      focusTextarea();
    },
    [focusTextarea, onSend],
  );

  const hasReferences =
    !!attachments.length ||
    !!selectedBookReferences.length ||
    !!selectedNotebookRecords.length ||
    !!selectedHistorySessions.length ||
    !!selectedAgentSessions.length ||
    !!selectedQuestionEntries.length ||
    !!selectedPersona ||
    !!selectedMemoryFiles.length;

  // `capabilityNeedsConfig && !capabilityConfigConfirmed` blocks send so the
  // user has to click *Confirm* in the right-side Activity panel first.
  // Clicking the send button while in this state surfaces the config card
  // (via `onRequestConfigConfirm`) instead of silently doing nothing.
  const isConfigBlocked = capabilityNeedsConfig && !capabilityConfigConfirmed;
  const hasIntent = hasContent || hasReferences;
  const canSend = hasIntent && !isStreaming && !isConfigBlocked;

  // `blocked` only exists once there is intent: without it the button stays
  // `idle` so an empty composer doesn't present a live send affordance. That
  // makes intent — not `canSend` — the thing that decides interactivity, so
  // the `blocked` state can stay clickable and surface the config card.
  const sendState: SendState = isStreaming
    ? "streaming"
    : !hasIntent
      ? "idle"
      : isConfigBlocked
        ? "blocked"
        : "ready";

  const spaceSelectionCounts: SpaceSelectionCounts = {
    attachments: attachments.length,
    knowledge: selectedKnowledgeBases.length,
    chatHistory: selectedHistorySessions.length,
    myAgents: selectedAgentSessions.length,
    books: selectedBookReferences.reduce(
      (total, ref) => total + ref.pages.length,
      0,
    ),
    notebooks: selectedNotebookRecords.length,
    questionBank: selectedQuestionEntries.length,
    persona: selectedPersona ? 1 : 0,
    memory: selectedMemoryFiles.length,
  };
  // Badge on the "+" button = how many things are selected through the
  // "+" menu. Knowledge is excluded: it no longer lives in this menu —
  // it has its own toolbar chip (KnowledgeSelector) with its own active
  // state, so counting it here would double-signal.
  const contextSelectionCount = Object.entries(spaceSelectionCounts).reduce(
    (total, [key, count]) => (key === "knowledge" ? total : total + count),
    0,
  );

  // Unified reference tree above the textarea: Space references, persona
  // and memory render as quiet monochrome rows, collapsed behind a count
  // by default. File attachments intentionally stay OUT of the tree —
  // they keep their preview cards below the textarea.
  // Knowledge bases are intentionally NOT in this tree: they are a
  // session-level retrieval SCOPE (sticky, persisted), not a one-shot
  // reference like the rows below. That sticky state lives in the
  // toolbar KnowledgeSelector chip instead — same lifecycle class as
  // the persona selector.
  const contextTreeItems: ContextTreeItem[] = [
    ...selectedBookReferences.map(
      (book): ContextTreeItem => ({
        key: `book-${book.bookId}`,
        icon: BookOpen,
        kind: t("Book"),
        label: `${book.bookTitle} (${book.pages.length})`,
        onRemove: () => onRemoveBookReference(book.bookId),
      }),
    ),
    ...notebookReferenceGroups.map(
      (group): ContextTreeItem => ({
        key: `nb-${group.notebookId}`,
        icon: BookOpen,
        kind: t("Notebook"),
        label: `${group.notebookName} (${group.count})`,
        onRemove: () => onRemoveNotebook(group.notebookId),
      }),
    ),
    ...selectedHistorySessions.map(
      (session): ContextTreeItem => ({
        key: `hist-${session.sessionId}`,
        icon: MessageSquare,
        kind: t("Chat History"),
        label: session.title,
        onRemove: () => onRemoveHistory(session.sessionId),
      }),
    ),
    ...selectedAgentSessions.map(
      (session): ContextTreeItem => ({
        key: `agent-${session.sessionId}`,
        icon: Bot,
        kind: t("My Agents"),
        label: session.title,
        onRemove: () => onRemoveAgent(session.sessionId),
      }),
    ),
    ...selectedQuestionEntries.map(
      (entry): ContextTreeItem => ({
        key: `q-${entry.id}`,
        icon: ClipboardList,
        kind: t("Question Bank"),
        label: entry.question,
        onRemove: () => onRemoveQuestion(entry.id),
      }),
    ),
    ...(selectedPersona
      ? [
          {
            key: "persona",
            icon: UserRound,
            kind: t("Persona"),
            label: selectedPersona,
            onRemove: onClearPersona,
          } satisfies ContextTreeItem,
        ]
      : []),
    ...selectedMemoryFiles.map(
      (file): ContextTreeItem => ({
        key: `mem-${file}`,
        icon: Brain,
        kind: t("Memory"),
        label: file === "summary" ? t("Summary") : t("Profile"),
        onRemove: () => onToggleMemoryFile(file),
      }),
    ),
  ];

  const handleManualSend = useCallback(() => {
    if (isConfigBlocked) {
      // Don't silently fail — surface the config card so the user knows
      // they need to confirm settings first.
      onRequestConfigConfirm();
      return;
    }
    if (!canSend) return;
    const content = inputHandleRef.current?.getValue() || "";
    doSend(content);
  }, [canSend, doSend, isConfigBlocked, onRequestConfigConfirm]);

  // One button, so one handler: mid-turn the same control cancels.
  const handleSendButtonClick = useCallback(() => {
    if (isStreaming) {
      onCancelStreaming();
      return;
    }
    handleManualSend();
  }, [handleManualSend, isStreaming, onCancelStreaming]);

  const sendLabel =
    sendState === "streaming" ? t("Stop generating") : t("Send");
  const sendTitle =
    sendState === "blocked"
      ? t("Confirm settings on the right to send.")
      : sendLabel;

  return (
    <div
      ref={composerRef}
      className={`relative z-20 mx-auto w-full shrink-0 px-6 pb-5 ${hasMessages ? "pt-1 max-w-[960px]" : "max-w-[768px]"}`}
      style={{
        transition: "max-width 650ms cubic-bezier(0.16, 1, 0.3, 1)",
      }}
    >
      {hasMessages && (
        <div className="pointer-events-none absolute inset-x-0 top-0 h-6 bg-gradient-to-b from-transparent to-[var(--background)]/72" />
      )}

      <div className="relative">
        <div
          className={`relative rounded-[26px] border bg-[var(--card)] shadow-[0_1px_2px_rgba(0,0,0,0.025),0_10px_28px_-10px_rgba(0,0,0,0.08)] transition-colors ${
            dragging
              ? "border-[var(--primary)] bg-[var(--primary)]/[0.03]"
              : "border-[var(--border)]/55"
          }`}
          onDragEnter={onDragEnter}
          onDragLeave={onDragLeave}
          onDragOver={onDragOver}
          onDrop={onDrop}
          data-drag-counter={dragCounter.current}
        >
          {dragging && (
            <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center rounded-[26px] border-2 border-dashed border-[var(--primary)]/50 bg-[var(--primary)]/[0.04]">
              <div className="flex flex-col items-center gap-1 text-[var(--primary)]">
                <Paperclip size={22} strokeWidth={1.6} />
                <span className="text-[13px] font-medium">
                  {t("Drop files here")}
                </span>
                <span className="text-[11px] text-[var(--primary)]/70">
                  {t("Images, Office docs, code & text")}
                </span>
              </div>
            </div>
          )}

          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept={ATTACHMENT_ACCEPT}
            onChange={handleFileInputChange}
            className="hidden"
            aria-hidden="true"
            tabIndex={-1}
          />

          {contextTreeItems.length > 0 && (
            // The reference zone reads as its own layer: a faint muted band
            // with a hairline against the input area, following the card's
            // top radius.
            <div className="rounded-t-[26px] border-b border-[var(--border)]/30 bg-[var(--muted)]/30 px-4 pb-2 pt-2.5">
              {/* Narrower than the composer on purpose — long titles
                  truncate early so the tree reads as an annotation, not a
                  content row. */}
              <div className="max-w-[min(560px,85%)]">
                <ContextReferenceTree
                  items={contextTreeItems}
                  direction="up"
                  summaryNoun={t("references")}
                />
              </div>
            </div>
          )}
          <ComposerInput
            ref={inputHandleRef}
            textareaRef={textareaRef}
            isVisualizeMode={isVisualizeMode}
            isStreaming={isStreaming}
            canSendEmpty={hasReferences}
            onSend={doSend}
            onInputChange={handleInputChange}
            onPaste={onPaste}
            connectedAgents={connectedAgents}
            selectedAgent={selectedAgent}
            onSelectAgent={onSelectAgent}
            selectedCounts={spaceSelectionCounts}
            knowledgeAvailable={false}
            personaAvailable={!onPersonaSelectionChange}
            onSelectAttach={handlePickFiles}
            agentsAvailable={agentsAvailable}
            onSelectNotebookPicker={onSelectNotebookPicker}
            onSelectBookPicker={onSelectBookPicker}
            onSelectHistoryPicker={onSelectHistoryPicker}
            onSelectAgentsPicker={onSelectAgentsPicker}
            onSelectQuestionBankPicker={onSelectQuestionBankPicker}
            onSelectPersonaPicker={onSelectPersonaPicker}
            onSelectMemoryPicker={onSelectMemoryPicker}
            onOpenPersonaSelector={
              onPersonaSelectionChange && onPersonaSelectorOpenChange
                ? () => onPersonaSelectorOpenChange(true)
                : undefined
            }
            placeholder={inputPlaceholder}
            minHeight={hasMessages ? 28 : 64}
          />

          {!!attachments.length && (
            <div className="flex flex-wrap gap-2 px-4 pb-2">
              {attachments.map((a, i) => {
                const previewLabel = t("Preview");
                const removeLabel = t("Remove attachment");
                if (
                  (a.type === "image" || isSvgFilename(a.filename)) &&
                  a.previewUrl
                ) {
                  return (
                    <div
                      key={`${a.filename}-${i}`}
                      className="group relative"
                      title={a.filename || previewLabel}
                    >
                      <button
                        type="button"
                        onClick={() => onPreviewAttachment?.(i)}
                        aria-label={previewLabel}
                        className="relative block h-16 w-16 overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--card)] transition-shadow hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]/40"
                      >
                        {/* Native <img> is safe for SVG: scripts inside an
                            SVG don't execute under <img> context. Next.js
                            <Image> rejects SVG by default. */}
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img
                          src={a.previewUrl}
                          alt={a.filename || t("Attachment preview")}
                          className={`h-full w-full ${isSvgFilename(a.filename) ? "object-contain p-1" : "object-cover"}`}
                        />
                      </button>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          onRemoveAttachment(i);
                        }}
                        aria-label={removeLabel}
                        className="absolute -right-1.5 -top-1.5 flex h-4 w-4 items-center justify-center rounded-full bg-[var(--foreground)] text-[var(--background)] opacity-0 shadow-sm transition-opacity group-hover:opacity-100"
                      >
                        <X size={10} />
                      </button>
                    </div>
                  );
                }
                const spec = docIconFor(a.filename);
                const Icon = spec.Icon;
                const sizeLabel = a.size ? formatBytes(a.size) : "";
                return (
                  <div
                    key={`${a.filename}-${i}`}
                    className="group relative"
                    title={a.filename}
                  >
                    <button
                      type="button"
                      onClick={() => onPreviewAttachment?.(i)}
                      aria-label={previewLabel}
                      className="flex h-16 w-[160px] items-center gap-2.5 rounded-lg border border-[var(--border)] bg-[var(--card)] px-2.5 text-left transition-colors hover:border-[var(--primary)]/40 hover:bg-[var(--muted)]/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]/40"
                    >
                      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-[var(--muted)]/60">
                        <Icon
                          size={22}
                          strokeWidth={1.5}
                          className={spec.tint}
                        />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-[12px] font-medium text-[var(--foreground)]">
                          {a.filename}
                        </div>
                        <div className="truncate text-[10px] uppercase tracking-wide text-[var(--muted-foreground)]">
                          {sizeLabel
                            ? `${spec.label} · ${sizeLabel}`
                            : spec.label}
                        </div>
                      </div>
                    </button>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        onRemoveAttachment(i);
                      }}
                      aria-label={removeLabel}
                      className="absolute -right-1.5 -top-1.5 flex h-4 w-4 items-center justify-center rounded-full bg-[var(--foreground)] text-[var(--background)] opacity-0 shadow-sm transition-opacity group-hover:opacity-100"
                    >
                      <X size={10} />
                    </button>
                  </div>
                );
              })}
            </div>
          )}

          {attachmentError && (
            <div className="px-4 pb-2 text-[11px] text-red-600">
              {attachmentError}
            </div>
          )}

          {/* Claude-style chrome-free toolbar: no divider against the input
              area, no pill borders — quiet text/icon buttons that surface
              on hover. */}
          <div className="px-3 pb-2 pt-0.5">
            <div className="flex items-center gap-1">
              <div className="relative">
                <button
                  ref={capBtnRef}
                  onClick={() => onSetCapMenuOpen((v) => !v)}
                  className={`inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-2 text-[14px] font-medium transition-[background-color,color,transform] duration-150 active:scale-[0.97] ${
                    capMenuOpen
                      ? "bg-[var(--primary)]/10 text-[var(--primary)]"
                      : "text-[var(--foreground)] hover:bg-[var(--muted)]/55"
                  }`}
                >
                  <span className="flex min-w-0 items-center gap-1.5">
                    <CapIcon size={16} strokeWidth={1.7} className="shrink-0" />
                    {composerCompact ? null : (
                      <span className="truncate">{t(activeCap.label)}</span>
                    )}
                  </span>
                  <ChevronDown
                    size={13}
                    strokeWidth={2}
                    className={`-mr-0.5 shrink-0 transition-transform duration-200 ${capMenuOpen ? "rotate-180" : ""}`}
                  />
                </button>

                {capMenuOpen && (
                  <div
                    ref={capMenuRef}
                    className="dt-popup-up absolute bottom-full left-0 z-50 mb-1.5 w-[260px] overflow-visible rounded-xl border border-[var(--border)] bg-[var(--popover)] py-1 shadow-lg backdrop-blur-md"
                  >
                    {capabilities
                      .filter((cap) => !cap.secondary)
                      .map((cap) => (
                        <CapMenuItem
                          key={cap.value}
                          cap={cap}
                          selected={activeCap.value === cap.value}
                          onSelect={handleSelectCapability}
                        />
                      ))}
                    {(() => {
                      const loopCaps = capabilities.filter(
                        (cap) => cap.secondary,
                      );
                      if (loopCaps.length === 0) return null;
                      const loopSelected = loopCaps.some(
                        (cap) => cap.value === activeCap.value,
                      );
                      return (
                        <div
                          className="group/more relative"
                          onMouseEnter={() => setMoreCapsOpen(true)}
                          onMouseLeave={() => setMoreCapsOpen(false)}
                          onFocus={() => setMoreCapsOpen(true)}
                          onBlur={(event) => {
                            const next = event.relatedTarget;
                            if (
                              !next ||
                              !event.currentTarget.contains(next as Node)
                            ) {
                              setMoreCapsOpen(false);
                            }
                          }}
                        >
                          <button
                            type="button"
                            aria-haspopup="menu"
                            aria-expanded={moreCapsOpen}
                            onClick={() => setMoreCapsOpen((open) => !open)}
                            className={`flex w-full items-center gap-2.5 px-3 py-1.5 text-left transition-colors ${
                              moreCapsOpen
                                ? "bg-[var(--muted)]/45"
                                : "group-hover/more:bg-[var(--muted)]/45"
                            } ${
                              loopSelected && !moreCapsOpen
                                ? "bg-[var(--primary)]/[0.06]"
                                : ""
                            }`}
                          >
                            <Sparkles
                              size={15}
                              strokeWidth={1.7}
                              className={`shrink-0 ${loopSelected ? "text-[var(--primary)]" : "text-[var(--muted-foreground)]"}`}
                            />
                            <div className="min-w-0 flex-1">
                              <div className="truncate text-[12.5px] font-medium leading-snug text-[var(--foreground)]">
                                {t("More Capabilities")}
                              </div>
                              <div className="truncate text-[11px] leading-snug text-[var(--muted-foreground)]">
                                {t("Agent-loop driven modes")}
                              </div>
                            </div>
                            <ChevronRight
                              size={14}
                              strokeWidth={2}
                              className="shrink-0 text-[var(--muted-foreground)]"
                            />
                          </button>
                          {/* Right flyout. ``pl-1.5`` is a pointer bridge so the
                              cursor can cross the gap without dropping hover;
                              click/focus also open it for touch and keyboard. */}
                          <div
                            className={`absolute bottom-0 left-full z-50 pl-1.5 transition-opacity duration-150 ${
                              moreCapsOpen
                                ? "visible opacity-100"
                                : "invisible opacity-0"
                            }`}
                          >
                            <div className="w-[240px] overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--popover)] py-1 shadow-lg backdrop-blur-md">
                              {loopCaps.map((cap) => (
                                <CapMenuItem
                                  key={cap.value}
                                  cap={cap}
                                  selected={activeCap.value === cap.value}
                                  onSelect={handleSelectCapability}
                                />
                              ))}
                            </div>
                          </div>
                        </div>
                      );
                    })()}
                  </div>
                )}
              </div>

              <div className="relative flex min-w-0 flex-1 items-center">
                <button
                  ref={spaceBtnRef}
                  type="button"
                  onClick={() => onSetSpaceMenuOpen((v) => !v)}
                  title={t("Add files & context")}
                  aria-label={t("Add files & context")}
                  className={`relative flex h-8 w-8 shrink-0 items-center justify-center rounded-lg transition-[background-color,color,transform] duration-150 active:scale-90 ${
                    spaceMenuOpen
                      ? "bg-[var(--muted)] text-[var(--foreground)]"
                      : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]/55 hover:text-[var(--foreground)]"
                  }`}
                >
                  <Plus size={20} strokeWidth={1.8} />
                  {contextSelectionCount > 0 && (
                    <span className="absolute -right-0.5 -top-0.5 flex h-[13px] min-w-[13px] items-center justify-center rounded-full bg-[var(--primary)] px-[3px] text-[8px] font-semibold leading-none text-[var(--primary-foreground)] ring-[1.5px] ring-[var(--card)]">
                      {contextSelectionCount}
                    </span>
                  )}
                </button>
                <AnimatePresence>
                  {spaceMenuOpen && (
                    <motion.div
                      ref={spaceMenuRef}
                      className="absolute bottom-full left-0 z-50 mb-1.5"
                      style={{ transformOrigin: "bottom left" }}
                      initial={{ opacity: 0, y: 6, scale: 0.96 }}
                      animate={{ opacity: 1, y: 0, scale: 1 }}
                      exit={{ opacity: 0, y: 4, scale: 0.97 }}
                      transition={{ duration: 0.16, ease: [0.16, 1, 0.3, 1] }}
                    >
                      <ChatSpaceMenu
                        variant="toolbar"
                        selectedCounts={spaceSelectionCounts}
                        knowledgeAvailable={false}
                        personaAvailable={!onPersonaSelectionChange}
                        agentsAvailable={agentsAvailable}
                        onSelectItem={(key) => {
                          onSetSpaceMenuOpen(false);
                          if (key === "attach") handlePickFiles();
                          else if (key === "chat_history")
                            onSelectHistoryPicker();
                          else if (key === "my_agents") onSelectAgentsPicker();
                          else if (key === "books") onSelectBookPicker();
                          else if (key === "notebooks")
                            onSelectNotebookPicker();
                          else if (key === "question_bank")
                            onSelectQuestionBankPicker();
                          else if (key === "persona") onSelectPersonaPicker();
                          else if (key === "memory") onSelectMemoryPicker();
                        }}
                      />
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>

              <div className="ml-auto flex shrink-0 items-center gap-1.5">
                {connectedAgents.length > 0 && onSelectAgent ? (
                  <AgentSelector
                    agents={connectedAgents}
                    selected={selectedAgent}
                    onSelect={onSelectAgent}
                    budget={subagentBudget}
                    onBudgetChange={onSubagentBudgetChange}
                  />
                ) : null}
                {knowledgeBases.length > 0 ? (
                  <KnowledgeSelector
                    knowledgeBases={knowledgeBases}
                    selected={selectedKnowledgeBases}
                    onToggle={onToggleKB}
                  />
                ) : null}
                {onPersonaSelectionChange ? (
                  <PersonaSelector
                    value={personaSelection ?? ""}
                    onChange={onPersonaSelectionChange}
                    open={personaSelectorOpen}
                    onOpenChange={onPersonaSelectorOpenChange}
                  />
                ) : null}
                {showModelControls ? (
                  <ModelSelector
                    options={llmOptions}
                    activeDefault={activeLLMDefault}
                    value={llmSelection}
                    loading={llmOptionsLoading}
                    error={llmOptionsError}
                    onChange={onSelectLLM}
                    onRefresh={onRefreshLLMOptions}
                  />
                ) : null}
                {showModelControls && contextBudget ? (
                  <ContextBudgetChip budget={contextBudget} />
                ) : null}

                <button
                  type="button"
                  onClick={recorder.toggle}
                  disabled={recorder.state === "transcribing" || isStreaming}
                  className={`group relative inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-[10px] transition-[background-color,color,transform] duration-150 active:scale-90 disabled:opacity-40 ${
                    recorder.state === "recording"
                      ? "bg-red-500/15 text-red-500"
                      : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]/55 hover:text-[var(--foreground)]"
                  }`}
                  aria-label={
                    recorder.state === "recording"
                      ? t("Stop recording")
                      : t("Record voice")
                  }
                  title={
                    recorder.error ||
                    (recorder.state === "recording"
                      ? t("Stop recording")
                      : t("Record voice"))
                  }
                >
                  {recorder.state === "recording" && (
                    <span className="pointer-events-none absolute inset-0 rounded-[10px] border border-red-500/40 animate-pulse" />
                  )}
                  {recorder.state === "transcribing" ? (
                    <Loader2
                      size={16}
                      strokeWidth={1.9}
                      className="animate-spin"
                    />
                  ) : (
                    <Mic size={16} strokeWidth={1.9} />
                  )}
                </button>

                {/* The thing you press is the thing that's working is the
                    thing you press to stop — one element for the whole turn,
                    so the button never swaps out from under the cursor at the
                    moment of the click. The glyph crossfades arrow→square in
                    place (both stacked in the same grid cell) and the progress
                    ring moves to the perimeter, where it can spin without
                    fighting the square for the same space. */}
                <button
                  type="button"
                  onClick={handleSendButtonClick}
                  disabled={sendState === "idle"}
                  className={`group relative ml-1 inline-grid h-8 w-8 shrink-0 place-items-center rounded-full transition-[background-color,box-shadow,transform] duration-200 active:scale-95 ${SEND_STATE_CLASS[sendState]}`}
                  aria-label={sendLabel}
                  title={sendTitle}
                >
                  {sendState === "streaming" && (
                    // Outside the fill, so "still working" reads at a glance
                    // and dims on hover to hand the control back as "stop".
                    <span className="pointer-events-none absolute -inset-[3px] rounded-full border-2 border-[color-mix(in_srgb,var(--primary)_15%,transparent)] border-t-[var(--primary)] animate-spin transition-opacity group-hover:opacity-30" />
                  )}
                  <ArrowUp
                    size={16}
                    strokeWidth={2.5}
                    className={`col-start-1 row-start-1 transition-[opacity,transform] duration-200 ${
                      sendState === "streaming"
                        ? "scale-50 opacity-0"
                        : "scale-100 opacity-100"
                    }`}
                  />
                  <Square
                    size={10}
                    strokeWidth={2.6}
                    className={`col-start-1 row-start-1 fill-current transition-[opacity,transform] duration-200 ${
                      sendState === "streaming"
                        ? "scale-100 opacity-100"
                        : "scale-50 opacity-0"
                    }`}
                  />
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
});
