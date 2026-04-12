"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  ArrowRight,
  ArrowUpRight,
  Bold,
  BookPlus,
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
  Quote,
  Redo2,
  Strikethrough,
  Table2,
  Undo2,
  WandSparkles,
  Workflow,
} from "lucide-react";
import { apiUrl } from "@/lib/api";
import { listKnowledgeBases } from "@/lib/knowledge-api";
import { CO_WRITER_SAMPLE_TEMPLATE } from "./sampleTemplate";

const MarkdownRenderer = dynamic(() => import("@/components/common/MarkdownRenderer"), {
  ssr: false,
});
const SaveToNotebookModal = dynamic(() => import("@/components/notebook/SaveToNotebookModal"), {
  ssr: false,
});

type EditAction = "rewrite" | "shorten" | "expand";
type SelectionMode = EditAction | "none";
type SourceOption = "none" | "rag" | "web";
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

const STORAGE_KEY = "deeptutor.co_writer.draft";
const HISTORY_KEY = "deeptutor.co_writer.history";
const LEGACY_STORAGE_KEY = "deeptutor.co_writer.draft";
const LEGACY_HISTORY_KEY = "deeptutor.co_writer.history";

function shouldReplaceLegacyTemplate(content: string): boolean {
  const text = content.trim();
  return (
    text.startsWith("# DeepTutor Co-Writer") ||
    text.includes("DeepTutor's built-in writing canvas for notes, reports, tutorials, and AI-assisted drafts.")
  );
}

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
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const selectionPopoverRef = useRef<HTMLDivElement>(null);
  const preserveSelectionTraceRef = useRef(false);
  const selectionRequestAbortRef = useRef<AbortController | null>(null);
  const selectionDragStateRef = useRef<{ offsetX: number; offsetY: number } | null>(
    null,
  );
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
  const [selectedRange, setSelectedRange] = useState<SelectedRange | null>(null);
  const [selectionPopover, setSelectionPopover] = useState<SelectionPopoverState>({
    visible: false,
    top: 0,
    left: 0,
  });
  const [selectionInstruction, setSelectionInstruction] = useState("");
  const [selectionMode, setSelectionMode] = useState<SelectionMode>("rewrite");
  const [selectionTools, setSelectionTools] = useState<ToolName[]>([]);
  const [isToolMenuOpen, setIsToolMenuOpen] = useState(false);
  const [isModeMenuOpen, setIsModeMenuOpen] = useState(false);
  const [selectionTrace, setSelectionTrace] = useState<SelectionTraceData | null>(
    null,
  );
  const [isTraceExpanded, setIsTraceExpanded] = useState(true);
  const [selectionPopoverPinned, setSelectionPopoverPinned] = useState(false);
  const [isDraggingSelectionPopover, setIsDraggingSelectionPopover] =
    useState(false);

  const [editorCollapsed, setEditorCollapsed] = useState(false);
  const [previewCollapsed, setPreviewCollapsed] = useState(false);

  const [showSaveModal, setShowSaveModal] = useState(false);

  const [undoStack, setUndoStack] = useState<string[]>([]);
  const [redoStack, setRedoStack] = useState<string[]>([]);
  const undoTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [hasLoadedDraft, setHasLoadedDraft] = useState(false);

  useEffect(() => {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    const legacySaved = window.localStorage.getItem(LEGACY_STORAGE_KEY);
    const loaded = saved ?? legacySaved;

    if (loaded === null) {
      setMarkdown(CO_WRITER_SAMPLE_TEMPLATE);
      setHasLoadedDraft(true);
      return;
    }

    // One-time migration from legacy DeepTutor default template to DeepTutor Chinese template.
    if (saved === null && shouldReplaceLegacyTemplate(loaded)) {
      setMarkdown(CO_WRITER_SAMPLE_TEMPLATE);
      window.localStorage.setItem(STORAGE_KEY, CO_WRITER_SAMPLE_TEMPLATE);
      window.localStorage.removeItem(LEGACY_STORAGE_KEY);
      window.localStorage.removeItem(LEGACY_HISTORY_KEY);
      setHasLoadedDraft(true);
      return;
    }

    setMarkdown(loaded);
    if (saved === null) {
      window.localStorage.setItem(STORAGE_KEY, loaded);
    }
    setHasLoadedDraft(true);
  }, []);

  useEffect(() => {
    if (!hasLoadedDraft) return;
    window.localStorage.setItem(STORAGE_KEY, markdown);
  }, [hasLoadedDraft, markdown]);

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

  const pushUndo = useCallback(
    (prev: string) => {
      setUndoStack((s) => [...s.slice(-50), prev]);
      setRedoStack([]);
    },
    [],
  );

  const handleMarkdownChange = useCallback(
    (value: string) => {
      if (undoTimerRef.current) clearTimeout(undoTimerRef.current);
      const prev = markdown;
      undoTimerRef.current = setTimeout(() => pushUndo(prev), 400);
      setMarkdown(value);
    },
    [markdown, pushUndo],
  );

  const handleUndo = useCallback(() => {
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

  const wordCount = useMemo(() => {
    const trimmed = markdown.trim();
    if (!trimmed) return 0;
    return trimmed.split(/\s+/).length;
  }, [markdown]);

  const charCount = markdown.length;
  const notebookSavePayload = useMemo(() => {
    const title =
      markdown
        .split("\n")
        .find((line) => line.startsWith("#"))
        ?.replace(/^#+\s*/, "")
        .trim() || t("Co-Writer Draft");
    return {
      recordType: "co_writer" as const,
      title,
      userQuery: "",
      output: markdown,
      metadata: { source: "co_writer", char_count: markdown.length },
    };
  }, [markdown]);

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
    [markdown, pushUndo],
  );

  const clearDocument = () => {
    pushUndo(markdown);
    setMarkdown("");
    setStatus("");
    setError("");
  };

  const loadExampleTemplate = useCallback(() => {
    if (markdown === CO_WRITER_SAMPLE_TEMPLATE) {
      setStatus(t("Example template is already loaded."));
      setError("");
      return;
    }

    pushUndo(markdown);
    setMarkdown(CO_WRITER_SAMPLE_TEMPLATE);
    setStatus(t("Loaded example template."));
    setError("");
  }, [markdown, pushUndo]);

  const handleDownload = () => {
    const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "co-writer.md";
    anchor.click();
    URL.revokeObjectURL(url);
  };

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
        textarea.setSelectionRange(range.start, range.start + replacement.length);
        updateSelectionPopover();
      });
    },
    [pushUndo, updateSelectionPopover],
  );

  const toggleSelectionTool = useCallback((tool: ToolName) => {
    setSelectionTools((prev) =>
      prev.includes(tool) ? prev.filter((item) => item !== tool) : [...prev, tool],
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

  const updateSelectionTraceFromEvent = useCallback((event: StreamTraceEvent) => {
    setSelectionTrace((prev) => {
      const current = prev ?? { thinking: "", toolTraces: [], response: "" };
      if (event.type === "thinking") {
        return { ...current, thinking: `${current.thinking}${event.content || ""}` };
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
        return { ...current, response: `${current.response}${event.content || ""}` };
      }
      return current;
    });
  }, []);

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
        const response = await fetch(apiUrl("/api/v1/co_writer/edit_react/stream"), {
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
        });
        if (!response.ok) {
          throw new Error((await response.text()) || "Failed to edit selected text.");
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
            throw new Error(String(payload?.detail || "Failed to edit selected text."));
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
      setStatus(t("Applied {{action}} to the full draft.", { action: t(ACTION_LABELS[action]).toLowerCase() }));
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
        snippet:
          "\n```mermaid\nflowchart TD\n  A[Start] --> B[End]\n```\n",
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

  const showEditor = !editorCollapsed;
  const showPreview = !previewCollapsed;

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
    };
  }, []);

  return (
    <div className="flex h-full min-h-full flex-col overflow-hidden bg-[var(--background)]">
      {/* ── Top bar ── */}
      <header className="flex shrink-0 items-center justify-between border-b border-[var(--border)] px-4 py-1.5">
        <div className="flex items-center gap-3 text-sm text-[var(--muted-foreground)]">
          <span className="font-medium text-[var(--foreground)]">
            {t("Co-Writer")}
          </span>
          <span className="hidden text-xs sm:inline">
            {wordCount} {t("words")} &middot; {charCount} {t("chars")}
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <ToolbarIconBtn
            title={t("Clear")}
            onClick={clearDocument}
          >
            <Eraser size={15} />
          </ToolbarIconBtn>
          <ToolbarIconBtn
            title={t("Export Markdown")}
            onClick={handleDownload}
          >
            <Download size={15} />
          </ToolbarIconBtn>
          <ToolbarIconBtn
            title={t("Load Example Template")}
            onClick={loadExampleTemplate}
          >
            <FileText size={15} />
          </ToolbarIconBtn>
          <div className="relative">
            <ToolbarIconBtn
              title={t("Add to Notebook")}
              onClick={() => setShowSaveModal(true)}
            >
              <BookPlus size={15} />
            </ToolbarIconBtn>
          </div>
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

        <div className="ml-auto flex shrink-0 items-center gap-1 pl-3 text-[10px] text-[var(--muted-foreground)]">
          <span className="rounded bg-[var(--muted)] px-1.5 py-0.5">GFM</span>
          <span className="rounded bg-[var(--muted)] px-1.5 py-0.5">
            KaTeX
          </span>
          <span className="rounded bg-[var(--muted)] px-1.5 py-0.5">
            Mermaid
          </span>
        </div>
      </div>

      {/* ── Editor + Preview ── */}
      <div className="relative flex min-h-0 flex-1">
        {/* Editor panel */}
        {showEditor && (
          <div
            className={`flex min-h-0 flex-col ${showPreview ? "w-1/2" : "w-full"} border-r border-[var(--border)]`}
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
              onKeyUp={updateSelectionPopover}
              onMouseUp={updateSelectionPopover}
              onScroll={updateSelectionPopover}
              spellCheck={false}
              className="min-h-0 flex-1 resize-none bg-transparent p-4 font-mono text-[13px] leading-relaxed text-[var(--foreground)] outline-none placeholder:text-[var(--muted-foreground)]"
              placeholder={t("Start writing in Markdown...")}
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
            className={`flex min-h-0 flex-col ${showEditor ? "w-1/2" : "w-full"}`}
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
            <div className="min-h-0 flex-1 overflow-y-auto p-5">
              <MarkdownRenderer
                content={markdown || `_${t("Nothing to preview yet.")}_`}
                variant="prose"
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
                      ? t(TOOL_OPTIONS.find((item) => item.name === selectionTools[0])
                          ?.label || "Tools")
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
                        {active ? <Check size={12} /> : <span className="w-3" />}
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
                  {t(MODE_OPTIONS.find((item) => item.value === selectionMode)?.label ||
                    "Mode")}
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
                          <div key={`${trace.name}-${index}`} className="space-y-1">
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
                    onChange={(e) =>
                      setSource(e.target.value as SourceOption)
                    }
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

      <SaveToNotebookModal
        open={showSaveModal}
        payload={notebookSavePayload}
        onClose={() => setShowSaveModal(false)}
        onSaved={() => setStatus(t("Added to notebook."))}
      />
    </div>
  );
}

function ToolbarIconBtn({
  title,
  onClick,
  children,
}: {
  title: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      title={title}
      onClick={onClick}
      className="rounded p-1.5 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
    >
      {children}
    </button>
  );
}
