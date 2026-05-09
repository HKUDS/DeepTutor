"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  ArrowRight,
  ArrowUpRight,
  Bold,
  Braces,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Code2,
  Download,
  Eraser,
  FileText,
  Heading1,
  Heading2,
  Heading3,
  Heading4,
  Heading5,
  Heading6,
  Highlighter,
  Image as ImageIcon,
  Italic,
  Link as LinkIcon,
  List,
  ListOrdered,
  ListTodo,
  Loader2,
  Minus,
  NotebookPen,
  Quote,
  Redo2,
  Strikethrough,
  Table2,
  Undo2,
  WandSparkles,
  Workflow,
} from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { apiUrl } from "@/lib/api";
import { listKnowledgeBases } from "@/lib/knowledge-api";
import {
  getCoWriterDocument,
  updateCoWriterDocument,
} from "@/lib/co-writer-api";
import { notifyCoWriterChanged } from "@/lib/co-writer-events";
import SaveToNotebookModal, {
  type NotebookSavePayload,
} from "@/components/notebook/SaveToNotebookModal";
import { CO_WRITER_SAMPLE_TEMPLATE } from "../sampleTemplate";

const MarkdownRenderer = dynamic(
  () => import("@/components/common/MarkdownRenderer"),
  {
    ssr: false,
  },
);

type EditAction = "rewrite" | "shorten" | "expand";
type SelectionMode = EditAction | "none";
type SourceOption = "none" | "rag" | "web";
type ConfirmAction = "clear" | "template";
type ToolName =
  | "brainstorm"
  | "rag"
  | "web_search"
  | "code_execution"
  | "reason"
  | "paper_search";

interface KnowledgeBase {
  name: string;
  is_default?: boolean;
}

const SPLIT_RATIO_KEY = "deeptutor.co_writer.split_ratio";
const SYNC_SCROLL_KEY = "deeptutor.co_writer.sync_scroll";
const LOCAL_DRAFT_PREFIX = "deeptutor.co_writer.draft.";
const AUTOSAVE_DEBOUNCE_MS = 1500;
const MIN_PANEL_RATIO = 0.18;
const MAX_PANEL_RATIO = 0.82;

const ACTION_LABELS: Record<EditAction, string> = {
  rewrite: "Rewrite",
  shorten: "Shorten",
  expand: "Expand",
};

const TOOL_OPTIONS: Array<{ name: ToolName; label: string }> = [
  { name: "brainstorm", label: "Brainstorm" },
  { name: "rag", label: "RAG" },
  { name: "web_search", label: "Web Search" },
  { name: "code_execution", label: "Code" },
  { name: "reason", label: "Reason" },
  { name: "paper_search", label: "Arxiv Search" },
];

const MODE_OPTIONS: Array<{ value: SelectionMode; label: string }> = [
  { value: "none", label: "None" },
  { value: "shorten", label: "Shorten" },
  { value: "expand", label: "Expand" },
  { value: "rewrite", label: "Rewrite" },
];

interface ToolbarItem {
  id: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
  title: string;
  snippet?: string;
  type?: "separator";
  action?: () => void;
}

interface SelectedRange {
  start: number;
  end: number;
  text: string;
  snapshot: string;
}

interface SelectionPopoverState {
  visible: boolean;
  top: number;
  left: number;
}

interface SelectionToolTrace {
  kind?: "tool_call" | "tool_result";
  name: string;
  arguments: Record<string, unknown>;
  result: string;
  success: boolean;
  sources: Array<Record<string, unknown>>;
  metadata: Record<string, unknown>;
}

interface SelectionTraceData {
  thinking: string;
  toolTraces: SelectionToolTrace[];
  response: string;
}

interface StreamTraceEvent {
  type: string;
  stage?: string;
  content?: string;
  metadata?: Record<string, unknown>;
}

interface StreamEditResult {
  edited_text?: string;
}

export default function CoWriterPage() {
  const { t } = useTranslation();
  const router = useRouter();
  const params = useParams<{ docId?: string | string[] }>();
  const docId = useMemo(() => {
    const raw = params?.docId;
    if (!raw) return "";
    return Array.isArray(raw) ? (raw[0] ?? "") : raw;
  }, [params]);
  const draftStorageKey = useMemo(
    () => (docId ? `${LOCAL_DRAFT_PREFIX}${docId}` : null),
    [docId],
  );
  const lastSavedContentRef = useRef<string>("");
  const autosaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isUnmountedRef = useRef(false);
  const [docTitle, setDocTitle] = useState<string>("");
  const [isEditingTitle, setIsEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState<string>("");
  const titleInputRef = useRef<HTMLInputElement>(null);
  const [docNotFound, setDocNotFound] = useState(false);
  const [isLoadingDoc, setIsLoadingDoc] = useState(true);
  const [isSavingDoc, setIsSavingDoc] = useState(false);
  const [lastSavedAt, setLastSavedAt] = useState<number | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const previewScrollRef = useRef<HTMLDivElement>(null);
  const splitContainerRef = useRef<HTMLDivElement>(null);
  const scrollSyncSourceRef = useRef<"editor" | "preview" | null>(null);
  const scrollSyncResetTimerRef = useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );
  const selectionPopoverRef = useRef<HTMLDivElement>(null);
  const preserveSelectionTraceRef = useRef(false);
  const selectionRequestAbortRef = useRef<AbortController | null>(null);
  const selectionDragStateRef = useRef<{
    offsetX: number;
    offsetY: number;
  } | null>(null);
  const [markdown, setMarkdown] = useState("");
  const [instruction, setInstruction] = useState("");
  const [action, setAction] = useState<EditAction>("rewrite");
  const [source, setSource] = useState<SourceOption>("none");
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [kbName, setKbName] = useState("");
  const [isEditing, setIsEditing] = useState(false);
  const [isAutoMarking, setIsAutoMarking] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [pendingConfirmAction, setPendingConfirmAction] =
    useState<ConfirmAction | null>(null);
  const [notebookSavePayload, setNotebookSavePayload] =
    useState<NotebookSavePayload | null>(null);
  const [selectedRange, setSelectedRange] = useState<SelectedRange | null>(
    null,
  );
  const [selectionPopover, setSelectionPopover] =
    useState<SelectionPopoverState>({
      visible: false,
      top: 0,
      left: 0,
    });
  const [selectionInstruction, setSelectionInstruction] = useState("");
  const [selectionMode, setSelectionMode] = useState<SelectionMode>("rewrite");
  const [selectionTools, setSelectionTools] = useState<ToolName[]>([]);
  const [isToolMenuOpen, setIsToolMenuOpen] = useState(false);
  const [isModeMenuOpen, setIsModeMenuOpen] = useState(false);
  const [selectionTrace, setSelectionTrace] =
    useState<SelectionTraceData | null>(null);
  const [isTraceExpanded, setIsTraceExpanded] = useState(true);
  const [selectionPopoverPinned, setSelectionPopoverPinned] = useState(false);
  const [isDraggingSelectionPopover, setIsDraggingSelectionPopover] =
    useState(false);

  const [editorCollapsed, setEditorCollapsed] = useState(false);
  const [previewCollapsed, setPreviewCollapsed] = useState(false);
  const [editorRatio, setEditorRatio] = useState(0.5);
  const [isResizingSplit, setIsResizingSplit] = useState(false);
  const [syncScrollEnabled, setSyncScrollEnabled] = useState(true);
  const showEditor = !editorCollapsed;
  const showPreview = !previewCollapsed;

  const [undoStack, setUndoStack] = useState<string[]>([]);
  const [redoStack, setRedoStack] = useState<string[]>([]);
  const undoTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingUndoSnapshotRef = useRef<string | null>(null);
  const [hasLoadedDraft, setHasLoadedDraft] = useState(false);

  useEffect(() => {
    const savedRatio = window.localStorage.getItem(SPLIT_RATIO_KEY);
    if (savedRatio) {
      const parsed = Number.parseFloat(savedRatio);
      if (Number.isFinite(parsed)) {
        setEditorRatio(
          Math.min(MAX_PANEL_RATIO, Math.max(MIN_PANEL_RATIO, parsed)),
        );
      }
    }

    const savedSync = window.localStorage.getItem(SYNC_SCROLL_KEY);
    if (savedSync !== null) {
      setSyncScrollEnabled(savedSync !== "0");
    }
  }, []);

  useEffect(() => {
    isUnmountedRef.current = false;
    return () => {
      isUnmountedRef.current = true;
    };
  }, []);

  // Load document content from server when docId is available.
  useEffect(() => {
    if (!docId) return;
    let cancelled = false;
    setIsLoadingDoc(true);
    setDocNotFound(false);
    setHasLoadedDraft(false);
    (async () => {
      try {
        const document = await getCoWriterDocument(docId);
        if (cancelled) return;
        // Prefer server content; fall back to local draft buffer if newer (rare:
        // page reloaded before debounced autosave completed).
        let content = document.content ?? "";
        if (draftStorageKey) {
          try {
            const localDraft = window.localStorage.getItem(draftStorageKey);
            if (localDraft !== null && localDraft !== content) {
              content = localDraft;
            }
          } catch {
            /* ignore */
          }
        }
        setMarkdown(content);
        setDocTitle(document.title || "");
        lastSavedContentRef.current = document.content ?? "";
        setLastSavedAt(
          document.updated_at ? document.updated_at * 1000 : Date.now(),
        );
        setHasLoadedDraft(true);
      } catch (err) {
        if (cancelled) return;
        const msg = err instanceof Error ? err.message : String(err);
        if (msg.includes("404")) {
          setDocNotFound(true);
        } else {
          setError(msg);
        }
      } finally {
        if (!cancelled) {
          setIsLoadingDoc(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [docId, draftStorageKey]);

  // Mirror the in-flight content to localStorage so an accidental reload
  // doesn't lose unsaved characters before autosave fires.
  useEffect(() => {
    if (!hasLoadedDraft || !draftStorageKey) return;
    try {
      window.localStorage.setItem(draftStorageKey, markdown);
    } catch {
      /* ignore quota errors */
    }
  }, [hasLoadedDraft, draftStorageKey, markdown]);

  // Debounced autosave to the server.
  useEffect(() => {
    if (!hasLoadedDraft || !docId) return;
    if (markdown === lastSavedContentRef.current) return;
    if (autosaveTimerRef.current) clearTimeout(autosaveTimerRef.current);
    autosaveTimerRef.current = setTimeout(async () => {
      try {
        setIsSavingDoc(true);
        const updated = await updateCoWriterDocument(docId, {
          content: markdown,
        });
        if (isUnmountedRef.current) return;
        lastSavedContentRef.current = markdown;
        setDocTitle(updated.title || "");
        setLastSavedAt(
          updated.updated_at ? updated.updated_at * 1000 : Date.now(),
        );
        if (draftStorageKey) {
          try {
            window.localStorage.removeItem(draftStorageKey);
          } catch {
            /* ignore */
          }
        }
        notifyCoWriterChanged();
      } catch (err) {
        if (isUnmountedRef.current) return;
        const msg = err instanceof Error ? err.message : String(err);
        setError(msg);
      } finally {
        if (!isUnmountedRef.current) {
          setIsSavingDoc(false);
        }
      }
    }, AUTOSAVE_DEBOUNCE_MS);
    return () => {
      if (autosaveTimerRef.current) {
        clearTimeout(autosaveTimerRef.current);
        autosaveTimerRef.current = null;
      }
    };
  }, [docId, hasLoadedDraft, markdown, draftStorageKey]);

  useEffect(() => {
    window.localStorage.setItem(SPLIT_RATIO_KEY, String(editorRatio));
  }, [editorRatio]);

  useEffect(() => {
    window.localStorage.setItem(SYNC_SCROLL_KEY, syncScrollEnabled ? "1" : "0");
  }, [syncScrollEnabled]);

  useEffect(() => {
    // Drop the cached editor line positions when the viewport changes width;
    // wrapping behavior depends on it.
    const handleResize = () => {
      editorYCacheRef.current = null;
    };
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  // Editor inner width can change without a window resize (collapsing the
  // preview pane, dragging the splitter, etc). Invalidate the y cache so the
  // mirror remeasures with the new wrap width.
  useEffect(() => {
    editorYCacheRef.current = null;
  }, [editorRatio, editorCollapsed, previewCollapsed]);

  useEffect(() => {
    (async () => {
      try {
        const list = await listKnowledgeBases();
        setKnowledgeBases(list);
        const defaultKb =
          list.find((k: KnowledgeBase) => k.is_default)?.name ||
          list[0]?.name ||
          "";
        setKbName((prev) => prev || defaultKb);
      } catch {
        setKnowledgeBases([]);
      }
    })();
  }, []);

  const pushUndo = useCallback((prev: string) => {
    setUndoStack((s) => [...s.slice(-50), prev]);
    setRedoStack([]);
  }, []);

  const commitPendingTypingUndo = useCallback(() => {
    if (undoTimerRef.current) {
      clearTimeout(undoTimerRef.current);
      undoTimerRef.current = null;
    }
    const snapshot = pendingUndoSnapshotRef.current;
    pendingUndoSnapshotRef.current = null;
    if (snapshot !== null && snapshot !== markdown) {
      pushUndo(snapshot);
    }
  }, [markdown, pushUndo]);

  const handleMarkdownChange = useCallback(
    (value: string) => {
      if (undoTimerRef.current) clearTimeout(undoTimerRef.current);
      if (pendingUndoSnapshotRef.current === null) {
        pendingUndoSnapshotRef.current = markdown;
      }
      const snapshot = pendingUndoSnapshotRef.current;
      undoTimerRef.current = setTimeout(() => {
        pendingUndoSnapshotRef.current = null;
        undoTimerRef.current = null;
        if (snapshot !== null && snapshot !== value) {
          pushUndo(snapshot);
        }
      }, 400);
      setMarkdown(value);
    },
    [markdown, pushUndo],
  );

  const handleUndo = useCallback(() => {
    if (undoTimerRef.current) {
      clearTimeout(undoTimerRef.current);
      undoTimerRef.current = null;
    }
    const pendingSnapshot = pendingUndoSnapshotRef.current;
    pendingUndoSnapshotRef.current = null;
    if (pendingSnapshot !== null && pendingSnapshot !== markdown) {
      setRedoStack((s) => [...s, markdown]);
      setMarkdown(pendingSnapshot);
      return;
    }

    if (undoStack.length === 0) return;
    const prev = undoStack[undoStack.length - 1];
    setRedoStack((s) => [...s, markdown]);
    setUndoStack((s) => s.slice(0, -1));
    setMarkdown(prev);
  }, [undoStack, markdown]);

  const handleRedo = useCallback(() => {
    if (redoStack.length === 0) return;
    const next = redoStack[redoStack.length - 1];
    setUndoStack((s) => [...s, markdown]);
    setRedoStack((s) => s.slice(0, -1));
    setMarkdown(next);
  }, [redoStack, markdown]);

  const handleEditorKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
      const key = event.key.toLowerCase();
      const hasUndoModifier = event.metaKey || event.ctrlKey;
      if (!hasUndoModifier || event.altKey) return;

      if (key === "z" && event.shiftKey) {
        event.preventDefault();
        handleRedo();
        return;
      }

      if (key === "z") {
        event.preventDefault();
        handleUndo();
        return;
      }

      if (key === "y") {
        event.preventDefault();
        handleRedo();
      }
    },
    [handleRedo, handleUndo],
  );

  const startEditingTitle = useCallback(() => {
    if (isLoadingDoc) return;
    setTitleDraft(docTitle);
    setIsEditingTitle(true);
  }, [docTitle, isLoadingDoc]);

  const cancelEditingTitle = useCallback(() => {
    setIsEditingTitle(false);
    setTitleDraft("");
  }, []);

  const commitTitle = useCallback(async () => {
    if (!docId) {
      setIsEditingTitle(false);
      return;
    }
    const next = titleDraft.trim();
    const current = (docTitle || "").trim();
    setIsEditingTitle(false);
    if (next === current) return;
    try {
      setIsSavingDoc(true);
      const updated = await updateCoWriterDocument(docId, { title: next });
      if (isUnmountedRef.current) return;
      setDocTitle(updated.title || "");
      setLastSavedAt(
        updated.updated_at ? updated.updated_at * 1000 : Date.now(),
      );
      notifyCoWriterChanged();
    } catch (err) {
      if (isUnmountedRef.current) return;
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (!isUnmountedRef.current) setIsSavingDoc(false);
    }
  }, [docId, docTitle, titleDraft]);

  useEffect(() => {
    if (!isEditingTitle) return;
    const input = titleInputRef.current;
    if (!input) return;
    input.focus();
    input.select();
  }, [isEditingTitle]);

  const wordCount = useMemo(() => {
    const trimmed = markdown.trim();
    if (!trimmed) return 0;
    return trimmed.split(/\s+/).length;
  }, [markdown]);

  const charCount = markdown.length;

  const hideSelectionPopover = useCallback(() => {
    selectionRequestAbortRef.current?.abort();
    selectionRequestAbortRef.current = null;
    selectionDragStateRef.current = null;
    setSelectionPopoverPinned(false);
    setIsDraggingSelectionPopover(false);
    setSelectionPopover((prev) => ({ ...prev, visible: false }));
    setSelectedRange(null);
    setSelectionInstruction("");
    setIsToolMenuOpen(false);
    setIsModeMenuOpen(false);
    setSelectionTrace(null);
    setIsTraceExpanded(true);
  }, []);

  const measureSelectionAnchor = useCallback(
    (textarea: HTMLTextAreaElement, index: number) => {
      const rect = textarea.getBoundingClientRect();
      const computed = window.getComputedStyle(textarea);
      const mirror = document.createElement("div");
      const properties = [
        "box-sizing",
        "width",
        "height",
        "overflow-x",
        "overflow-y",
        "border-top-width",
        "border-right-width",
        "border-bottom-width",
        "border-left-width",
        "padding-top",
        "padding-right",
        "padding-bottom",
        "padding-left",
        "font-style",
        "font-variant",
        "font-weight",
        "font-stretch",
        "font-size",
        "font-size-adjust",
        "line-height",
        "font-family",
        "letter-spacing",
        "text-align",
        "text-transform",
        "text-indent",
        "text-decoration",
        "tab-size",
      ];

      properties.forEach((property) => {
        mirror.style.setProperty(property, computed.getPropertyValue(property));
      });

      mirror.style.position = "fixed";
      mirror.style.top = `${rect.top}px`;
      mirror.style.left = `${rect.left}px`;
      mirror.style.whiteSpace = "pre-wrap";
      mirror.style.overflowWrap = "break-word";
      mirror.style.visibility = "hidden";
      mirror.style.pointerEvents = "none";

      mirror.textContent = textarea.value.slice(0, index);

      const marker = document.createElement("span");
      marker.textContent = textarea.value.slice(index) || ".";
      mirror.appendChild(marker);

      document.body.appendChild(mirror);

      const top = rect.top + marker.offsetTop - textarea.scrollTop;
      const left = rect.left + marker.offsetLeft - textarea.scrollLeft;

      document.body.removeChild(mirror);
      return { top, left };
    },
    [],
  );

  const updateSelectionPopover = useCallback(() => {
    const textarea = textareaRef.current;
    if (!textarea) {
      hideSelectionPopover();
      return;
    }

    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    if (start === end) {
      hideSelectionPopover();
      return;
    }

    const text = textarea.value.slice(start, end);
    if (!text.trim()) {
      hideSelectionPopover();
      return;
    }

    const anchor = measureSelectionAnchor(textarea, end);
    const width = 360;
    const left = Math.min(
      Math.max(anchor.left - width / 2, 12),
      window.innerWidth - width - 12,
    );
    const top = Math.max(anchor.top - 98, 12);

    setSelectedRange((prev) => {
      const changed =
        !prev ||
        prev.start !== start ||
        prev.end !== end ||
        prev.text !== text ||
        prev.snapshot !== markdown;
      if (changed) {
        setSelectionPopoverPinned(false);
        if (preserveSelectionTraceRef.current) {
          preserveSelectionTraceRef.current = false;
        } else {
          setSelectionTrace(null);
        }
        setIsTraceExpanded(true);
      }
      return { start, end, text, snapshot: markdown };
    });
    setSelectionPopover((prev) => ({
      visible: true,
      top: selectionPopoverPinned ? prev.top : top,
      left: selectionPopoverPinned ? prev.left : left,
    }));
  }, [
    hideSelectionPopover,
    markdown,
    measureSelectionAnchor,
    selectionPopoverPinned,
  ]);

  const insertSnippet = useCallback(
    (snippet: string) => {
      commitPendingTypingUndo();
      pushUndo(markdown);
      const textarea = textareaRef.current;
      if (!textarea) {
        setMarkdown((prev) => `${prev}\n${snippet}`);
        return;
      }
      const start = textarea.selectionStart;
      const end = textarea.selectionEnd;
      const next = `${markdown.slice(0, start)}${snippet}${markdown.slice(end)}`;
      setMarkdown(next);
      requestAnimationFrame(() => {
        textarea.focus();
        const cursor = start + snippet.length;
        textarea.setSelectionRange(cursor, cursor);
      });
    },
    [commitPendingTypingUndo, markdown, pushUndo],
  );

  const clearDocument = useCallback(() => {
    if (!markdown) {
      setStatus(t("Draft is already empty."));
      setError("");
      return;
    }
    commitPendingTypingUndo();
    pushUndo(markdown);
    setMarkdown("");
    setStatus(t("Draft cleared. Press Ctrl/Cmd+Z or use Undo to restore it."));
    setError("");
  }, [commitPendingTypingUndo, markdown, pushUndo, t]);

  const loadExampleTemplate = useCallback(() => {
    if (markdown === CO_WRITER_SAMPLE_TEMPLATE) {
      setStatus(t("Example template is already loaded."));
      setError("");
      return;
    }

    commitPendingTypingUndo();
    pushUndo(markdown);
    setMarkdown(CO_WRITER_SAMPLE_TEMPLATE);
    setStatus(
      t("Loaded example template. Press Ctrl/Cmd+Z or use Undo to restore it."),
    );
    setError("");
  }, [commitPendingTypingUndo, markdown, pushUndo, t]);

  const requestClearDocument = useCallback(() => {
    if (!markdown) {
      clearDocument();
      return;
    }
    setPendingConfirmAction("clear");
  }, [clearDocument, markdown]);

  const requestLoadExampleTemplate = useCallback(() => {
    if (markdown === CO_WRITER_SAMPLE_TEMPLATE) {
      loadExampleTemplate();
      return;
    }
    setPendingConfirmAction("template");
  }, [loadExampleTemplate, markdown]);

  const confirmActionCopy = useMemo(() => {
    if (pendingConfirmAction === "clear") {
      return {
        title: t("Clear this draft?"),
        description: t(
          "This will empty the editor. The previous content is kept in Undo until you leave this draft.",
        ),
        confirmLabel: t("Clear draft"),
        tone: "danger" as const,
        onConfirm: clearDocument,
      };
    }

    if (pendingConfirmAction === "template") {
      return {
        title: t("Replace with the example template?"),
        description: t(
          "This will replace the current editor content. The previous content is kept in Undo until you leave this draft.",
        ),
        confirmLabel: t("Load template"),
        tone: "warning" as const,
        onConfirm: loadExampleTemplate,
      };
    }

    return null;
  }, [clearDocument, loadExampleTemplate, pendingConfirmAction, t]);

  const handleDownload = () => {
    const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "co-writer.md";
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const handleOpenSaveToNotebook = useCallback(() => {
    if (!markdown.trim()) {
      setError(t("Add some content before saving to a notebook."));
      return;
    }
    const fallbackTitle = t("Untitled Co-Writer Document");
    const titleForRecord = (docTitle || fallbackTitle).trim() || fallbackTitle;
    setNotebookSavePayload({
      recordType: "co_writer",
      title: titleForRecord,
      userQuery: titleForRecord,
      output: markdown,
      metadata: {
        source: "co_writer",
        doc_id: docId,
      },
      kbName: kbName || null,
    });
  }, [docId, docTitle, kbName, markdown, t]);

  const replaceSelectedText = useCallback(
    (range: SelectedRange, replacement: string) => {
      pushUndo(range.snapshot);
      const next = `${range.snapshot.slice(0, range.start)}${replacement}${range.snapshot.slice(range.end)}`;
      preserveSelectionTraceRef.current = true;
      setMarkdown(next);
      setSelectedRange({
        start: range.start,
        end: range.start + replacement.length,
        text: replacement,
        snapshot: next,
      });

      requestAnimationFrame(() => {
        const textarea = textareaRef.current;
        if (!textarea) return;
        textarea.focus();
        textarea.setSelectionRange(
          range.start,
          range.start + replacement.length,
        );
        updateSelectionPopover();
      });
    },
    [pushUndo, updateSelectionPopover],
  );

  const toggleSelectionTool = useCallback((tool: ToolName) => {
    setSelectionTools((prev) =>
      prev.includes(tool)
        ? prev.filter((item) => item !== tool)
        : [...prev, tool],
    );
  }, []);

  const handleSelectionPopoverDragStart = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      const target = event.target as HTMLElement;
      if (
        target.closest(
          "input, textarea, button, select, option, a, [data-no-drag='true']",
        )
      ) {
        return;
      }
      event.preventDefault();
      selectionDragStateRef.current = {
        offsetX: event.clientX - selectionPopover.left,
        offsetY: event.clientY - selectionPopover.top,
      };
      setSelectionPopoverPinned(true);
      setIsDraggingSelectionPopover(true);
      setIsToolMenuOpen(false);
      setIsModeMenuOpen(false);
    },
    [selectionPopover.left, selectionPopover.top],
  );

  const updateSelectionTraceFromEvent = useCallback(
    (event: StreamTraceEvent) => {
      setSelectionTrace((prev) => {
        const current = prev ?? { thinking: "", toolTraces: [], response: "" };
        if (event.type === "thinking") {
          return {
            ...current,
            thinking: `${current.thinking}${event.content || ""}`,
          };
        }
        if (event.type === "tool_call") {
          return {
            ...current,
            toolTraces: [
              ...current.toolTraces,
              {
                kind: "tool_call",
                name: String(event.content || ""),
                arguments:
                  event.metadata && typeof event.metadata.args === "object"
                    ? (event.metadata.args as Record<string, unknown>)
                    : {},
                result: "",
                success: true,
                sources: [],
                metadata: event.metadata || {},
              },
            ],
          };
        }
        if (event.type === "tool_result") {
          return {
            ...current,
            toolTraces: [
              ...current.toolTraces,
              {
                kind: "tool_result",
                name: String(event.metadata?.tool || "result"),
                arguments: {},
                result: String(event.content || ""),
                success: true,
                sources: [],
                metadata: event.metadata || {},
              },
            ],
          };
        }
        if (event.type === "content" && event.stage === "responding") {
          return {
            ...current,
            response: `${current.response}${event.content || ""}`,
          };
        }
        return current;
      });
    },
    [],
  );

  const applyReactSelectionEdit = useCallback(async () => {
    if (!selectedRange) {
      setError(t("Please select a text passage first."));
      return;
    }

    if (selectionMode === "none" && !selectionInstruction.trim()) {
      setError(t("Please enter an instruction or choose a mode."));
      return;
    }

    setIsEditing(true);
    setError("");
    setStatus("");
    setSelectionTrace({ thinking: "", toolTraces: [], response: "" });
    setIsTraceExpanded(true);
    selectionRequestAbortRef.current?.abort();
    const controller = new AbortController();
    selectionRequestAbortRef.current = controller;

    try {
      const response = await fetch(
        apiUrl("/api/v1/co_writer/edit_react/stream"),
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          signal: controller.signal,
          body: JSON.stringify({
            selected_text: selectedRange.text,
            instruction: selectionInstruction.trim(),
            mode: selectionMode,
            tools: selectionTools,
            kb_name: selectionTools.includes("rag") ? kbName || null : null,
          }),
        },
      );
      if (!response.ok) {
        throw new Error(
          (await response.text()) || "Failed to edit selected text.",
        );
      }
      if (!response.body) {
        throw new Error("Streaming response body is missing.");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let finalResult: StreamEditResult | undefined;

      const processSseChunk = (chunk: string) => {
        const lines = chunk.split(/\r?\n/);
        let eventName = "message";
        const dataLines: string[] = [];
        for (const line of lines) {
          if (line.startsWith("event:")) {
            eventName = line.slice(6).trim();
          } else if (line.startsWith("data:")) {
            dataLines.push(line.slice(5).trimStart());
          }
        }
        if (dataLines.length === 0) return;
        const payload = JSON.parse(dataLines.join("\n"));
        if (eventName === "stream") {
          updateSelectionTraceFromEvent(payload as StreamTraceEvent);
          return;
        }
        if (eventName === "result") {
          finalResult = payload as StreamEditResult;
          return;
        }
        if (eventName === "error") {
          throw new Error(
            String(payload?.detail || "Failed to edit selected text."),
          );
        }
      };

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        while (true) {
          const delimiterIndex = buffer.indexOf("\n\n");
          if (delimiterIndex === -1) break;
          const rawEvent = buffer.slice(0, delimiterIndex);
          buffer = buffer.slice(delimiterIndex + 2);
          processSseChunk(rawEvent);
        }
      }
      buffer += decoder.decode();
      if (buffer.trim()) {
        processSseChunk(buffer.trim());
      }
      if (finalResult === undefined) {
        throw new Error("Did not receive a final edit result.");
      }
      const editedText = finalResult.edited_text ?? "";

      if (markdown !== selectedRange.snapshot) {
        throw new Error(
          "The draft changed before AI edit finished. Please reselect the text and try again.",
        );
      }

      replaceSelectedText(selectedRange, editedText);
      setStatus(t("Applied AI edit to the selection."));
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        return;
      }
      setError(
        err instanceof Error ? err.message : "Failed to edit selected text.",
      );
    } finally {
      selectionRequestAbortRef.current = null;
      setIsEditing(false);
    }
  }, [
    kbName,
    markdown,
    replaceSelectedText,
    selectedRange,
    selectionInstruction,
    selectionMode,
    selectionTools,
    t,
    updateSelectionTraceFromEvent,
  ]);

  const applyEdit = async () => {
    if (!instruction.trim()) {
      setError(t("Please enter an editing instruction first."));
      return;
    }
    setIsEditing(true);
    setError("");
    setStatus("");
    try {
      const response = await fetch(apiUrl("/api/v1/co_writer/edit"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: markdown,
          instruction: instruction.trim(),
          action,
          source: source === "none" ? null : source,
          kb_name: source === "rag" ? kbName || null : null,
        }),
      });
      const data = await response.json();
      if (!response.ok)
        throw new Error(data?.detail || "Failed to edit document.");
      pushUndo(markdown);
      setMarkdown(data.edited_text || "");
      setStatus(
        t("Applied {{action}} to the full draft.", {
          action: t(ACTION_LABELS[action]).toLowerCase(),
        }),
      );
      setIsEditModalOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to edit document.");
    } finally {
      setIsEditing(false);
    }
  };

  const applyAutoMark = async () => {
    setIsAutoMarking(true);
    setError("");
    setStatus("");
    try {
      const response = await fetch(apiUrl("/api/v1/co_writer/automark"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: markdown }),
      });
      const data = await response.json();
      if (!response.ok)
        throw new Error(data?.detail || "Failed to auto-mark document.");
      pushUndo(markdown);
      setMarkdown(data.marked_text || "");
      setStatus(t("Applied auto-mark annotations."));
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to auto-mark document.",
      );
    } finally {
      setIsAutoMarking(false);
    }
  };

  const TOOLBAR: ToolbarItem[] = useMemo(
    () => [
      { id: "undo", icon: Undo2, title: "Undo", action: handleUndo },
      { id: "redo", icon: Redo2, title: "Redo", action: handleRedo },
      { id: "sep-1", icon: Minus, title: "", type: "separator" },
      { id: "h1", icon: Heading1, title: "Heading 1", snippet: "\n# " },
      { id: "h2", icon: Heading2, title: "Heading 2", snippet: "\n## " },
      { id: "h3", icon: Heading3, title: "Heading 3", snippet: "\n### " },
      { id: "h4", icon: Heading4, title: "Heading 4", snippet: "\n#### " },
      { id: "h5", icon: Heading5, title: "Heading 5", snippet: "\n##### " },
      { id: "h6", icon: Heading6, title: "Heading 6", snippet: "\n###### " },
      { id: "sep-2", icon: Minus, title: "", type: "separator" },
      { id: "bold", icon: Bold, title: "Bold", snippet: "**bold**" },
      { id: "italic", icon: Italic, title: "Italic", snippet: "*italic*" },
      {
        id: "strikethrough",
        icon: Strikethrough,
        title: "Strikethrough",
        snippet: "~~text~~",
      },
      { id: "code", icon: Braces, title: "Inline Code", snippet: "`code`" },
      { id: "sep-3", icon: Minus, title: "", type: "separator" },
      { id: "quote", icon: Quote, title: "Blockquote", snippet: "\n> " },
      {
        id: "ul",
        icon: List,
        title: "Bullet List",
        snippet: "\n- Item\n- Item\n",
      },
      {
        id: "ol",
        icon: ListOrdered,
        title: "Numbered List",
        snippet: "\n1. Item\n2. Item\n",
      },
      {
        id: "task",
        icon: ListTodo,
        title: "Task List",
        snippet: "\n- [ ] Task\n- [x] Done\n",
      },
      { id: "sep-4", icon: Minus, title: "", type: "separator" },
      { id: "hr", icon: Minus, title: "Horizontal Rule", snippet: "\n---\n" },
      {
        id: "table",
        icon: Table2,
        title: "Table",
        snippet:
          "\n| Column | Column |\n| ------ | ------ |\n| Cell   | Cell   |\n",
      },
      {
        id: "link",
        icon: LinkIcon,
        title: "Link",
        snippet: "[text](https://)",
      },
      {
        id: "image",
        icon: ImageIcon,
        title: "Image",
        snippet: "![alt](https://)",
      },
      { id: "sep-5", icon: Minus, title: "", type: "separator" },
      {
        id: "codeblock",
        icon: Code2,
        title: "Code Block",
        snippet: '\n```python\nprint("hello")\n```\n',
      },
      {
        id: "mermaid",
        icon: Workflow,
        title: "Mermaid Diagram",
        snippet: "\n```mermaid\nflowchart TD\n  A[Start] --> B[End]\n```\n",
      },
      {
        id: "math",
        icon: () => (
          <span className="text-[11px] font-semibold leading-none">
            &Sigma;
          </span>
        ),
        title: "Math Block",
        snippet: "\n$$\na^2 + b^2 = c^2\n$$\n",
      },
    ],
    [handleUndo, handleRedo],
  );

  useEffect(() => {
    if (!selectionPopover.visible) return;
    const handleViewportChange = () => updateSelectionPopover();
    window.addEventListener("resize", handleViewportChange);
    return () => window.removeEventListener("resize", handleViewportChange);
  }, [selectionPopover.visible, updateSelectionPopover]);

  useEffect(() => {
    if (!selectionPopover.visible) return;
    const handlePointerDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (selectionPopoverRef.current?.contains(target)) return;
      if (textareaRef.current?.contains(target)) return;
      hideSelectionPopover();
    };
    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, [hideSelectionPopover, selectionPopover.visible]);

  useEffect(() => {
    if (!isDraggingSelectionPopover) return;
    const handleMouseMove = (event: MouseEvent) => {
      const dragState = selectionDragStateRef.current;
      const popover = selectionPopoverRef.current;
      if (!dragState || !popover) return;
      const width = popover.offsetWidth || 360;
      const height = popover.offsetHeight || 200;
      const nextLeft = Math.min(
        Math.max(event.clientX - dragState.offsetX, 12),
        window.innerWidth - width - 12,
      );
      const nextTop = Math.min(
        Math.max(event.clientY - dragState.offsetY, 12),
        window.innerHeight - height - 12,
      );
      setSelectionPopover((prev) => ({
        ...prev,
        visible: true,
        top: nextTop,
        left: nextLeft,
      }));
    };
    const handleMouseUp = () => {
      selectionDragStateRef.current = null;
      setIsDraggingSelectionPopover(false);
    };
    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, [isDraggingSelectionPopover]);

  useEffect(() => {
    return () => {
      selectionRequestAbortRef.current?.abort();
      if (scrollSyncResetTimerRef.current) {
        clearTimeout(scrollSyncResetTimerRef.current);
      }
    };
  }, []);

  const handleSplitterPointerDown = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      if (!showEditor || !showPreview) return;
      event.preventDefault();
      setIsResizingSplit(true);
      try {
        (event.target as HTMLDivElement).setPointerCapture(event.pointerId);
      } catch {
        /* ignore */
      }
    },
    [showEditor, showPreview],
  );

  useEffect(() => {
    if (!isResizingSplit) return;
    const handleMove = (event: PointerEvent) => {
      const container = splitContainerRef.current;
      if (!container) return;
      const rect = container.getBoundingClientRect();
      if (rect.width <= 0) return;
      const ratio = (event.clientX - rect.left) / rect.width;
      setEditorRatio(
        Math.min(MAX_PANEL_RATIO, Math.max(MIN_PANEL_RATIO, ratio)),
      );
    };
    const handleEnd = () => setIsResizingSplit(false);
    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleEnd);
    window.addEventListener("pointercancel", handleEnd);
    return () => {
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleEnd);
      window.removeEventListener("pointercancel", handleEnd);
    };
  }, [isResizingSplit]);

  const releaseScrollSyncSource = useCallback(() => {
    if (scrollSyncResetTimerRef.current) {
      clearTimeout(scrollSyncResetTimerRef.current);
    }
    scrollSyncResetTimerRef.current = setTimeout(() => {
      scrollSyncSourceRef.current = null;
    }, 90);
  }, []);

  // ── Line-anchored scroll synchronization ──
  //
  // Each block element rendered in the preview carries a `data-source-line`
  // attribute that points back at its starting line in the markdown source
  // (provided by remark's AST position info). For the editor side we cannot
  // assume `scrollTop / lineHeight = source line` because long lines wrap
  // visually. Instead we build a hidden mirror that mimics the textarea's
  // wrapping and read the real pixel y of every source line. With both sides
  // expressed as pixel coordinates we can interpolate either direction with
  // a single piecewise-linear map.

  // Cache: rebuilding the mirror is moderately expensive, so cache by
  // (markdown content, textarea inner width). Both invalidate the cache.
  const editorYCacheRef = useRef<{
    signature: string;
    ys: Map<number, number>;
  } | null>(null);

  const measureEditorLineYs = useCallback((): Map<number, number> => {
    const editor = textareaRef.current;
    if (!editor) return new Map();
    const value = editor.value;
    const sourceLines = value.split("\n");
    if (sourceLines.length === 0) return new Map();

    const computed = window.getComputedStyle(editor);
    const rect = editor.getBoundingClientRect();
    const mirror = document.createElement("div");

    const properties = [
      "box-sizing",
      "width",
      "border-top-width",
      "border-right-width",
      "border-bottom-width",
      "border-left-width",
      "padding-top",
      "padding-right",
      "padding-bottom",
      "padding-left",
      "font-style",
      "font-variant",
      "font-weight",
      "font-stretch",
      "font-size",
      "font-size-adjust",
      "line-height",
      "font-family",
      "letter-spacing",
      "text-align",
      "text-transform",
      "text-indent",
      "tab-size",
    ];
    for (const property of properties) {
      mirror.style.setProperty(property, computed.getPropertyValue(property));
    }

    mirror.style.position = "fixed";
    mirror.style.top = `${rect.top}px`;
    mirror.style.left = `${rect.left}px`;
    mirror.style.height = "auto";
    mirror.style.maxHeight = "none";
    mirror.style.minHeight = "0";
    mirror.style.whiteSpace = "pre-wrap";
    mirror.style.overflowWrap = "break-word";
    mirror.style.wordBreak = "normal";
    mirror.style.visibility = "hidden";
    mirror.style.pointerEvents = "none";
    mirror.style.zIndex = "-1";

    const spans: HTMLSpanElement[] = [];
    for (let i = 0; i < sourceLines.length; i += 1) {
      if (i > 0) mirror.appendChild(document.createTextNode("\n"));
      const span = document.createElement("span");
      // Empty lines need measurable content for offsetTop to be meaningful.
      span.textContent = sourceLines[i].length > 0 ? sourceLines[i] : "\u200B";
      mirror.appendChild(span);
      spans.push(span);
    }

    document.body.appendChild(mirror);

    const result = new Map<number, number>();
    // span.offsetTop is the y-position of the line within the mirror, which
    // mirrors the textarea's scroll content. Setting `editor.scrollTop` to
    // this value lifts that source line to the top of the visible viewport.
    for (let i = 0; i < spans.length; i += 1) {
      result.set(i + 1, spans[i].offsetTop);
    }

    document.body.removeChild(mirror);
    return result;
  }, []);

  const getEditorLineYs = useCallback((): Map<number, number> => {
    const editor = textareaRef.current;
    if (!editor) return new Map();
    const signature = `${editor.clientWidth}|${markdown}`;
    const cached = editorYCacheRef.current;
    if (cached && cached.signature === signature) return cached.ys;
    const ys = measureEditorLineYs();
    editorYCacheRef.current = { signature, ys };
    return ys;
  }, [markdown, measureEditorLineYs]);

  const collectPreviewLineYs = useCallback((): Map<number, number> => {
    const preview = previewScrollRef.current;
    if (!preview) return new Map();
    const nodes = preview.querySelectorAll<HTMLElement>("[data-source-line]");
    if (nodes.length === 0) return new Map();
    const previewRect = preview.getBoundingClientRect();
    const baseTop = previewRect.top - preview.scrollTop;
    const result = new Map<number, number>();
    for (const el of Array.from(nodes)) {
      const raw = el.getAttribute("data-source-line");
      const line = raw ? Number.parseInt(raw, 10) : NaN;
      if (!Number.isFinite(line)) continue;
      // Keep the first occurrence; nested wrappers often repeat the same line.
      if (result.has(line)) continue;
      const rect = el.getBoundingClientRect();
      result.set(line, rect.top - baseTop);
    }
    return result;
  }, []);

  const buildJointMarkers = useCallback((): Array<{
    line: number;
    editorY: number;
    previewY: number;
  }> => {
    const editorYs = getEditorLineYs();
    const previewYs = collectPreviewLineYs();
    if (editorYs.size === 0 || previewYs.size === 0) return [];

    const lines = Array.from(previewYs.keys())
      .filter((line) => editorYs.has(line))
      .sort((a, b) => a - b);

    const editor = textareaRef.current;
    const preview = previewScrollRef.current;
    const markers: Array<{ line: number; editorY: number; previewY: number }> =
      [];
    for (const line of lines) {
      const editorY = editorYs.get(line);
      const previewY = previewYs.get(line);
      if (typeof editorY !== "number" || typeof previewY !== "number") continue;
      markers.push({ line, editorY, previewY });
    }

    // Anchor the very top so we don't snap to the first heading when the user
    // is still above it.
    if (
      markers.length === 0 ||
      markers[0].editorY > 0 ||
      markers[0].previewY > 0
    ) {
      markers.unshift({ line: 0, editorY: 0, previewY: 0 });
    }

    // Anchor the bottom so the bottom of the document matches.
    if (editor && preview) {
      const editorMax = Math.max(0, editor.scrollHeight - editor.clientHeight);
      const previewMax = Math.max(
        0,
        preview.scrollHeight - preview.clientHeight,
      );
      const last = markers[markers.length - 1];
      if (editorMax > last.editorY + 1 || previewMax > last.previewY + 1) {
        markers.push({
          line: last.line + 1,
          editorY: editorMax,
          previewY: previewMax,
        });
      }
    }

    return markers;
  }, [collectPreviewLineYs, getEditorLineYs]);

  const interpolate = (
    value: number,
    fromA: number,
    fromB: number,
    toA: number,
    toB: number,
  ): number => {
    if (fromA === fromB) return toA;
    const ratio = (value - fromA) / (fromB - fromA);
    return toA + (toB - toA) * ratio;
  };

  const handleEditorScrollSync = useCallback(() => {
    updateSelectionPopover();
    if (!syncScrollEnabled) return;
    if (scrollSyncSourceRef.current === "preview") return;
    const editor = textareaRef.current;
    const preview = previewScrollRef.current;
    if (!editor || !preview) return;
    const markers = buildJointMarkers();
    if (markers.length === 0) return;

    const editorScroll = editor.scrollTop;
    let lower = markers[0];
    let upper = markers[markers.length - 1];
    for (const marker of markers) {
      if (marker.editorY <= editorScroll) lower = marker;
      if (marker.editorY >= editorScroll) {
        upper = marker;
        break;
      }
    }

    const target = interpolate(
      editorScroll,
      lower.editorY,
      upper.editorY,
      lower.previewY,
      upper.previewY,
    );

    const max = preview.scrollHeight - preview.clientHeight;
    const next = Math.max(0, Math.min(max, target));
    if (Math.abs(next - preview.scrollTop) < 0.5) return;
    scrollSyncSourceRef.current = "editor";
    preview.scrollTop = next;
    releaseScrollSyncSource();
  }, [
    buildJointMarkers,
    releaseScrollSyncSource,
    syncScrollEnabled,
    updateSelectionPopover,
  ]);

  const handlePreviewScrollSync = useCallback(() => {
    if (!syncScrollEnabled) return;
    if (scrollSyncSourceRef.current === "editor") return;
    const editor = textareaRef.current;
    const preview = previewScrollRef.current;
    if (!editor || !preview) return;
    const markers = buildJointMarkers();
    if (markers.length === 0) return;

    const previewScroll = preview.scrollTop;
    let lower = markers[0];
    let upper = markers[markers.length - 1];
    for (const marker of markers) {
      if (marker.previewY <= previewScroll) lower = marker;
      if (marker.previewY >= previewScroll) {
        upper = marker;
        break;
      }
    }

    const target = interpolate(
      previewScroll,
      lower.previewY,
      upper.previewY,
      lower.editorY,
      upper.editorY,
    );

    const max = editor.scrollHeight - editor.clientHeight;
    const next = Math.max(0, Math.min(max, target));
    if (Math.abs(next - editor.scrollTop) < 0.5) return;
    scrollSyncSourceRef.current = "preview";
    editor.scrollTop = next;
    releaseScrollSyncSource();
  }, [buildJointMarkers, releaseScrollSyncSource, syncScrollEnabled]);

  // Mermaid diagrams, images, and KaTeX render asynchronously, so the preview's
  // scrollHeight (and the y position of every marker after them) shifts well
  // after the initial render. Without intervention, the user's last alignment
  // becomes stale and the next scroll feels "jumpy" because all the markers
  // moved underneath them. Whenever the preview's intrinsic height changes we
  // re-run the editor→preview sync to put the preview back in lock-step with
  // the editor's current scroll position.
  const handleEditorScrollSyncRef = useRef(handleEditorScrollSync);
  useEffect(() => {
    handleEditorScrollSyncRef.current = handleEditorScrollSync;
  }, [handleEditorScrollSync]);

  useEffect(() => {
    const preview = previewScrollRef.current;
    if (!preview) return;
    const inner = preview.firstElementChild as HTMLElement | null;
    if (!inner) return;

    let raf = 0;
    const schedule = () => {
      if (raf) cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        raf = 0;
        // Treat this as an editor-driven update; we want preview to follow
        // wherever the editor cursor currently anchors us, not the other way
        // around (which would feed back into editor scroll).
        if (scrollSyncSourceRef.current) return;
        handleEditorScrollSyncRef.current();
      });
    };

    const observer = new ResizeObserver(schedule);
    observer.observe(inner);

    // Images load asynchronously and don't always trigger a ResizeObserver
    // update on the parent, so we listen to load events directly too.
    const onLoad = (event: Event) => {
      const target = event.target as HTMLElement | null;
      if (!target) return;
      if (target.tagName === "IMG" || target.tagName === "IFRAME") schedule();
    };
    inner.addEventListener("load", onLoad, true);

    return () => {
      if (raf) cancelAnimationFrame(raf);
      observer.disconnect();
      inner.removeEventListener("load", onLoad, true);
    };
  }, [showPreview]);

  if (docNotFound) {
    return (
      <div className="flex h-full min-h-full flex-col items-center justify-center gap-4 bg-[var(--background)] p-10 text-center">
        <p className="text-lg font-medium text-[var(--foreground)]">
          {t("Document not found")}
        </p>
        <p className="text-sm text-[var(--muted-foreground)]">
          {t("This document may have been deleted, or the link is incorrect.")}
        </p>
        <button
          type="button"
          onClick={() => router.push("/co-writer")}
          className="inline-flex items-center gap-1.5 rounded-md bg-[var(--primary)] px-3 py-1.5 text-sm font-medium text-white transition-opacity hover:opacity-90"
        >
          <ChevronLeft size={14} />
          {t("Back to Co-Writer")}
        </button>
      </div>
    );
  }

  if (isLoadingDoc && !hasLoadedDraft) {
    return (
      <div className="flex h-full min-h-full flex-col items-center justify-center gap-3 bg-[var(--background)] p-10 text-center text-[var(--muted-foreground)]">
        <Loader2 size={20} className="animate-spin" />
        <span className="text-sm">{t("Loading document…")}</span>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-full flex-col overflow-hidden bg-[var(--background)]">
      {/* ── Top bar ── */}
      <header className="flex shrink-0 items-center justify-between border-b border-[var(--border)] px-4 py-1.5">
        <div className="flex min-w-0 items-center gap-3 text-sm text-[var(--muted-foreground)]">
          <button
            type="button"
            onClick={() => router.push("/co-writer")}
            className="inline-flex shrink-0 items-center gap-1 rounded-md px-1.5 py-0.5 text-xs font-medium text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            title={t("Back to documents")}
          >
            <ChevronLeft size={14} strokeWidth={1.7} />
            <span>{t("Co-Writer")}</span>
          </button>
          <span className="text-[var(--muted-foreground)]/40">/</span>
          {isEditingTitle ? (
            <input
              ref={titleInputRef}
              value={titleDraft}
              onChange={(event) => setTitleDraft(event.target.value)}
              onBlur={() => {
                void commitTitle();
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  void commitTitle();
                } else if (event.key === "Escape") {
                  event.preventDefault();
                  cancelEditingTitle();
                }
              }}
              maxLength={120}
              spellCheck={false}
              placeholder={t("Untitled draft")}
              aria-label={t("Document title")}
              className="min-w-0 flex-1 max-w-[24rem] rounded-md border border-[var(--primary)]/40 bg-[var(--background)] px-2 py-0.5 font-medium text-[var(--foreground)] outline-none focus:border-[var(--primary)] focus:ring-1 focus:ring-[var(--primary)]/30"
            />
          ) : (
            <span
              role="button"
              tabIndex={0}
              onDoubleClick={startEditingTitle}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === "F2") {
                  event.preventDefault();
                  startEditingTitle();
                }
              }}
              title={t("Double-click to rename")}
              className="min-w-0 truncate cursor-text rounded-md border border-transparent px-2 py-0.5 font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)]/60 focus:outline-none focus:ring-1 focus:ring-[var(--primary)]/30"
            >
              {docTitle || t("Untitled draft")}
            </span>
          )}
          <span className="hidden text-xs sm:inline">
            {wordCount} {t("words")} &middot; {charCount} {t("chars")}
          </span>
          {isSavingDoc ? (
            <span className="hidden items-center gap-1 text-[10px] text-[var(--muted-foreground)]/70 sm:inline-flex">
              <Loader2 size={10} className="animate-spin" />
              {t("Saving…")}
            </span>
          ) : lastSavedAt ? (
            <span className="hidden text-[10px] text-[var(--muted-foreground)]/60 sm:inline">
              {t("Saved")}
            </span>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          <ToolbarIconBtn
            title={t("Clear")}
            onClick={requestClearDocument}
            tone="danger"
          >
            <Eraser size={17} strokeWidth={1.7} />
          </ToolbarIconBtn>
          <ToolbarIconBtn title={t("Export Markdown")} onClick={handleDownload}>
            <Download size={17} strokeWidth={1.7} />
          </ToolbarIconBtn>
          <ToolbarIconBtn
            title={t("Save to Notebook")}
            onClick={handleOpenSaveToNotebook}
          >
            <NotebookPen size={17} strokeWidth={1.7} />
          </ToolbarIconBtn>
          <ToolbarIconBtn
            title={t("Load Example Template")}
            onClick={requestLoadExampleTemplate}
            tone="warning"
          >
            <FileText size={17} strokeWidth={1.7} />
          </ToolbarIconBtn>
          <a
            href="https://litewrite.ai/"
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 rounded-full border border-[var(--border)] px-2.5 py-1 text-[11px] font-medium text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
          >
            <span>{t("Pro Vide Writing")}</span>
            <ArrowUpRight size={12} strokeWidth={1.8} aria-hidden="true" />
          </a>
          <div className="mx-1 h-5 w-px bg-[var(--border)]" />
          <button
            onClick={() => setIsEditModalOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-md bg-[var(--primary)] px-3 py-1 text-xs font-medium text-white transition-opacity hover:opacity-90"
          >
            <WandSparkles size={13} />
            {t("Full Draft")}
          </button>
        </div>
      </header>

      {/* ── Toolbar ── */}
      <div className="flex shrink-0 items-center gap-0.5 overflow-x-auto border-b border-[var(--border)] px-3 py-1">
        {TOOLBAR.map((item) => {
          if (item.type === "separator") {
            return (
              <div
                key={item.id}
                className="mx-1 h-4 w-px shrink-0 bg-[var(--border)]"
              />
            );
          }
          const Icon = item.icon;
          return (
            <button
              key={item.id}
              title={t(item.title)}
              onClick={() =>
                item.action ? item.action() : insertSnippet(item.snippet || "")
              }
              className="shrink-0 rounded p-1.5 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            >
              <Icon size={16} />
            </button>
          );
        })}

        <div className="ml-auto flex shrink-0 items-center gap-1.5 pl-3 text-[10px] text-[var(--muted-foreground)]">
          <button
            type="button"
            onClick={() => setSyncScrollEnabled((prev) => !prev)}
            disabled={!showEditor || !showPreview}
            title={
              syncScrollEnabled
                ? t("Scroll sync is on. Click to disable.")
                : t("Scroll sync is off. Click to enable.")
            }
            className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
              syncScrollEnabled
                ? "border-[var(--primary)]/40 bg-[var(--primary)]/10 text-[var(--primary)]"
                : "border-[var(--border)] bg-transparent text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
            }`}
          >
            <span
              aria-hidden="true"
              className={`inline-block h-1.5 w-1.5 rounded-full ${
                syncScrollEnabled
                  ? "bg-[var(--primary)]"
                  : "bg-[var(--muted-foreground)]/60"
              }`}
            />
            {t("Sync Scroll")}
          </button>
          <span
            className="mx-0.5 h-3 w-px bg-[var(--border)]"
            aria-hidden="true"
          />
          <span className="rounded bg-[var(--muted)] px-1.5 py-0.5">GFM</span>
          <span className="rounded bg-[var(--muted)] px-1.5 py-0.5">KaTeX</span>
          <span className="rounded bg-[var(--muted)] px-1.5 py-0.5">
            Mermaid
          </span>
        </div>
      </div>

      {/* ── Editor + Preview ── */}
      <div
        ref={splitContainerRef}
        className={`relative flex min-h-0 flex-1 ${
          isResizingSplit ? "select-none" : ""
        }`}
      >
        {/* Editor panel */}
        {showEditor && (
          <div
            className="flex min-h-0 flex-col"
            style={{
              width: showPreview ? `${editorRatio * 100}%` : "100%",
            }}
          >
            <div className="flex shrink-0 items-center justify-between border-b border-[var(--border)] px-3 py-1">
              <span className="text-xs font-medium text-[var(--muted-foreground)]">
                {t("Editor")}
              </span>
              <button
                title={t("Collapse editor")}
                onClick={() => setEditorCollapsed(true)}
                className="rounded p-0.5 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
              >
                <ChevronLeft size={14} />
              </button>
            </div>
            <textarea
              ref={textareaRef}
              value={markdown}
              onChange={(e) => handleMarkdownChange(e.target.value)}
              onSelect={updateSelectionPopover}
              onKeyDown={handleEditorKeyDown}
              onKeyUp={updateSelectionPopover}
              onMouseUp={updateSelectionPopover}
              onScroll={handleEditorScrollSync}
              spellCheck={false}
              className="min-h-0 flex-1 resize-none bg-transparent p-4 font-mono text-[13px] leading-relaxed text-[var(--foreground)] outline-none placeholder:text-[var(--muted-foreground)]"
              placeholder={t("Start writing in Markdown...")}
            />
          </div>
        )}

        {/* Draggable splitter (only when both panes are visible) */}
        {showEditor && showPreview && (
          <div
            role="separator"
            aria-orientation="vertical"
            aria-label={t("Resize editor and preview")}
            onPointerDown={handleSplitterPointerDown}
            onDoubleClick={() => setEditorRatio(0.5)}
            className={`group relative z-10 flex w-1 shrink-0 cursor-col-resize items-stretch border-x border-[var(--border)] transition-colors ${
              isResizingSplit
                ? "bg-[var(--primary)]/40"
                : "bg-transparent hover:bg-[var(--primary)]/30"
            }`}
            title={t("Drag to resize, double-click to reset")}
          >
            {/* Wider invisible hit-area so the handle is easy to grab */}
            <div className="absolute inset-y-0 -left-1.5 -right-1.5" />
            <div
              className={`pointer-events-none absolute left-1/2 top-1/2 h-10 w-[3px] -translate-x-1/2 -translate-y-1/2 rounded-full transition-opacity ${
                isResizingSplit
                  ? "bg-[var(--primary)] opacity-100"
                  : "bg-[var(--muted-foreground)]/40 opacity-0 group-hover:opacity-100"
              }`}
            />
          </div>
        )}

        {/* Collapse gutter / expand buttons */}
        {editorCollapsed && (
          <button
            onClick={() => setEditorCollapsed(false)}
            title={t("Expand editor")}
            className="flex w-7 shrink-0 items-center justify-center border-r border-[var(--border)] text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
          >
            <ChevronRight size={14} />
          </button>
        )}

        {previewCollapsed && (
          <button
            onClick={() => setPreviewCollapsed(false)}
            title={t("Expand preview")}
            className="flex w-7 shrink-0 items-center justify-center border-l border-[var(--border)] text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
          >
            <ChevronLeft size={14} />
          </button>
        )}

        {/* Preview panel */}
        {showPreview && (
          <div
            className="flex min-h-0 flex-col"
            style={{
              width: showEditor ? `${(1 - editorRatio) * 100}%` : "100%",
            }}
          >
            <div className="flex shrink-0 items-center justify-between border-b border-[var(--border)] px-3 py-1">
              <span className="text-xs font-medium text-[var(--muted-foreground)]">
                {t("Preview")}
              </span>
              <button
                title={t("Collapse preview")}
                onClick={() => setPreviewCollapsed(true)}
                className="rounded p-0.5 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
              >
                <ChevronRight size={14} />
              </button>
            </div>
            <div
              ref={previewScrollRef}
              onScroll={handlePreviewScrollSync}
              className="min-h-0 flex-1 overflow-y-auto p-5"
            >
              <MarkdownRenderer
                content={markdown || `_${t("Nothing to preview yet.")}_`}
                variant="prose"
                trackSourceLines
              />
            </div>
          </div>
        )}
      </div>

      {selectionPopover.visible && selectedRange && (
        <div
          ref={selectionPopoverRef}
          onMouseDown={handleSelectionPopoverDragStart}
          className={`fixed z-50 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-2.5 shadow-2xl ${
            isDraggingSelectionPopover ? "cursor-grabbing" : "cursor-grab"
          }`}
          style={{
            top: selectionPopover.top,
            left: selectionPopover.left,
            width: 360,
          }}
        >
          <div className="mb-2 flex justify-center" aria-hidden="true">
            <div className="h-1 w-10 rounded-full bg-[var(--border)]/80" />
          </div>

          <div className="relative">
            <input
              value={selectionInstruction}
              onChange={(e) => setSelectionInstruction(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  void applyReactSelectionEdit();
                }
              }}
              className="h-10 w-full rounded-xl bg-transparent pl-3 pr-10 text-[13px] text-[var(--foreground)] outline-none placeholder:text-[var(--muted-foreground)]"
              placeholder={t("Tell AI what to do with the selection...")}
            />
            <button
              onClick={() => void applyReactSelectionEdit()}
              disabled={isEditing || isAutoMarking}
              className="absolute right-1.5 top-1.5 inline-flex h-7 w-7 items-center justify-center rounded-full bg-[var(--primary)] text-white transition-opacity disabled:opacity-45"
              title={t("Apply AI edit")}
            >
              {isEditing ? (
                <Loader2 size={13} className="animate-spin" />
              ) : (
                <ArrowRight size={13} />
              )}
            </button>
          </div>

          <div className="mt-2 grid grid-cols-2 gap-2">
            <div className="relative">
              <button
                onClick={() => {
                  setIsToolMenuOpen((prev) => !prev);
                  setIsModeMenuOpen(false);
                }}
                className="flex h-9 w-full items-center justify-between rounded-xl border border-[var(--border)] px-3 text-[12px] text-[var(--foreground)] transition-colors hover:bg-[var(--muted)]"
              >
                <span className="truncate">
                  {selectionTools.length === 0
                    ? t("Tools")
                    : selectionTools.length === 1
                      ? t(
                          TOOL_OPTIONS.find(
                            (item) => item.name === selectionTools[0],
                          )?.label || "Tools",
                        )
                      : t("{{count}} tools", { count: selectionTools.length })}
                </span>
                <ChevronDown
                  size={13}
                  className={`shrink-0 transition-transform ${isToolMenuOpen ? "rotate-180" : ""}`}
                />
              </button>
              {isToolMenuOpen && (
                <div className="absolute left-0 top-full z-20 mt-1 w-full rounded-xl border border-[var(--border)] bg-[var(--card)] p-1 shadow-xl">
                  {TOOL_OPTIONS.map((tool) => {
                    const active = selectionTools.includes(tool.name);
                    return (
                      <button
                        key={tool.name}
                        onClick={() => toggleSelectionTool(tool.name)}
                        className="flex w-full items-center justify-between rounded-lg px-2.5 py-2 text-left text-[12px] text-[var(--foreground)] transition-colors hover:bg-[var(--muted)]"
                      >
                        <span>{t(tool.label)}</span>
                        {active ? (
                          <Check size={12} />
                        ) : (
                          <span className="w-3" />
                        )}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>

            <div className="relative">
              <button
                onClick={() => {
                  setIsModeMenuOpen((prev) => !prev);
                  setIsToolMenuOpen(false);
                }}
                className="flex h-9 w-full items-center justify-between rounded-xl border border-[var(--border)] px-3 text-[12px] text-[var(--foreground)] transition-colors hover:bg-[var(--muted)]"
              >
                <span>
                  {t(
                    MODE_OPTIONS.find((item) => item.value === selectionMode)
                      ?.label || "Mode",
                  )}
                </span>
                <ChevronDown
                  size={13}
                  className={`shrink-0 transition-transform ${isModeMenuOpen ? "rotate-180" : ""}`}
                />
              </button>
              {isModeMenuOpen && (
                <div className="absolute left-0 top-full z-20 mt-1 w-full rounded-xl border border-[var(--border)] bg-[var(--card)] p-1 shadow-xl">
                  {MODE_OPTIONS.map((mode) => (
                    <button
                      key={mode.value}
                      onClick={() => {
                        setSelectionMode(mode.value);
                        setIsModeMenuOpen(false);
                      }}
                      className="flex w-full items-center justify-between rounded-lg px-2.5 py-2 text-left text-[12px] text-[var(--foreground)] transition-colors hover:bg-[var(--muted)]"
                    >
                      <span>{t(mode.label)}</span>
                      {selectionMode === mode.value ? (
                        <Check size={12} />
                      ) : (
                        <span className="w-3" />
                      )}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          {(isEditing || selectionTrace) && (
            <div className="mt-2 rounded-xl border border-[var(--border)]/70 bg-[var(--muted)]/18">
              <button
                onClick={() => setIsTraceExpanded((prev) => !prev)}
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-[12px] text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
              >
                <ChevronDown
                  size={12}
                  className={`shrink-0 transition-transform ${isTraceExpanded ? "rotate-180" : ""}`}
                />
                <span className="font-medium text-[var(--foreground)]">
                  {t("Trace")}
                </span>
                {isEditing ? (
                  <Loader2 size={12} className="ml-auto animate-spin" />
                ) : null}
              </button>

              {isTraceExpanded && (
                <div
                  data-no-drag="true"
                  className="max-h-[280px] overflow-y-auto border-t border-[var(--border)]/60 px-3 py-2 text-[12px] leading-[1.7] text-[var(--muted-foreground)]"
                >
                  {selectionTrace?.thinking ? (
                    <div className="space-y-1.5">
                      <div className="text-[11px] font-medium uppercase tracking-[0.08em] text-[var(--muted-foreground)]/60">
                        {t("Thought")}
                      </div>
                      <MarkdownRenderer
                        content={selectionTrace.thinking}
                        variant="trace"
                      />
                    </div>
                  ) : isEditing ? (
                    <div className="opacity-70">{t("Thinking...")}</div>
                  ) : null}

                  {selectionTrace && selectionTrace.toolTraces.length > 0 && (
                    <div className="mt-3 space-y-1.5">
                      <div className="text-[11px] font-medium uppercase tracking-[0.08em] text-[var(--muted-foreground)]/60">
                        {t("Tool")}
                      </div>
                      <div className="space-y-2">
                        {selectionTrace.toolTraces.map((trace, index) => (
                          <div
                            key={`${trace.name}-${index}`}
                            className="space-y-1"
                          >
                            <div>
                              <span className="opacity-50">
                                {trace.kind === "tool_result" ? "✓ " : "→ "}
                              </span>
                              <span className="text-[var(--foreground)]">
                                {trace.name}
                              </span>
                            </div>
                            {trace.arguments &&
                            Object.keys(trace.arguments).length > 0 ? (
                              <pre className="ml-3 whitespace-pre-wrap break-words rounded-md bg-[var(--muted)]/45 px-2 py-1 font-mono text-[11px] leading-[1.55] text-[var(--muted-foreground)]/78">
                                {JSON.stringify(trace.arguments, null, 2)}
                              </pre>
                            ) : null}
                            {trace.result ? (
                              <div className="ml-3">
                                <MarkdownRenderer
                                  content={trace.result}
                                  variant="trace"
                                />
                              </div>
                            ) : null}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {selectionTrace?.response ? (
                    <div className="mt-3 space-y-1.5">
                      <div className="text-[11px] font-medium uppercase tracking-[0.08em] text-[var(--muted-foreground)]/60">
                        {t("Response")}
                      </div>
                      <MarkdownRenderer
                        content={selectionTrace.response}
                        variant="trace"
                      />
                    </div>
                  ) : null}

                  {isEditing &&
                  selectionTrace &&
                  !selectionTrace.thinking &&
                  selectionTrace.toolTraces.length === 0 &&
                  !selectionTrace.response ? (
                    <div className="mt-2 opacity-70">
                      {t("Running tools and preparing the final edit...")}
                    </div>
                  ) : null}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── Status bar ── */}
      {(error || status) && (
        <div
          className={`shrink-0 border-t px-4 py-1.5 text-xs ${
            error
              ? "border-red-200 bg-red-50 text-red-600 dark:border-red-900 dark:bg-red-950/30 dark:text-red-400"
              : "border-emerald-200 bg-emerald-50 text-emerald-600 dark:border-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-400"
          }`}
        >
          {error || status}
        </div>
      )}

      {/* ── AI Edit modal ── */}
      {isEditModalOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm"
          onClick={(e) => {
            if (e.target === e.currentTarget) setIsEditModalOpen(false);
          }}
        >
          <div className="w-full max-w-md rounded-xl border border-[var(--border)] bg-[var(--card)] shadow-xl">
            <div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-3">
              <h2 className="text-sm font-semibold text-[var(--foreground)]">
                {t("Full Draft AI Edit")}
              </h2>
              <button
                onClick={() => setIsEditModalOpen(false)}
                className="text-xs text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
              >
                {t("Close")}
              </button>
            </div>

            <div className="space-y-3 px-4 py-4">
              <div className="flex gap-1.5">
                {(Object.keys(ACTION_LABELS) as EditAction[]).map((a) => (
                  <button
                    key={a}
                    onClick={() => setAction(a)}
                    className={`rounded-md px-3 py-1.5 text-xs transition-colors ${
                      action === a
                        ? "bg-[var(--primary)] text-white"
                        : "border border-[var(--border)] text-[var(--foreground)] hover:bg-[var(--muted)]"
                    }`}
                  >
                    {t(ACTION_LABELS[a])}
                  </button>
                ))}
              </div>

              <textarea
                value={instruction}
                onChange={(e) => setInstruction(e.target.value)}
                rows={4}
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm text-[var(--foreground)] outline-none focus:border-[var(--primary)]"
                placeholder={t("Describe how you want the text edited...")}
              />

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="mb-1 block text-[10px] font-medium uppercase tracking-wider text-[var(--muted-foreground)]">
                    {t("Source")}
                  </label>
                  <select
                    value={source}
                    onChange={(e) => setSource(e.target.value as SourceOption)}
                    className="w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-2 py-1.5 text-xs text-[var(--foreground)] outline-none focus:border-[var(--primary)]"
                  >
                    <option value="none">{t("None")}</option>
                    <option value="rag">{t("Knowledge Base")}</option>
                    <option value="web">{t("Web Search")}</option>
                  </select>
                </div>
                <div>
                  <label className="mb-1 block text-[10px] font-medium uppercase tracking-wider text-[var(--muted-foreground)]">
                    {t("Knowledge Base")}
                  </label>
                  <select
                    value={kbName}
                    onChange={(e) => setKbName(e.target.value)}
                    disabled={source !== "rag"}
                    className="w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-2 py-1.5 text-xs text-[var(--foreground)] outline-none focus:border-[var(--primary)] disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    <option value="">{t("Select...")}</option>
                    {knowledgeBases.map((k) => (
                      <option key={k.name} value={k.name}>
                        {k.name}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
            </div>

            <div className="flex justify-end gap-2 border-t border-[var(--border)] px-4 py-3">
              <button
                onClick={applyAutoMark}
                disabled={isEditing || isAutoMarking}
                className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] px-3 py-1.5 text-xs font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)] disabled:opacity-50"
              >
                {isAutoMarking ? (
                  <Loader2 size={13} className="animate-spin" />
                ) : (
                  <Highlighter size={13} />
                )}
                {t("Auto Mark")}
              </button>
              <button
                onClick={applyEdit}
                disabled={isEditing || isAutoMarking}
                className="inline-flex items-center gap-1.5 rounded-md bg-[var(--primary)] px-3 py-1.5 text-xs font-medium text-white transition-opacity disabled:opacity-50"
              >
                {isEditing ? (
                  <Loader2 size={13} className="animate-spin" />
                ) : (
                  <ArrowRight size={13} />
                )}
                {t("Apply")}
              </button>
            </div>
          </div>
        </div>
      )}

      {confirmActionCopy && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 px-4 backdrop-blur-sm"
          onClick={(e) => {
            if (e.target === e.currentTarget) setPendingConfirmAction(null);
          }}
        >
          <div
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="co-writer-confirm-title"
            aria-describedby="co-writer-confirm-description"
            className="w-full max-w-sm rounded-xl border border-[var(--border)] bg-[var(--card)] shadow-xl"
          >
            <div className="border-b border-[var(--border)] px-4 py-3">
              <h2
                id="co-writer-confirm-title"
                className="text-sm font-semibold text-[var(--foreground)]"
              >
                {confirmActionCopy.title}
              </h2>
              <p
                id="co-writer-confirm-description"
                className="mt-1 text-xs leading-relaxed text-[var(--muted-foreground)]"
              >
                {confirmActionCopy.description}
              </p>
            </div>

            <div className="px-4 py-3">
              <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] leading-relaxed text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-200">
                {t(
                  "Undo is available with Ctrl/Cmd+Z or the toolbar Undo button.",
                )}
              </div>
            </div>

            <div className="flex justify-end gap-2 border-t border-[var(--border)] px-4 py-3">
              <button
                type="button"
                onClick={() => setPendingConfirmAction(null)}
                className="rounded-md border border-[var(--border)] px-3 py-1.5 text-xs font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)]"
              >
                {t("Cancel")}
              </button>
              <button
                type="button"
                onClick={() => {
                  const onConfirm = confirmActionCopy.onConfirm;
                  setPendingConfirmAction(null);
                  onConfirm();
                }}
                className={`rounded-md px-3 py-1.5 text-xs font-medium text-white transition-opacity hover:opacity-90 ${
                  confirmActionCopy.tone === "danger"
                    ? "bg-red-600"
                    : "bg-amber-600"
                }`}
              >
                {confirmActionCopy.confirmLabel}
              </button>
            </div>
          </div>
        </div>
      )}

      <SaveToNotebookModal
        open={notebookSavePayload !== null}
        payload={notebookSavePayload}
        onClose={() => setNotebookSavePayload(null)}
        onSaved={() => {
          setStatus(t("Saved to notebook."));
          setError("");
        }}
      />
    </div>
  );
}

function ToolbarIconBtn({
  title,
  onClick,
  children,
  tone = "default",
}: {
  title: string;
  onClick: () => void;
  children: React.ReactNode;
  tone?: "default" | "danger" | "warning";
}) {
  const toneClass =
    tone === "danger"
      ? "hover:bg-red-500/10 hover:text-red-600 dark:hover:text-red-400"
      : tone === "warning"
        ? "hover:bg-amber-500/10 hover:text-amber-700 dark:hover:text-amber-300"
        : "hover:bg-[var(--muted)] hover:text-[var(--foreground)]";

  return (
    <button
      type="button"
      aria-label={title}
      onClick={onClick}
      className={`group relative inline-flex h-8 w-8 items-center justify-center rounded-md text-[var(--muted-foreground)] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]/35 ${toneClass}`}
    >
      {children}
      <span
        role="tooltip"
        className="pointer-events-none absolute left-1/2 top-full z-30 mt-1.5 -translate-x-1/2 whitespace-nowrap rounded-md border border-[var(--border)] bg-[var(--card)] px-2 py-1 text-[10px] font-medium text-[var(--foreground)] opacity-0 shadow-lg transition-opacity delay-[120ms] duration-100 group-hover:opacity-100 group-focus-visible:opacity-100 group-focus-visible:delay-0"
      >
        {title}
      </span>
    </button>
  );
}
