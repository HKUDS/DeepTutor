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
import { saveWorkspaceDraft, readWorkspaceDraft } from "@/lib/workspace-drafts";
import {
  ArrowUp,
  BookMarked,
  BookOpen,
  Bot,
  Brain,
  Check,
  ChevronDown,
  ChevronRight,
  ClipboardList,
  Database,
  Loader2,
  MessageSquare,
  Mic,
  Paperclip,
  Plug,
  Sparkles,
  Square,
  UserRound,
  Users,
  Wand2,
  X,
} from "lucide-react";
import {
  ATTACHMENT_ACCEPT,
} from "@/lib/doc-attachments";
import { useTranslation } from "react-i18next";

import { CoursePill } from "@/components/chat/home/CoursePill";
import { WorkspacePill } from "@/components/workspaces/WorkspacePill";
import type { StudyCourse } from "@/lib/courses-api";
import type { ChatWorkspaceRegistration } from "@/lib/workspaces-api";
import type { SelectedHistorySession } from "@/components/chat/HistorySessionPicker";
import type { SelectedQuestionEntry } from "@/components/chat/QuestionBankPicker";
import type { SelectedRecord } from "@/lib/notebook-selection-types";
import type { LLMSelection } from "@/features/chat/model/protocol";
import type { LLMOption } from "@/lib/llm-options";
import ChatSpaceMenu from "@/components/chat/space/ChatSpaceMenu";
import type { SpaceMemoryFile } from "@/lib/space-items";
import type { SelectedBookReference } from "@/lib/book-references";
import type { SelectedReadingReference } from "@/lib/reading-references";
import AgentSelector from "./AgentSelector";
import PartnerSelector from "./PartnerSelector";
import { listPartners, type PartnerInfo } from "@/lib/partners-api";
import PartnerGroupSelector from "./PartnerGroupSelector";
import { listPartnerGroups, type PartnerGroup } from "@/lib/partner-groups-api";
import ContextBudgetChip, { type ContextBudget } from "./ContextBudgetChip";
import { RailSlot } from "@/components/chat/home/ComposerRail";
import ComposerResources, {
  type ComposerResourceItem,
} from "./ComposerResources";
import KnowledgeSelector from "./KnowledgeSelector";
import ModelSelector from "./ModelSelector";
import styles from "./ChatComposer.module.css";
import PersonaSelector from "./PersonaSelector";
import ResourceSelector from "./ResourceSelector";
import type { ComposerResourceCatalog } from "@/hooks/useComposerResources";
import type { ResourceSelection } from "@/features/chat/ChatStateAdapter";

type SpaceSelectionCounts = {
  attachments: number;
  knowledge: number;
  chatHistory: number;
  myAgents: number;
  books: number;
  reading: number;
  notebooks: number;
  questionBank: number;
  persona: number;
  memory: number;
};
import type { ContextTreeItem } from "./ContextReferenceTree";
import SelectedResources from "./SelectedResources";
import { knowledgeBaseRef } from "@/lib/knowledge-helpers";
import { ComposerInput, type ComposerInputHandle } from "./ComposerInput";
import { useVoiceRecorder } from "@/hooks/useVoiceRecorder";
import type { CapabilityDef } from "@/features/capabilities/presentation";
import AttachmentProcessingStatus from "./AttachmentProcessingStatus";
import type { AttachmentProcessingItem } from "@/features/chat/selectors/attachment-processing";

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
  courses = [],
  courseId = "",
  onSelectCourse,
  workspaces = [],
  workspaceId = "",
  onSelectWorkspace,
  workspaceError = "",
  workspacePending = false,
  spaceMenuOpen,
  hasMessages,
  attachments,
  attachmentError,
  attachmentProcessing = [],
  activeCap,
  knowledgeBases,
  connectedAgents = [],
  selectedPartner = null,
  onSelectPartner,
  selectedPartnerGroup = null,
  onSelectPartnerGroup,
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
  selectedReadingReferences = [],
  selectedHistorySessions,
  selectedAgentSessions,
  selectedQuestionEntries,
  notebookReferenceGroups,
  selectedPersona,
  selectedMemoryFiles,
  selectedKnowledgeBases,
  isStreaming,
  awaitingUserReply = false,
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
  onSelectReadingPicker,
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
  resourceCatalog,
  resourceSelection,
  onResourceSelectionChange,
  agentsAvailable = true,
  onToggleMemoryFile,
  onSend,
  onRemoveAttachment,
  onPreviewAttachment,
  onRemoveHistory,
  onRemoveAgent,
  onRemoveBookReference,
  onRemoveReadingReference,
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
  inputPlaceholderCompletion,
  showCapabilityChip = true,
}: {
  composerRef: RefObject<HTMLDivElement | null>;
  capMenuRef: RefObject<HTMLDivElement | null>;
  capBtnRef: RefObject<HTMLButtonElement | null>;
  spaceMenuRef: RefObject<HTMLDivElement | null>;
  spaceBtnRef: RefObject<HTMLButtonElement | null>;
  dragCounter: RefObject<number>;
  dragging: boolean;
  capMenuOpen: boolean;
  /* Course binding. Absent on the standalone composers (Mastery Path,
     Immersive Reading), which are already inside one subject's surface and
     have no course to choose. */
  courses?: StudyCourse[];
  courseId?: string;
  onSelectCourse?: (courseId: string) => void;
  /* Workspace binding. Same shape as the course binding above, and absent for
     the same reason on composers that live inside one surface already. */
  workspaces?: ChatWorkspaceRegistration[];
  workspaceId?: string;
  onSelectWorkspace?: (workspaceId: string) => void;
  workspaceError?: string;
  workspacePending?: boolean;
  spaceMenuOpen: boolean;
  hasMessages: boolean;
  attachments: PendingAttachment[];
  attachmentError: string | null;
  attachmentProcessing?: AttachmentProcessingItem[];
  activeCap: CapabilityDef;
  knowledgeBases: KnowledgeBase[];
  /** Connected local subagents (Claude Code / Codex) selectable for this turn. */
  connectedAgents?: { name: string; kind?: string }[];
  /** The connected agent selected for this turn, if any (single-select). */
  selectedPartner?: string | null;
  onSelectPartner?: (id: string | null) => void;
  selectedPartnerGroup?: string | null;
  onSelectPartnerGroup?: (id: string | null) => void;
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
  selectedReadingReferences?: SelectedReadingReference[];
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
  /** The live turn is paused on an ask_user card and needs an answer. */
  awaitingUserReply?: boolean;
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
  onSelectReadingPicker?: () => void;
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
  /**
   * Skill / MCP narrowing for this conversation. Supplied together: the
   * catalog is what may be picked (already clipped to what the workspace
   * allows) and the selection is what was picked, where empty means the
   * conversation inherits everything. Surfaces without a rail omit all three
   * and keep inheriting, exactly as before the pickers existed.
   */
  resourceCatalog?: ComposerResourceCatalog;
  resourceSelection?: ResourceSelection;
  onResourceSelectionChange?: (selection: ResourceSelection) => void;
  /** Hide the My Agents reference entry (e.g. the quiz follow-up surface). */
  agentsAvailable?: boolean;
  onToggleMemoryFile: (file: SpaceMemoryFile) => void;
  onSend: (content: string) => void;
  onRemoveAttachment: (index: number) => void;
  onPreviewAttachment?: (index: number) => void;
  onRemoveHistory: (sessionId: string) => void;
  onRemoveAgent: (sessionId: string) => void;
  onRemoveBookReference: (bookId: string) => void;
  onRemoveReadingReference?: (materialId: string) => void;
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
  /** A line Tab accepts while the composer is empty. See ComposerInput. */
  inputPlaceholderCompletion?: string;
  /**
   * Hide the capability chip. A surface that only ever runs one capability
   * — and names it in its own chrome — gains nothing from a picker that
   * cannot pick anything.
   */
  showCapabilityChip?: boolean;
}) {
  const { t } = useTranslation();
  const [partners, setPartners] = useState<PartnerInfo[]>([]);
  const [partnersLoading, setPartnersLoading] = useState(false);
  const [partnerLoadError, setPartnerLoadError] = useState(false);
  const canSelectPartner = Boolean(onSelectPartner);
  const canSelectGroup = Boolean(onSelectPartnerGroup);
  useEffect(() => {
    if (!canSelectPartner) return;
    let active = true;
    const refresh = () => {
      setPartnersLoading(true);
      void listPartners().then(value => {
        if (active) { setPartners(value); setPartnerLoadError(false); }
      }).catch(() => { if (active) setPartnerLoadError(true); })
        .finally(() => { if (active) setPartnersLoading(false); });
    };
    refresh();
    window.addEventListener("focus", refresh);
    return () => { active = false; window.removeEventListener("focus", refresh); };
  }, [canSelectPartner]);
  const partnerName = partners.find(partner => partner.partner_id === selectedPartner)?.name || selectedPartner;
  const [partnerGroups, setPartnerGroups] = useState<PartnerGroup[]>([]);
  const [groupLoadError, setGroupLoadError] = useState(false);
  const [groupsLoading, setGroupsLoading] = useState(false);
  useEffect(() => {
    if (!canSelectGroup) return;
    let active = true;
    const refresh = () => {
      setGroupsLoading(true);
      void listPartnerGroups().then(groups => {
        if (active) { setPartnerGroups(groups); setGroupLoadError(false); }
      }).catch(() => { if (active) setGroupLoadError(true); })
        .finally(() => { if (active) setGroupsLoading(false); });
    };
    refresh();
    window.addEventListener("focus", refresh);
    return () => { active = false; window.removeEventListener("focus", refresh); };
  }, [canSelectGroup]);
  const partnerGroupName = partnerGroups.find(group => group.group_id === selectedPartnerGroup)?.name || selectedPartnerGroup;

  const CapIcon = activeCap.icon;

  const [hasContent, setHasContent] = useState(false);
  const [moreCapsOpen, setMoreCapsOpen] = useState(false);
  const [lastCapMenuOpen, setLastCapMenuOpen] = useState(capMenuOpen);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const restoreFocusOnReturnRef = useRef(false);
  const inputHandleRef = useRef<ComposerInputHandle>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const draftAttachmentsRef = useRef(attachments);
  const addDraftFilesRef = useRef(onAddFiles);
  useEffect(() => {
    draftAttachmentsRef.current = attachments;
  }, [attachments]);
  useEffect(() => {
    addDraftFilesRef.current = onAddFiles;
  }, [onAddFiles]);
  const restoredDraftRef = useRef(false);
  useEffect(() => {
    let alive = true;
    const restore = readWorkspaceDraft();
    if (!restoredDraftRef.current) {
      void restore
        .then((draft) => {
          if (!alive || restoredDraftRef.current) return;
          restoredDraftRef.current = true;
          if (!draft) return;
          const current = inputHandleRef.current?.getValue() || "";
          inputHandleRef.current?.setValue(
            current ? `${draft.text}\n${current}` : draft.text,
          );
          const files = draft.attachments
            .filter((item) => item.base64)
            .map((item) => {
              const bytes = Uint8Array.from(atob(item.base64!), (char) =>
                char.charCodeAt(0),
              );
              return new File([bytes], item.filename, {
                type: item.mimeType || "application/octet-stream",
              });
            });
          if (files.length) addDraftFilesRef.current(files);
        })
        .catch(() => {});
    }
    const save = (event: Event) => {
      (event as CustomEvent<Promise<void>[]>).detail.push(
        restore.then(() =>
          saveWorkspaceDraft({
            text: inputHandleRef.current?.getValue() || "",
            attachments: draftAttachmentsRef.current.map(
              ({ filename, base64, mimeType }) => ({
                filename,
                base64,
                mimeType,
              }),
            ),
          }),
        ),
      );
    };
    window.addEventListener("deeptutor:before-workspace-switch", save);
    return () => {
      alive = false;
      window.removeEventListener("deeptutor:before-workspace-switch", save);
    };
  }, []);
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
    [onSelectCapability, setMoreCapsOpen],
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
      void saveWorkspaceDraft({ text: "", attachments: [] }).catch(() => {});
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
    !!selectedReadingReferences.length ||
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
  // A turn paused on a question is technically still streaming, but the only
  // thing that can move it forward is the user's answer. Locking the composer
  // there made the interactive card the ONLY way to answer — and left the
  // learner with no way out at all if the card failed to render.
  const streamingBlocksSend = isStreaming && !awaitingUserReply;
  const canSend = hasIntent && !streamingBlocksSend && !isConfigBlocked;

  // `blocked` only exists once there is intent: without it the button stays
  // `idle` so an empty composer doesn't present a live send affordance. That
  // makes intent — not `canSend` — the thing that decides interactivity, so
  // the `blocked` state can stay clickable and surface the config card.
  const sendState: SendState = streamingBlocksSend
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
    reading: selectedReadingReferences.reduce(
      (total, reference) => total + reference.units.length,
      0,
    ),
    notebooks: selectedNotebookRecords.length,
    questionBank: selectedQuestionEntries.length,
    persona: selectedPersona ? 1 : 0,
    memory: selectedMemoryFiles.length,
  };
  // One selection summary for files, references, and conversation resources.
  const contextTreeItems: ContextTreeItem[] = [
    ...attachments.map((file, index): ContextTreeItem => ({key:`file-${index}`, icon:Paperclip, kind:t("Attach files"),label:file.filename,thumbnailUrl:file.type === "image" ? file.previewUrl : undefined,onClick:()=>onPreviewAttachment?.(index),onRemove:()=>onRemoveAttachment(index)})),
    ...selectedKnowledgeBases.map((id): ContextTreeItem => ({key:`kb-${id}`,icon:Database,kind:t("Knowledge"),label:knowledgeBases.find(kb=>knowledgeBaseRef(kb)===id)?.name || id,onRemove:()=>onToggleKB(id)})),
    ...(personaSelection ? [{key:"persona-scope",icon:UserRound,kind:t("Response style"),label:personaSelection,onRemove:()=>onPersonaSelectionChange?.("")}] : []),
    ...(selectedPartner ? [{ key: "partner-current", icon: UserRound, kind: t("Ask partner"), label: partnerName!, onRemove: () => onSelectPartner?.(null) }] : []),
    ...(selectedPartnerGroup ? [{ key: "partner-group-current", icon: Users, kind: t("Organize partner discussion"), label: partnerGroupName!, onRemove: () => onSelectPartnerGroup?.(null) }] : []),
    ...(selectedAgent ? [{key:"collaborator-current",icon:Bot,kind:t("Ask subagent"),label:selectedAgent,onRemove:()=>onSelectAgent?.(null)}] : []),
    ...(resourceSelection?.skills || []).map((id): ContextTreeItem=>({key:`skill-${id}`,icon:Wand2,kind:t("Skills"),label:resourceCatalog?.skills.find(option=>option.id===id)?.name || id,onRemove:()=>onResourceSelectionChange?.({...resourceSelection!,skills:resourceSelection!.skills.filter(value=>value!==id)})})),
    ...(resourceSelection?.mcp || []).map((id): ContextTreeItem=>({key:`mcp-${id}`,icon:Plug,kind:t("MCP"),label:resourceCatalog?.mcp.find(option=>option.id===id)?.name || id,onRemove:()=>onResourceSelectionChange?.({...resourceSelection!,mcp:resourceSelection!.mcp.filter(value=>value!==id)})})),

    ...selectedBookReferences.map((book): ContextTreeItem => ({
      key: `book-${book.bookId}`,
      icon: BookOpen,
      kind: t("Book"),
      label: `${book.bookTitle} (${book.pages.length})`,
      onRemove: () => onRemoveBookReference(book.bookId),
    })),
    ...selectedReadingReferences.map((material): ContextTreeItem => ({
      key: `reading-${material.materialId}-r${material.revision}`,
      icon: BookMarked,
      kind: t("Reading"),
      label: `${material.materialTitle} (${material.units.length})`,
      onRemove: onRemoveReadingReference
        ? () => onRemoveReadingReference(material.materialId)
        : undefined,
    })),
    ...notebookReferenceGroups.map((group): ContextTreeItem => ({
      key: `nb-${group.notebookId}`,
      icon: BookOpen,
      kind: t("Notebook"),
      label: `${group.notebookName} (${group.count})`,
      onRemove: () => onRemoveNotebook(group.notebookId),
    })),
    ...selectedHistorySessions.map((session): ContextTreeItem => ({
      key: `hist-${session.sessionId}`,
      icon: MessageSquare,
      kind: t("Chat History"),
      label: session.title,
      onRemove: () => onRemoveHistory(session.sessionId),
    })),
    ...selectedAgentSessions.map((session): ContextTreeItem => ({
      key: `agent-${session.sessionId}`,
      icon: Bot,
      kind: t("My Agents"),
      label: session.title,
      onRemove: () => onRemoveAgent(session.sessionId),
    })),
    ...selectedQuestionEntries.map((entry): ContextTreeItem => ({
      key: `q-${entry.id}`,
      icon: ClipboardList,
      kind: t("Question Bank"),
      label: entry.question,
      onRemove: () => onRemoveQuestion(entry.id),
    })),
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
    ...selectedMemoryFiles.map((file): ContextTreeItem => ({
      key: `mem-${file}`,
      icon: Brain,
      kind: t("Memory"),
      label: file === "summary" ? t("Summary") : t("Profile"),
      onRemove: () => onToggleMemoryFile(file),
    })),
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

  // One button, so one handler: mid-turn the same control cancels — except
  // while the turn is waiting on the user, where sending IS how it continues.
  const handleSendButtonClick = useCallback(() => {
    if (streamingBlocksSend) {
      onCancelStreaming();
      return;
    }
    handleManualSend();
  }, [handleManualSend, streamingBlocksSend, onCancelStreaming]);

  const sendLabel =
    sendState === "streaming"
      ? t("Stop generating")
      : awaitingUserReply
        ? t("Send answer")
        : t("Send");
  const sendTitle =
    sendState === "blocked"
      ? t("Confirm settings on the right to send.")
      : sendLabel;

  const toggleResource = useCallback(
    (kind: "skills" | "mcp", id: string) => {
      if (!onResourceSelectionChange) return;
      const current = resourceSelection ?? { skills: [], mcp: [] };
      const list = current[kind];
      onResourceSelectionChange({
        ...current,
        [kind]: list.includes(id)
          ? list.filter((value) => value !== id)
          : [...list, id],
      });
    },
    [onResourceSelectionChange, resourceSelection],
  );

  // Available selectors share one resource panel; omitted catalogs stay hidden.
  const selectedSkills = resourceSelection?.skills ?? [];
  const selectedMcp = resourceSelection?.mcp ?? [];
  const resourceItems: ComposerResourceItem[] = [];
  if (knowledgeBases.length > 0) {
    resourceItems.push({
      key: "knowledge",
      group: "Reference materials",
      summary: selectedKnowledgeBases.length
        ? `${selectedKnowledgeBases.length} ${t("selected")}`
        : t("Default"),
      onClear: () => [...selectedKnowledgeBases].forEach(onToggleKB),
      label: t("Knowledge"),
      icon: Database,
      count: selectedKnowledgeBases.length,
      node: (
        <KnowledgeSelector
          knowledgeBases={knowledgeBases}
          selected={selectedKnowledgeBases}
          onToggle={onToggleKB}
          embedded
        />
      ),
    });
  }
  if (onPersonaSelectionChange) {
    resourceItems.push({
      key: "persona",
      group: "Answer preferences",
      summary: personaSelection || t("Default"),
      onClear: () => onPersonaSelectionChange(""),
      label: t("Response style"),
      icon: UserRound,
      count: personaSelection ? 1 : 0,
      node: (
        <PersonaSelector
          value={personaSelection ?? ""}
          onChange={onPersonaSelectionChange}
          embedded
        />
      ),
    });
  }
  if (onResourceSelectionChange && (resourceCatalog?.skills.length ?? 0) > 0) {
    resourceItems.push({
      key: "skills",
      group: "Tools",
      summary: selectedSkills.length
        ? `${selectedSkills.length} ${t("selected")}`
        : t("Workspace default"),
      resetLabel: t("Use workspace default"),
      onClear: () =>
        onResourceSelectionChange({ skills: [], mcp: selectedMcp }),
      label: t("Skills"),
      icon: Wand2,
      count: selectedSkills.length,
      node: (
        <ResourceSelector
          kind="skills"
          options={resourceCatalog?.skills ?? []}
          selected={selectedSkills}
          onToggle={(id) => toggleResource("skills", id)}
          embedded
        />
      ),
    });
  }
  if (onResourceSelectionChange && (resourceCatalog?.mcp.length ?? 0) > 0) {
    resourceItems.push({
      key: "mcp",
      group: "Tools",
      summary: selectedMcp.length
        ? `${selectedMcp.length} ${t("selected")}`
        : t("Workspace default"),
      resetLabel: t("Use workspace default"),
      onClear: () =>
        onResourceSelectionChange({ skills: selectedSkills, mcp: [] }),
      label: t("MCP"),
      icon: Plug,
      count: selectedMcp.length,
      node: (
        <ResourceSelector
          kind="mcp"
          options={resourceCatalog?.mcp ?? []}
          selected={selectedMcp}
          onToggle={(id) => toggleResource("mcp", id)}
          embedded
        />
      ),
    });
  }

  if (onSelectAgent) {
    resourceItems.push({
      key: "agent",
      group: "Answer preferences",
      summary: selectedAgent || t("None"),
      onClear: () => onSelectAgent(null),
      label: t("Ask subagent"),
      icon: Bot,
      count: selectedAgent ? 1 : 0,
      node: (
        <AgentSelector
          agents={connectedAgents}
          selected={selectedAgent}
          onSelect={onSelectAgent}
          budget={subagentBudget}
          onBudgetChange={onSubagentBudgetChange}
          embedded
        />
      ),
    });
  }

  if (onSelectPartner) {
    resourceItems.push({
      key: "partner", group: "Answer preferences",
      summary: partnerName || t("None"), onClear: () => onSelectPartner(null),
      label: t("Ask partner"), icon: UserRound, count: selectedPartner ? 1 : 0,
      node: <PartnerSelector partners={partners} selected={selectedPartner} onSelect={onSelectPartner}
        loading={partnersLoading} error={partnerLoadError} />,
    });
  }

  if (onSelectPartnerGroup) {
    resourceItems.push({
      key: "partner_group", group: "Answer preferences",
      summary: partnerGroupName || t("None"),
      onClear: () => onSelectPartnerGroup(null),
      label: t("Organize partner discussion"), icon: Users,
      count: selectedPartnerGroup ? 1 : 0,
      node: <PartnerGroupSelector groups={partnerGroups} selected={selectedPartnerGroup}
        onSelect={onSelectPartnerGroup} error={groupLoadError} loading={groupsLoading} />,
    });
  }


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
          className={`${styles.surface} relative rounded-[26px] border bg-[var(--card)] shadow-[0_1px_2px_rgba(0,0,0,0.025),0_10px_28px_-10px_rgba(0,0,0,0.08)] transition-colors ${
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

          <SelectedResources items={contextTreeItems}/>
          <AttachmentProcessingStatus items={attachmentProcessing} />
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
            onSelectReadingPicker={onSelectReadingPicker}
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
            placeholderCompletion={inputPlaceholderCompletion}
            minHeight={hasMessages ? 28 : 64}
          />

          {attachmentError && (
            <div className="px-4 pb-2 text-[11px] text-red-600">
              {attachmentError}
            </div>
          )}

          {/* Claude-style chrome-free toolbar: no divider against the input
              area, no pill borders — quiet text/icon buttons that surface
              on hover. */}
          <div className="px-3 pb-2 pt-0.5">
            <div className={styles.toolbar}>
              <div className={styles.context}>
                {showCapabilityChip && (
                  <div className="relative min-w-0 max-w-full">
                    <button
                      ref={capBtnRef}
                      aria-haspopup="menu"
                      aria-expanded={capMenuOpen}
                      onClick={() => onSetCapMenuOpen((v) => !v)}
                      aria-label={t(activeCap.label)}
                      title={t(activeCap.label)}
                      className={`inline-flex h-8 max-w-full items-center rounded-lg px-2 text-[14px] font-medium transition-[background-color,color,transform] duration-150 active:scale-[0.97] ${
                        capMenuOpen
                          ? "bg-[var(--primary)]/10 text-[var(--primary)]"
                          : "text-[var(--foreground)] hover:bg-[var(--muted)]/55"
                      }`}
                    >
                      <CapIcon size={16} strokeWidth={1.7} className="shrink-0" />
                      <span className="ml-1.5 inline-flex min-w-0 items-center gap-1.5 whitespace-nowrap">
                        <span className="min-w-0 truncate">{t(activeCap.label)}</span>
                        <ChevronDown size={13} strokeWidth={2} className={`shrink-0 transition-transform duration-200 ${capMenuOpen ? "rotate-180" : ""}`} />
                      </span>
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
                )}

                {onSelectWorkspace ? (
                  <WorkspacePill
                    collapsible
                    workspaces={workspaces}
                    workspaceId={workspaceId}
                    onSelect={onSelectWorkspace}
                    disabled={isStreaming || workspacePending}
                    readOnly={hasMessages}
                    error={workspaceError}
                  />
                ) : null}

                {onSelectCourse ? (
                  <RailSlot
                    onClear={courseId ? () => onSelectCourse("") : undefined}
                    clearLabel={t("Clear course")}
                  >
                    <CoursePill
                      courses={courses}
                      courseId={courseId}
                      onSelect={onSelectCourse}
                      needsCourse={activeCap.value === "course_study"}
                    />
                  </RailSlot>
                ) : null}

                {
                  <ComposerResources
                    selectedCount={contextTreeItems.length}
                    items={resourceItems}
                    open={spaceMenuOpen || Boolean(personaSelectorOpen)}
                    onOpenChange={(open) => {
                      onSetSpaceMenuOpen(open);
                      if (!open) onPersonaSelectorOpenChange?.(false);
                    }}
                    requestedKey={personaSelectorOpen ? "persona" : undefined}
                    onBack={() => {
                      if (personaSelectorOpen) {
                        onSetSpaceMenuOpen(true);
                        onPersonaSelectorOpenChange?.(false);
                      }
                    }}
                    triggerRef={spaceBtnRef}
                    panelRef={spaceMenuRef}
                    materials={(query) => (
                      <ChatSpaceMenu
                        variant="resources"
                        query={query}
                        selectedCounts={spaceSelectionCounts}
                        knowledgeAvailable={false}
                        personaAvailable={!onPersonaSelectionChange}
                        agentsAvailable={agentsAvailable}
                        readingAvailable={Boolean(onSelectReadingPicker)}
                        onSelectItem={(key) => {
                          onSetSpaceMenuOpen(false);
                          onPersonaSelectorOpenChange?.(false);
                          if (key === "attach") handlePickFiles();
                          else if (key === "chat_history")
                            onSelectHistoryPicker();
                          else if (key === "my_agents") onSelectAgentsPicker();
                          else if (key === "books") onSelectBookPicker();
                          else if (key === "reading") onSelectReadingPicker?.();
                          else if (key === "notebooks") onSelectNotebookPicker();
                          else if (key === "question_bank")
                            onSelectQuestionBankPicker();
                          else if (key === "persona") onSelectPersonaPicker();
                          else if (key === "memory") onSelectMemoryPicker();
                        }}
                      />
                    )}
                  />
                }

              </div>

              <div className={styles.actions}>
                <ModelSelector
                  options={llmOptions}
                  activeDefault={activeLLMDefault}
                  value={llmSelection}
                  loading={llmOptionsLoading}
                  error={llmOptionsError}
                  onChange={onSelectLLM}
                  onRefresh={onRefreshLLMOptions}
                />

                {contextBudget ? <ContextBudgetChip budget={contextBudget} /> : null}

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
