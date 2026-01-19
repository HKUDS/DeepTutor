"use client";

import React, { useState, useRef, useEffect, useCallback } from "react";
import {
  Wand2,
  Minimize2,
  Maximize2,
  Globe,
  Database,
  Loader2,
  X,
  History,
  Bold,
  Italic,
  Underline as UnderlineIcon,
  Highlighter,
  Strikethrough,
  Code,
  Heading1,
  Heading2,
  List,
  ListOrdered,
  Quote,
  Link,
  Image as ImageIcon,
  Table,
  Minus,
  Download,
  FileText,
  PenTool,
  Sparkles,
  Eye,
  EyeOff,
  Wifi,
  WifiOff,
  AlertCircle,
  Book,
  Mic,
  Headphones,
  Radio,
  ChevronDown,
  ChevronRight,
  LayoutTemplate,
  Import,
} from "lucide-react";
import AddToNotebookModal from "./AddToNotebookModal";
import NotebookImportModal from "./NotebookImportModal";
import { apiUrl } from "@/lib/api";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import rehypeRaw from "rehype-raw";
import "katex/dist/katex.min.css";
import { processLatexContent } from "@/lib/latex";
import { loadFromStorage, saveToStorage, STORAGE_KEYS } from "@/lib/persistence";
import { debounce } from "@/lib/debounce";

interface CoWriterEditorProps {
  initialValue?: string;
}

// AI Mark tag regex patterns
const AI_MARK_REGEX = /<span\s+data-rough-notation="[^"]+">([^<]*)<\/span>/g;
const AI_MARK_OPEN_TAG = /<span\s+data-rough-notation="[^"]+">/g;
const AI_MARK_CLOSE_TAG = /<\/span>/g;

// Default content for new documents
const DEFAULT_COWRITER_CONTENT =
  "# Welcome to Co-Writer\n\nSelect text to see the magic happen.\n\n## Features\n\n- **Bold** text with Ctrl+B\n- *Italic* text with Ctrl+I\n- <u>Underline</u> with Ctrl+U\n- <mark>Highlight</mark> with Ctrl+H\n- AI-powered editing and auto-marking\n";

export default function CoWriterEditor({
  initialValue = "",
}: CoWriterEditorProps) {
  // Track hydration to avoid SSR mismatch
  const isHydrated = useRef(false);

  // Initialize with default content (same on server and client)
  const [content, setContent] = useState(initialValue || DEFAULT_COWRITER_CONTENT);

  // Debounced save for content
  const saveContent = useCallback(
    debounce((text: string) => {
      if (!isHydrated.current) return;
      saveToStorage(STORAGE_KEYS.COWRITER_CONTENT, text);
    }, 1000), // 1 second debounce for content to avoid too frequent saves while typing
    []
  );

  // Restore persisted content after hydration
  useEffect(() => {
    if (typeof window === "undefined") return;
    // If initialValue was provided, don't load from storage
    if (initialValue) {
      isHydrated.current = true;
      return;
    }
    
    const persistedContent = loadFromStorage<string>(
      STORAGE_KEYS.COWRITER_CONTENT,
      DEFAULT_COWRITER_CONTENT
    );
    if (persistedContent !== DEFAULT_COWRITER_CONTENT) {
      setContent(persistedContent);
    }
    isHydrated.current = true;
  }, [initialValue]);

  // Auto-save content on change (only after hydration)
  useEffect(() => {
    if (isHydrated.current) {
      saveContent(content);
    }
  }, [content, saveContent]);

  const [selection, setSelection] = useState<{
    start: number;
    end: number;
    text: string;
  } | null>(null);
  const [popover, setPopover] = useState<{
    visible: boolean;
    x: number;
    y: number;
  } | null>(null);
  const [instruction, setInstruction] = useState("");
  const [selectedAction, setSelectedAction] = useState<
    "rewrite" | "shorten" | "expand" | "automark"
  >("rewrite");
  const [source, setSource] = useState<"rag" | "web" | null>(null);
  const [selectedKb, setSelectedKb] = useState("");
  const [kbs, setKbs] = useState<string[]>([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const [operationHistory, setOperationHistory] = useState<any[]>([]);
  const [showHistory, setShowHistory] = useState(false);
  const [hideAiMarks, setHideAiMarks] = useState(false);
  const [rawContent, setRawContent] = useState(""); // Store original content with tags
  const [backendConnected, setBackendConnected] = useState<boolean | null>(
    null,
  ); // null = checking, true = connected, false = disconnected
  const [showNotebookModal, setShowNotebookModal] = useState(false);
  const [showImportModal, setShowImportModal] = useState(false);

  // Podcast / Narration related states
  const [isPodcastExpanded, setIsPodcastExpanded] = useState(false);
  const [narrationStyle, setNarrationStyle] = useState<
    "friendly" | "academic" | "concise"
  >("friendly");
  const [narrationScript, setNarrationScript] = useState<string>("");
  const [narrationKeyPoints, setNarrationKeyPoints] = useState<string[]>([]);
  const [narrationLoading, setNarrationLoading] = useState<boolean>(false);
  const [narrationError, setNarrationError] = useState<string | null>(null);
  const [ttsAvailable, setTtsAvailable] = useState<boolean | null>(null);
  const [ttsVoices, setTtsVoices] = useState<
    Array<{ id: string; name: string; description?: string }>
  >([]);
  const [selectedVoice, setSelectedVoice] = useState<string>("alloy");
  const [audioInfo, setAudioInfo] = useState<{
    audioUrl?: string;
    audioId?: string;
    voice?: string;
  } | null>(null);
  const [showNarrationNotebookModal, setShowNarrationNotebookModal] =
    useState(false);

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const previewRef = useRef<HTMLDivElement>(null);
  const editorContainerRef = useRef<HTMLDivElement>(null);
  const isSyncingScroll = useRef(false);

  // Check backend connection status
  const checkBackendConnection = useCallback(
    async (silent: boolean = false) => {
      try {
        // Use AbortController for timeout (better compatibility)
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 3000); // 3s timeout

        const response = await fetch(apiUrl("/api/v1/co_writer/history"), {
          method: "GET",
          signal: controller.signal,
        });

        clearTimeout(timeoutId);

        if (response.ok) {
          setBackendConnected(true);
          return true;
        } else {
          setBackendConnected(false);
          return false;
        }
      } catch (error: any) {
        setBackendConnected(false);
        // Only log errors in non-silent mode to avoid console noise
        if (
          !silent &&
          error.name !== "AbortError" &&
          process.env.NODE_ENV === "development"
        ) {
          // Only show detailed errors in development mode
          console.debug(
            "Backend connection check failed (this is normal if backend is not running):",
            error.message,
          );
        }
        return false;
      }
    },
    [],
  );

  // Check TTS configuration and available voices
  useEffect(() => {
    const fetchTtsConfig = async () => {
      try {
        const statusRes = await fetch(apiUrl("/api/v1/co_writer/tts/status"));
        if (statusRes.ok) {
          const statusData = await statusRes.json();
          if (statusData.available) {
            setTtsAvailable(true);
            if (statusData.default_voice) {
              setSelectedVoice(statusData.default_voice);
            }
            // Further fetch available voice list
            const voicesRes = await fetch(
              apiUrl("/api/v1/co_writer/tts/voices"),
            );
            if (voicesRes.ok) {
              const voicesData = await voicesRes.json();
              setTtsVoices(voicesData.voices || []);
            }
          } else {
            setTtsAvailable(false);
          }
        } else {
          setTtsAvailable(false);
        }
      } catch (e) {
        setTtsAvailable(false);
      }
    };
    // Only check once when component mounts
    fetchTtsConfig();
  }, []);

  // Fetch KBs
  useEffect(() => {
    const loadData = async () => {
      setBackendConnected(null); // Start checking

      try {
        // First check connection (silent mode to avoid console noise)
        const isConnected = await checkBackendConnection(true);

        if (isConnected) {
          // Load knowledge base list
          try {
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 5000);

            const res = await fetch(apiUrl("/api/v1/knowledge/list"), {
              signal: controller.signal,
            });

            clearTimeout(timeoutId);

            if (res.ok) {
              const data = await res.json();
              setKbs(data.map((kb: any) => kb.name));
              if (data.length > 0) setSelectedKb(data[0].name);
            }
          } catch (err: any) {
            // Only show errors in development mode
            if (process.env.NODE_ENV === "development") {
              console.debug(
                "Failed to fetch KBs (backend may not be running):",
                err.message,
              );
            }
          }

          // Load history
          fetchHistory();
        }
      } catch (error: any) {
        // Only show errors in development mode
        if (process.env.NODE_ENV === "development") {
          console.debug(
            "Failed to initialize (backend may not be running):",
            error.message,
          );
        }
      }
    };

    loadData();
  }, [checkBackendConnection]);

  const fetchHistory = () => {
    fetch(apiUrl("/api/v1/co_writer/history"))
      .then((res) => {
        if (res.ok) {
          return res.json();
        } else {
          throw new Error(`HTTP ${res.status}`);
        }
      })
      .then((data) => {
        setOperationHistory(data.history || []);
        setBackendConnected(true);
      })
      .catch((err) => {
        // Only show errors in development mode to avoid console noise
        if (process.env.NODE_ENV === "development") {
          console.debug(
            "Failed to fetch history (backend may not be running):",
            err.message,
          );
        }
        setBackendConnected(false);
      });
  };

  // Auto clear source when automark is selected
  useEffect(() => {
    if (selectedAction === "automark") {
      setSource(null);
    }
  }, [selectedAction]);

  // Synchronized scroll functionality
  const handleEditorScroll = useCallback(() => {
    if (isSyncingScroll.current) return;
    const editor = editorContainerRef.current;
    const preview = previewRef.current;
    if (!editor || !preview) return;

    isSyncingScroll.current = true;
    const scrollPercentage =
      editor.scrollTop / (editor.scrollHeight - editor.clientHeight);
    preview.scrollTop =
      scrollPercentage * (preview.scrollHeight - preview.clientHeight);

    requestAnimationFrame(() => {
      isSyncingScroll.current = false;
    });
  }, []);

  const handlePreviewScroll = useCallback(() => {
    if (isSyncingScroll.current) return;
    const editor = editorContainerRef.current;
    const preview = previewRef.current;
    if (!editor || !preview) return;

    isSyncingScroll.current = true;
    const scrollPercentage =
      preview.scrollTop / (preview.scrollHeight - preview.clientHeight);
    editor.scrollTop =
      scrollPercentage * (editor.scrollHeight - editor.clientHeight);

    requestAnimationFrame(() => {
      isSyncingScroll.current = false;
    });
  }, []);

  // Hide AI Marks functionality
  const getDisplayContent = useCallback(() => {
    if (!hideAiMarks) return content;
    // Remove AI tags, show content only
    return content.replace(AI_MARK_REGEX, "$1");
  }, [content, hideAiMarks]);

  // Save original content when hideAiMarks is enabled
  useEffect(() => {
    if (hideAiMarks && !rawContent) {
      setRawContent(content);
    } else if (!hideAiMarks && rawContent) {
      // When restoring, need to map edits back to original content
      setRawContent("");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- Only trigger on hideAiMarks toggle, not content changes
  }, [hideAiMarks]);

  // Merge edits with tags - smart AI mark protection
  const mergeEditWithMarks = useCallback(
    (original: string, oldPlain: string, newPlain: string): string => {
      // 1. Extract all marks and their positions in plain text
      interface MarkInfo {
        tag: string;
        innerText: string;
        plainStart: number; // Start position in plain text
        plainEnd: number; // End position in plain text
      }

      const marks: MarkInfo[] = [];
      const regex = /<span\s+data-rough-notation="([^"]+)">([^<]*)<\/span>/g;
      let match;

      // Calculate each mark's position in plain text
      let plainOffset = 0;
      let lastIndex = 0;

      while ((match = regex.exec(original)) !== null) {
        const tag = match[1];
        const innerText = match[2];
        const htmlStart = match.index;
        const htmlEnd = htmlStart + match[0].length;

        // Calculate plain text length before mark
        const textBefore = original.substring(lastIndex, htmlStart);
        plainOffset += textBefore.length;

        marks.push({
          tag,
          innerText,
          plainStart: plainOffset,
          plainEnd: plainOffset + innerText.length,
        });

        plainOffset += innerText.length;
        lastIndex = htmlEnd;
      }

      // 2. Find edited area (diff between old and new text)
      let diffStart = 0;
      let diffEndOld = oldPlain.length;
      let diffEndNew = newPlain.length;

      // Find first different position
      while (
        diffStart < oldPlain.length &&
        diffStart < newPlain.length &&
        oldPlain[diffStart] === newPlain[diffStart]
      ) {
        diffStart++;
      }

      // Find last different position (from end)
      while (
        diffEndOld > diffStart &&
        diffEndNew > diffStart &&
        oldPlain[diffEndOld - 1] === newPlain[diffEndNew - 1]
      ) {
        diffEndOld--;
        diffEndNew--;
      }

      // 3. Check if each mark is modified
      // Only remove mark when edit occurs inside the marked word
      const marksToKeep: Array<{ mark: MarkInfo; newPosition: number }> = [];

      for (const mark of marks) {
        // Check if edit is inside mark
        const editStartsInsideMark =
          diffStart > mark.plainStart && diffStart < mark.plainEnd;
        const editEndsInsideMark =
          diffEndOld > mark.plainStart && diffEndOld < mark.plainEnd;
        const editCompletelyInsideMark =
          diffStart >= mark.plainStart && diffEndOld <= mark.plainEnd;

        // Remove mark if edit is completely inside, or starts/ends inside mark
        if (
          editCompletelyInsideMark ||
          editStartsInsideMark ||
          editEndsInsideMark
        ) {
          // Mark modified, don't keep
          continue;
        }

        // Mark not modified, try to find its position in new text
        // Calculate offset caused by edit
        let newPosition = mark.plainStart;

        if (diffEndOld <= mark.plainStart) {
          // Edit is before mark, position needs adjustment
          const editLengthDiff =
            diffEndNew - diffStart - (diffEndOld - diffStart);
          newPosition = mark.plainStart + editLengthDiff;
        } else if (diffStart >= mark.plainEnd) {
          // Edit is after mark, position unchanged
          newPosition = mark.plainStart;
        } else {
          // Edit overlaps with mark but not inside (e.g., edit starts before and ends after mark)
          // In this case, mark may have moved, need to search
          const searchRadius = 50;
          const searchStart = Math.max(0, mark.plainStart - searchRadius);
          const searchEnd = Math.min(
            newPlain.length,
            mark.plainEnd + searchRadius,
          );
          const searchArea = newPlain.substring(searchStart, searchEnd);
          const foundIndex = searchArea.indexOf(mark.innerText);

          if (foundIndex !== -1) {
            newPosition = searchStart + foundIndex;
          } else {
            // Can't find mark text, possibly deleted, skip
            continue;
          }
        }

        // Validate text at new position matches
        if (
          newPosition >= 0 &&
          newPosition + mark.innerText.length <= newPlain.length
        ) {
          const textAtPosition = newPlain.substring(
            newPosition,
            newPosition + mark.innerText.length,
          );
          if (textAtPosition === mark.innerText) {
            marksToKeep.push({ mark, newPosition });
          }
        }
      }

      // 4. Insert marks from end to start to avoid position offset
      marksToKeep.sort((a, b) => b.newPosition - a.newPosition);

      let result = newPlain;
      for (const { mark, newPosition } of marksToKeep) {
        const before = result.substring(0, newPosition);
        const after = result.substring(newPosition + mark.innerText.length);
        const markedText = `<span data-rough-notation="${mark.tag}">${mark.innerText}</span>`;
        result = before + markedText + after;
      }

      return result;
    },
    [],
  );

  // Handle content changes in hidden mode
  const handleContentChange = useCallback(
    (newValue: string) => {
      if (!hideAiMarks) {
        setContent(newValue);
        return;
      }

      // In hidden mode, need to protect tags
      // Use functional update to avoid content state dependency
      setContent((prevContent) => {
        const oldDisplayContent = prevContent.replace(AI_MARK_REGEX, "$1");
        const newDisplayContent = newValue;

        if (oldDisplayContent === newDisplayContent) {
          return prevContent;
        }

        // Simplified: if user edits in hidden mode, replace entire content
        // But keep tags that weren't edited
        return mergeEditWithMarks(
          prevContent,
          oldDisplayContent,
          newDisplayContent,
        );
      });
    },
    [hideAiMarks, mergeEditWithMarks],
  );

  // Wrap selection with markers
  const wrapSelection = useCallback((before: string, after: string) => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const selectedText = textarea.value.substring(start, end);

    if (selectedText.length === 0) return;

    // Check if already wrapped
    const textBefore = textarea.value.substring(
      Math.max(0, start - before.length),
      start,
    );
    const textAfter = textarea.value.substring(end, end + after.length);

    let newContent: string;
    let newStart: number;
    let newEnd: number;

    if (textBefore === before && textAfter === after) {
      // Remove wrapping
      newContent =
        textarea.value.substring(0, start - before.length) +
        selectedText +
        textarea.value.substring(end + after.length);
      newStart = start - before.length;
      newEnd = end - before.length;
    } else {
      // Add wrapping
      newContent =
        textarea.value.substring(0, start) +
        before +
        selectedText +
        after +
        textarea.value.substring(end);
      newStart = start + before.length;
      newEnd = end + before.length;
    }

    setContent(newContent);

    // Restore selection after state update
    setTimeout(() => {
      textarea.focus();
      textarea.setSelectionRange(newStart, newEnd);
    }, 0);
  }, []);

  // Toggle line prefix
  const toggleLinePrefix = useCallback((prefix: string) => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const lines = textarea.value.split("\n");

    // Find line indices
    let charCount = 0;
    let startLine = 0;
    let endLine = 0;

    for (let i = 0; i < lines.length; i++) {
      if (charCount <= start && start <= charCount + lines[i].length) {
        startLine = i;
      }
      if (charCount <= end && end <= charCount + lines[i].length) {
        endLine = i;
        break;
      }
      charCount += lines[i].length + 1;
    }

    // Check if all lines have prefix
    let allHavePrefix = true;
    for (let i = startLine; i <= endLine; i++) {
      if (!lines[i].startsWith(prefix)) {
        allHavePrefix = false;
        break;
      }
    }

    // Toggle prefix
    for (let i = startLine; i <= endLine; i++) {
      if (allHavePrefix) {
        lines[i] = lines[i].substring(prefix.length);
      } else {
        lines[i] = prefix + lines[i];
      }
    }

    setContent(lines.join("\n"));
  }, []);

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (
        !textareaRef.current ||
        document.activeElement !== textareaRef.current
      )
        return;

      if (e.ctrlKey || e.metaKey) {
        switch (e.key.toLowerCase()) {
          case "b":
            e.preventDefault();
            wrapSelection("**", "**");
            break;
          case "i":
            e.preventDefault();
            wrapSelection("*", "*");
            break;
          case "u":
            e.preventDefault();
            wrapSelection("<u>", "</u>");
            break;
          case "h":
            e.preventDefault();
            wrapSelection("<mark>", "</mark>");
            break;
          case "s":
            if (e.shiftKey) {
              e.preventDefault();
              wrapSelection("~~", "~~");
            }
            break;
        }
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [wrapSelection]);

  // Handle selection for popover
  const handleMouseUp = (e: React.MouseEvent) => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const text = textarea.value.substring(start, end);

    if (text.trim().length > 0) {
      const rect = textarea.getBoundingClientRect();
      let x = e.clientX;
      let y = e.clientY + 10;

      setSelection({ start, end, text });
      setPopover({ visible: true, x, y });
      setInstruction("");
      setSelectedAction("rewrite");
      setSource(null);
    } else {
      setPopover(null);
      setSelection(null);
    }
  };

  // Close popover on click outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        popoverRef.current &&
        !popoverRef.current.contains(event.target as Node) &&
        textareaRef.current &&
        !textareaRef.current.contains(event.target as Node)
      ) {
        setPopover(null);
        setSelection(null);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handleAction = async (
    action: "rewrite" | "shorten" | "expand" | "automark",
  ) => {
    if (!selection) return;

    // If backend not connected, check once first
    if (backendConnected === false) {
      const isConnected = await checkBackendConnection();
      if (!isConnected) {
        alert(
          `❌ Backend service not connected\n\n` +
            `Please ensure the backend is running:\n` +
            `📍 ${apiUrl("")}\n\n` +
            `💡 How to start:\n` +
            `   Run in project root: python start.py\n` +
            `   Or: python start_web.py`,
        );
        return;
      }
    }

    setIsProcessing(true);

    try {
      let editedText: string;
      const apiEndpoint =
        action === "automark"
          ? "/api/v1/co_writer/automark"
          : "/api/v1/co_writer/edit";
      const requestUrl = apiUrl(apiEndpoint);

      if (action === "automark") {
        const requestBody = { text: selection.text };
        console.log("Sending automark request to:", requestUrl, requestBody);

        const res = await fetch(requestUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(requestBody),
        });

        if (!res.ok) {
          const errorText = await res.text();
          console.error("Automark API error:", res.status, errorText);
          throw new Error(
            `Failed to auto-mark text: ${res.status} ${res.statusText}\n${errorText}`,
          );
        }

        const data = await res.json();
        if (!data.marked_text) {
          throw new Error("Invalid response: missing marked_text field");
        }
        editedText = data.marked_text;
      } else {
        const requestBody: any = {
          text: selection.text,
          instruction: instruction || `Please ${action} this text.`,
          action,
        };

        // Only add source in non-automark mode
        if (source) {
          requestBody.source = source;
          if (source === "rag" && selectedKb) {
            requestBody.kb_name = selectedKb;
          }
        }

        console.log("Sending edit request to:", requestUrl, requestBody);

        const res = await fetch(requestUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(requestBody),
        });

        if (!res.ok) {
          const errorText = await res.text();
          console.error("Edit API error:", res.status, errorText);
          throw new Error(
            `Failed to edit text: ${res.status} ${res.statusText}\n${errorText}`,
          );
        }

        const data = await res.json();
        if (!data.edited_text) {
          throw new Error("Invalid response: missing edited_text field");
        }
        editedText = data.edited_text;
      }

      const newContent =
        content.substring(0, selection.start) +
        editedText +
        content.substring(selection.end);
      setContent(newContent);
      setPopover(null);
      setSelection(null);
      fetchHistory();
    } catch (error: any) {
      console.error("Action error:", error);

      // Update backend connection status
      setBackendConnected(false);

      // Build detailed error message
      let errorMessage = "Error processing request";
      const backendUrl = apiUrl("");

      if (
        error instanceof TypeError &&
        (error.message.includes("fetch") || error.message === "Failed to fetch")
      ) {
        errorMessage =
          `❌ Cannot connect to backend service\n\n` +
          `Please ensure the backend is running:\n` +
          `📍 ${backendUrl}\n\n` +
          `💡 How to start:\n` +
          `   Run in project root: python start.py\n` +
          `   Or: python start_web.py\n\n` +
          `If running on a different port, check NEXT_PUBLIC_API_BASE env variable`;
      } else if (
        error.name === "AbortError" ||
        error.message.includes("timeout")
      ) {
        errorMessage =
          `⏱️ Request timeout\n\n` +
          `Backend response took too long, please check:\n` +
          `1. Is the backend running properly?\n` +
          `2. Is network connection stable?\n` +
          `3. Is server load too high?`;
      } else if (error.message) {
        errorMessage = `❌ ${error.message}`;
      } else {
        errorMessage = `❌ Unknown error: ${String(error)}`;
      }

      alert(errorMessage);
    } finally {
      setIsProcessing(false);
    }
  };

  // Export functions
  const exportMarkdown = () => {
    const blob = new Blob([content], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "document.md";
    a.click();
    URL.revokeObjectURL(url);
  };

  const exportPDF = async () => {
    if (!previewRef.current) return;
    setIsProcessing(true);

    try {
      // Dynamically import jspdf and html2canvas
      const [{ default: jsPDF }, { default: html2canvas }] = await Promise.all([
        import("jspdf"),
        import("html2canvas"),
      ]);

      // Create temp container for PDF export
      const tempContainer = document.createElement("div");
      tempContainer.className = "pdf-export-container";
      tempContainer.style.cssText = `
        position: fixed;
        left: 0;
        top: 0;
        width: 210mm;
        min-height: 297mm;
        padding: 20mm;
        background: white;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
        font-size: 12pt;
        line-height: 1.6;
        color: #1e293b;
        z-index: 9999;
        overflow: visible;
      `;

      // Clone preview content
      const previewClone = previewRef.current.cloneNode(true) as HTMLElement;
      tempContainer.appendChild(previewClone);
      document.body.appendChild(tempContainer);

      // Copy all related stylesheets
      const allStyles = Array.from(document.styleSheets);
      const styleElement = document.createElement("style");
      styleElement.id = "pdf-export-styles";

      // Collect all style rules
      let styleText = "";

      // Add base styles
      styleText += `
        .pdf-export-container {
          position: fixed !important;
          left: 0 !important;
          top: 0 !important;
          width: 210mm !important;
          padding: 20mm !important;
          background: white !important;
        }

        /* Prose styles */
        .prose {
          max-width: none !important;
          color: #1e293b !important;
        }

        .prose h1, .prose h2, .prose h3, .prose h4 {
          font-weight: 600 !important;
          margin-top: 1.5em !important;
          margin-bottom: 0.5em !important;
          color: #0f172a !important;
        }

        .prose p {
          margin-bottom: 1em !important;
          line-height: 1.7 !important;
        }

        .prose ul, .prose ol {
          margin-bottom: 1em !important;
          padding-left: 1.5em !important;
        }

        .prose code {
          background: #f1f5f9 !important;
          padding: 0.125em 0.375em !important;
          border-radius: 0.25em !important;
          font-size: 0.9em !important;
          font-family: 'Consolas', 'Monaco', monospace !important;
        }

        .prose pre {
          background: #0f172a !important;
          color: #e2e8f0 !important;
          padding: 1em !important;
          border-radius: 0.5em !important;
          overflow-x: auto !important;
          margin: 1em 0 !important;
        }

        .prose pre code {
          background: transparent !important;
          padding: 0 !important;
          color: inherit !important;
        }

        .prose blockquote {
          border-left: 4px solid #8b5cf6 !important;
          padding-left: 1em !important;
          margin: 1em 0 !important;
          font-style: italic !important;
          color: #475569 !important;
        }

        .prose table {
          width: 100% !important;
          border-collapse: collapse !important;
          margin: 1em 0 !important;
        }

        .prose th, .prose td {
          border: 1px solid #cbd5e1 !important;
          padding: 0.5em !important;
        }

        .prose th {
          background: #f1f5f9 !important;
          font-weight: 600 !important;
        }
      `;

      // Add complete Rough Notation styles
      styleText += `
        /* Rough Notation - Complete Styles */
        .rough-notation {
          display: inline !important;
          position: relative !important;
        }

        /* Circle annotation */
        .rough-circle {
          position: relative !important;
          display: inline-block !important;
          padding: 0 6px !important;
        }

        .rough-circle::before {
          content: '' !important;
          position: absolute !important;
          top: -4px !important;
          left: -4px !important;
          right: -4px !important;
          bottom: -4px !important;
          border: 2.5px solid #ef4444 !important;
          border-radius: 50% !important;
          transform: rotate(-2deg) !important;
          pointer-events: none !important;
        }

        .rough-circle::after {
          content: '' !important;
          position: absolute !important;
          top: -3px !important;
          left: -2px !important;
          right: -6px !important;
          bottom: -5px !important;
          border: 1.5px solid rgba(239, 68, 68, 0.4) !important;
          border-radius: 45% 55% 50% 50% !important;
          transform: rotate(1deg) !important;
          pointer-events: none !important;
        }

        /* Highlight annotation */
        .rough-highlight {
          background: linear-gradient(
            104deg,
            rgba(254, 240, 138, 0) 0.9%,
            rgba(254, 240, 138, 1) 2.4%,
            rgba(254, 240, 138, 0.5) 5.8%,
            rgba(254, 240, 138, 0.3) 93%,
            rgba(254, 240, 138, 0.8) 96%,
            rgba(254, 240, 138, 0) 98%
          ),
          linear-gradient(
            183deg,
            rgba(254, 240, 138, 0) 0%,
            rgba(254, 240, 138, 0.4) 7.9%,
            rgba(254, 240, 138, 0) 15%
          ) !important;
          padding: 0.1em 0.2em !important;
          margin: 0 -0.2em !important;
          border-radius: 0.2em !important;
          box-decoration-break: clone !important;
          -webkit-box-decoration-break: clone !important;
        }

        /* Box annotation */
        .rough-box {
          position: relative !important;
          display: inline-block !important;
          padding: 2px 6px !important;
        }

        .rough-box::before {
          content: '' !important;
          position: absolute !important;
          top: -2px !important;
          left: -3px !important;
          right: -3px !important;
          bottom: -2px !important;
          border: 2px solid #3b82f6 !important;
          border-radius: 2px !important;
          transform: rotate(-0.5deg) skewX(-0.5deg) !important;
          pointer-events: none !important;
        }

        .rough-box::after {
          content: '' !important;
          position: absolute !important;
          top: 0px !important;
          left: -1px !important;
          right: -5px !important;
          bottom: -4px !important;
          border: 1.5px solid rgba(59, 130, 246, 0.3) !important;
          border-radius: 1px !important;
          transform: rotate(0.5deg) !important;
          pointer-events: none !important;
        }

        /* Underline annotation */
        .rough-underline {
          position: relative !important;
          text-decoration: none !important;
        }

        .rough-underline::after {
          content: '' !important;
          position: absolute !important;
          left: 0 !important;
          right: 0 !important;
          bottom: -2px !important;
          height: 4px !important;
          background: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 4'%3E%3Cpath d='M0 3 Q5 0 10 3 T20 3' stroke='%231e293b' stroke-width='1.5' fill='none' stroke-linecap='round'/%3E%3C/svg%3E") repeat-x !important;
          background-size: 12px 4px !important;
          pointer-events: none !important;
        }

        /* Bracket annotation */
        .rough-bracket {
          display: inline !important;
        }

        .rough-bracket-container {
          position: relative !important;
          padding-left: 16px !important;
          margin-left: 4px !important;
        }

        .rough-bracket-container::before {
          content: '' !important;
          position: absolute !important;
          left: 0 !important;
          top: -4px !important;
          bottom: -4px !important;
          width: 10px !important;
          border-left: 3px solid #8b5cf6 !important;
          border-top: 3px solid #8b5cf6 !important;
          border-bottom: 3px solid #8b5cf6 !important;
          border-radius: 4px 0 0 4px !important;
          transform: scaleX(0.6) !important;
          transform-origin: left center !important;
          pointer-events: none !important;
        }

        span.rough-bracket {
          border-left: 3px solid #8b5cf6 !important;
          padding-left: 8px !important;
          margin-left: 4px !important;
          display: inline !important;
          position: relative !important;
        }

        span.rough-bracket::before {
          content: '' !important;
          position: absolute !important;
          left: -3px !important;
          top: -2px !important;
          width: 8px !important;
          height: 3px !important;
          border-left: 3px solid #8b5cf6 !important;
          border-top: 3px solid #8b5cf6 !important;
          border-radius: 3px 0 0 0 !important;
          pointer-events: none !important;
        }

        span.rough-bracket::after {
          content: '' !important;
          position: absolute !important;
          left: -3px !important;
          bottom: -2px !important;
          width: 8px !important;
          height: 3px !important;
          border-left: 3px solid #8b5cf6 !important;
          border-bottom: 3px solid #8b5cf6 !important;
          border-radius: 0 0 0 3px !important;
          pointer-events: none !important;
        }
      `;

      styleElement.textContent = styleText;
      document.head.appendChild(styleElement);

      // Wait for styles to apply and render
      await new Promise((resolve) => setTimeout(resolve, 100));

      // Force layout recalculation
      tempContainer.offsetHeight;

      const canvas = await html2canvas(tempContainer, {
        scale: 2,
        useCORS: true,
        logging: false,
        backgroundColor: "#ffffff",
        allowTaint: true,
        removeContainer: false,
        imageTimeout: 15000,
        onclone: (clonedDoc) => {
          // Ensure styles are applied in cloned document
          const clonedStyle = clonedDoc.getElementById("pdf-export-styles");
          if (!clonedStyle) {
            const newStyle = clonedDoc.createElement("style");
            newStyle.id = "pdf-export-styles";
            newStyle.textContent = styleText;
            clonedDoc.head.appendChild(newStyle);
          }
        },
      });

      // Cleanup
      document.body.removeChild(tempContainer);
      const styleToRemove = document.getElementById("pdf-export-styles");
      if (styleToRemove) {
        document.head.removeChild(styleToRemove);
      }

      const imgData = canvas.toDataURL("image/png", 1.0);
      const pdf = new jsPDF("p", "mm", "a4");
      const pdfWidth = pdf.internal.pageSize.getWidth();
      const pdfHeight = pdf.internal.pageSize.getHeight();
      const margin = 10; // 10mm margins
      const contentWidth = pdfWidth - margin * 2;

      const imgProps = pdf.getImageProperties(imgData);
      const imgHeight = (imgProps.height * contentWidth) / imgProps.width;

      let heightLeft = imgHeight;
      let position = margin;

      // Add first page
      pdf.addImage(imgData, "PNG", margin, position, contentWidth, imgHeight);
      heightLeft -= pdfHeight - margin * 2;

      // Add subsequent pages
      while (heightLeft > 0) {
        pdf.addPage();
        position = margin - (imgHeight - heightLeft);
        pdf.addImage(imgData, "PNG", margin, position, contentWidth, imgHeight);
        heightLeft -= pdfHeight - margin * 2;
      }

      pdf.save("document.pdf");
    } catch (e) {
      console.error("PDF export error:", e);
      alert(
        "PDF export failed, please try again. Check console for error details.",
      );
    } finally {
      setIsProcessing(false);
    }
  };

  // Toolbar button component
  const ToolbarButton = ({
    icon,
    onClick,
    title,
    active,
  }: {
    icon: React.ReactNode;
    onClick: () => void;
    title: string;
    active?: boolean;
  }) => (
    <button
      onClick={onClick}
      title={title}
      className={`p-1.5 rounded transition-all ${active ? "bg-purple-100 dark:bg-purple-900/50 text-purple-700 dark:text-purple-300" : "text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700 hover:text-slate-700 dark:hover:text-slate-200"}`}
    >
      {icon}
    </button>
  );

  const Divider = () => (
    <div className="w-px h-5 bg-slate-200 dark:bg-slate-600 mx-1" />
  );

  return (
    <div className="flex h-full gap-4">
      {/* Left Column: Editor */}
      <div className="flex-1 flex flex-col bg-white dark:bg-slate-900 rounded-xl shadow-sm border border-slate-200 dark:border-slate-700 overflow-hidden relative">
        {/* Toolbar */}
        <div className="p-2 border-b border-slate-100 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-800/50 flex items-center gap-1 flex-wrap">
          {/* Formatting */}
          <div className="flex items-center gap-0.5">
            <ToolbarButton
              icon={<Bold className="w-4 h-4" />}
              onClick={() => wrapSelection("**", "**")}
              title="Bold (Ctrl+B)"
            />
            <ToolbarButton
              icon={<Italic className="w-4 h-4" />}
              onClick={() => wrapSelection("*", "*")}
              title="Italic (Ctrl+I)"
            />
            <ToolbarButton
              icon={<UnderlineIcon className="w-4 h-4" />}
              onClick={() => wrapSelection("<u>", "</u>")}
              title="Underline (Ctrl+U)"
            />
            <ToolbarButton
              icon={<Highlighter className="w-4 h-4" />}
              onClick={() => wrapSelection("<mark>", "</mark>")}
              title="Highlight (Ctrl+H)"
            />
            <ToolbarButton
              icon={<Strikethrough className="w-4 h-4" />}
              onClick={() => wrapSelection("~~", "~~")}
              title="Strikethrough (Ctrl+Shift+S)"
            />
            <ToolbarButton
              icon={<Code className="w-4 h-4" />}
              onClick={() => wrapSelection("`", "`")}
              title="Inline Code"
            />
          </div>

          <Divider />

          {/* Headings */}
          <div className="flex items-center gap-0.5">
            <ToolbarButton
              icon={<Heading1 className="w-4 h-4" />}
              onClick={() => toggleLinePrefix("# ")}
              title="Heading 1"
            />
            <ToolbarButton
              icon={<Heading2 className="w-4 h-4" />}
              onClick={() => toggleLinePrefix("## ")}
              title="Heading 2"
            />
          </div>

          <Divider />

          {/* Lists */}
          <div className="flex items-center gap-0.5">
            <ToolbarButton
              icon={<List className="w-4 h-4" />}
              onClick={() => toggleLinePrefix("- ")}
              title="Bullet List"
            />
            <ToolbarButton
              icon={<ListOrdered className="w-4 h-4" />}
              onClick={() => toggleLinePrefix("1. ")}
              title="Numbered List"
            />
            <ToolbarButton
              icon={<Quote className="w-4 h-4" />}
              onClick={() => toggleLinePrefix("> ")}
              title="Quote"
            />
          </div>

          <Divider />

          {/* Insert */}
          <div className="flex items-center gap-0.5">
            <ToolbarButton
              icon={<Link className="w-4 h-4" />}
              onClick={() => wrapSelection("[", "](url)")}
              title="Link"
            />
            <ToolbarButton
              icon={<ImageIcon className="w-4 h-4" />}
              onClick={() => wrapSelection("![", "](url)")}
              title="Image"
            />
            <ToolbarButton
              icon={<Minus className="w-4 h-4" />}
              onClick={() => {
                const textarea = textareaRef.current;
                if (!textarea) return;
                const pos = textarea.selectionStart;
                setContent(
                  content.substring(0, pos) +
                    "\n\n---\n\n" +
                    content.substring(pos),
                );
              }}
              title="Horizontal Rule"
            />
          </div>

          <Divider />

          {/* Import from Notebook */}
          <button
            onClick={() => setShowImportModal(true)}
            className="flex items-center gap-1 px-2 py-1 text-xs text-blue-600 dark:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-900/30 rounded transition-all"
            title="Import from Notebook"
          >
            <Import className="w-3.5 h-3.5" />
            Import
          </button>

          <div className="flex-1" />

          {/* Backend Status Indicator */}
          {backendConnected !== null && (
            <>
              <div
                className={`flex items-center gap-1 px-2 py-1 text-xs rounded transition-all ${
                  backendConnected
                    ? "bg-green-50 dark:bg-green-900/30 text-green-700 dark:text-green-400 border border-green-200 dark:border-green-800"
                    : "bg-red-50 dark:bg-red-900/30 text-red-700 dark:text-red-400 border border-red-200 dark:border-red-800"
                }`}
                title={
                  backendConnected
                    ? `Backend connected: ${apiUrl("")}`
                    : `Backend not connected\nRun: python start.py\nAddress: ${apiUrl("")}`
                }
              >
                {backendConnected ? (
                  <>
                    <Wifi className="w-3 h-3" />
                    <span className="hidden sm:inline">Connected</span>
                  </>
                ) : (
                  <>
                    <WifiOff className="w-3 h-3" />
                    <span className="hidden sm:inline">Disconnected</span>
                  </>
                )}
              </div>
            </>
          )}
        </div>

        {/* Editor Area */}
        <div className="flex-1 flex flex-col overflow-hidden">
          <div className="p-2 border-b border-slate-100 dark:border-slate-700 bg-slate-50/30 dark:bg-slate-800/30 flex justify-between items-center">
            <div className="flex items-center gap-2">
              <div className="text-[10px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-wider">
                Editor
              </div>
              {hideAiMarks && (
                <span className="text-[9px] bg-emerald-100 dark:bg-emerald-900/50 text-emerald-600 dark:text-emerald-400 px-1.5 py-0.5 rounded-full font-medium">
                  Marks Hidden
                </span>
              )}
            </div>
            <div className="text-[10px] text-slate-400 dark:text-slate-500">
              {content.length} chars · {content.split("\n").length} lines
            </div>
          </div>
          <div
            ref={editorContainerRef}
            className="flex-1 overflow-y-auto"
            onScroll={handleEditorScroll}
          >
            <textarea
              ref={textareaRef}
              value={hideAiMarks ? getDisplayContent() : content}
              onChange={(e) => handleContentChange(e.target.value)}
              onMouseUp={handleMouseUp}
              className="w-full h-full min-h-full p-4 resize-none outline-none font-mono text-sm leading-relaxed text-slate-800 dark:text-slate-200 bg-transparent placeholder-slate-400 dark:placeholder-slate-500"
              placeholder="Type your markdown here..."
              style={{ minHeight: "100%" }}
            />
          </div>
        </div>

        {/* Popover */}
        {popover && (
          <div
            ref={popoverRef}
            style={{
              position: "fixed",
              left: Math.min(
                window.innerWidth - 340,
                Math.max(20, popover.x - 160),
              ),
              top: Math.min(window.innerHeight - 480, popover.y),
            }}
            className="z-50 w-[320px] bg-white dark:bg-slate-800 rounded-xl shadow-2xl border border-slate-200 dark:border-slate-600 animate-in fade-in zoom-in-95 duration-200 flex flex-col"
          >
            <div className="p-3 border-b border-slate-100 dark:border-slate-700 bg-gradient-to-r from-purple-50 to-indigo-50 dark:from-purple-900/30 dark:to-indigo-900/30 flex justify-between items-center rounded-t-xl">
              <div className="flex items-center gap-2 text-xs font-bold text-slate-700 dark:text-slate-200">
                <Sparkles className="w-4 h-4 text-purple-500 dark:text-purple-400" />
                AI Edit Assistant
              </div>
              <button
                onClick={() => setPopover(null)}
                className="text-slate-400 hover:text-slate-600 dark:text-slate-500 dark:hover:text-slate-300"
                title="Close"
                aria-label="Close dialog"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="p-4 space-y-4">
              {/* Selected Text Preview */}
              <div className="text-xs text-slate-500 dark:text-slate-400 bg-slate-50 dark:bg-slate-700 p-2 rounded-lg border border-slate-100 dark:border-slate-600 line-clamp-2 italic">
                &quot;{selection?.text}&quot;
              </div>

              {/* Instruction Input */}
              <div className="space-y-1">
                <label className="text-[10px] font-bold text-slate-500 dark:text-slate-400 uppercase">
                  Instruction (Optional)
                </label>
                <input
                  type="text"
                  value={instruction}
                  onChange={(e) => setInstruction(e.target.value)}
                  placeholder="e.g. Make it more formal..."
                  className="w-full px-3 py-2 text-xs border border-slate-200 dark:border-slate-600 rounded-lg focus:ring-2 focus:ring-purple-500/20 focus:border-purple-500 outline-none bg-white dark:bg-slate-700 text-slate-800 dark:text-slate-200 placeholder-slate-400 dark:placeholder-slate-500"
                />
              </div>

              {/* Source Selection - Only show in non-automark mode */}
              {selectedAction !== "automark" && (
                <div className="space-y-1">
                  <label className="text-[10px] font-bold text-slate-500 dark:text-slate-400 uppercase">
                    Context Source (Optional)
                  </label>
                  <div className="flex gap-2">
                    <button
                      onClick={() => setSource(source === "rag" ? null : "rag")}
                      className={`flex-1 flex items-center justify-center gap-1 py-1.5 text-xs border rounded-lg transition-all ${source === "rag" ? "bg-purple-50 dark:bg-purple-900/40 border-purple-200 dark:border-purple-700 text-purple-700 dark:text-purple-300" : "bg-white dark:bg-slate-700 border-slate-200 dark:border-slate-600 text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-600"}`}
                    >
                      <Database className="w-3 h-3" />
                      RAG
                    </button>
                    <button
                      onClick={() => setSource(source === "web" ? null : "web")}
                      className={`flex-1 flex items-center justify-center gap-1 py-1.5 text-xs border rounded-lg transition-all ${source === "web" ? "bg-blue-50 dark:bg-blue-900/40 border-blue-200 dark:border-blue-700 text-blue-700 dark:text-blue-300" : "bg-white dark:bg-slate-700 border-slate-200 dark:border-slate-600 text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-600"}`}
                    >
                      <Globe className="w-3 h-3" />
                      Web
                    </button>
                  </div>
                </div>
              )}

              {/* KB Selector if RAG */}
              {source === "rag" && kbs.length > 0 && (
                <div className="animate-in fade-in slide-in-from-top-1">
                  <select
                    value={selectedKb}
                    onChange={(e) => setSelectedKb(e.target.value)}
                    className="w-full px-2 py-1.5 text-xs border border-slate-200 dark:border-slate-600 rounded-lg outline-none bg-white dark:bg-slate-700 text-slate-800 dark:text-slate-200"
                  >
                    {kbs.map((kb) => (
                      <option key={kb} value={kb}>
                        {kb}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              {/* Actions */}
              <div className="pt-2 border-t border-slate-100 dark:border-slate-700 space-y-3">
                <div className="grid grid-cols-4 gap-1.5">
                  <button
                    onClick={() => setSelectedAction("rewrite")}
                    disabled={isProcessing}
                    className={`flex flex-col items-center gap-1 p-2 rounded-lg transition-all text-[10px] font-medium border-2 ${selectedAction === "rewrite" ? "bg-purple-50 dark:bg-purple-900/40 border-purple-400 dark:border-purple-600 text-purple-600 dark:text-purple-300" : "border-transparent text-slate-600 dark:text-slate-400 hover:bg-purple-50 dark:hover:bg-purple-900/30 hover:text-purple-600 dark:hover:text-purple-300"}`}
                  >
                    <Wand2 className="w-4 h-4" />
                    Rewrite
                  </button>
                  <button
                    onClick={() => setSelectedAction("shorten")}
                    disabled={isProcessing}
                    className={`flex flex-col items-center gap-1 p-2 rounded-lg transition-all text-[10px] font-medium border-2 ${selectedAction === "shorten" ? "bg-amber-50 dark:bg-amber-900/40 border-amber-400 dark:border-amber-600 text-amber-600 dark:text-amber-300" : "border-transparent text-slate-600 dark:text-slate-400 hover:bg-amber-50 dark:hover:bg-amber-900/30 hover:text-amber-600 dark:hover:text-amber-300"}`}
                  >
                    <Minimize2 className="w-4 h-4" />
                    Shorten
                  </button>
                  <button
                    onClick={() => setSelectedAction("expand")}
                    disabled={isProcessing}
                    className={`flex flex-col items-center gap-1 p-2 rounded-lg transition-all text-[10px] font-medium border-2 ${selectedAction === "expand" ? "bg-blue-50 dark:bg-blue-900/40 border-blue-400 dark:border-blue-600 text-blue-600 dark:text-blue-300" : "border-transparent text-slate-600 dark:text-slate-400 hover:bg-blue-50 dark:hover:bg-blue-900/30 hover:text-blue-600 dark:hover:text-blue-300"}`}
                  >
                    <Maximize2 className="w-4 h-4" />
                    Expand
                  </button>
                  <button
                    onClick={() => setSelectedAction("automark")}
                    disabled={isProcessing}
                    className={`flex flex-col items-center gap-1 p-2 rounded-lg transition-all text-[10px] font-medium border-2 ${selectedAction === "automark" ? "bg-emerald-50 dark:bg-emerald-900/40 border-emerald-400 dark:border-emerald-600 text-emerald-600 dark:text-emerald-300" : "border-transparent text-slate-600 dark:text-slate-400 hover:bg-emerald-50 dark:hover:bg-emerald-900/30 hover:text-emerald-600 dark:hover:text-emerald-300"}`}
                  >
                    <PenTool className="w-4 h-4" />
                    AI Mark
                  </button>
                </div>

                {/* Submit Button */}
                <button
                  onClick={() => handleAction(selectedAction)}
                  disabled={isProcessing}
                  className="w-full py-2.5 bg-gradient-to-r from-purple-600 to-indigo-600 text-white text-xs font-bold rounded-lg hover:from-purple-700 hover:to-indigo-700 transition-all shadow-md hover:shadow-lg disabled:opacity-50 flex items-center justify-center gap-2"
                >
                  {isProcessing ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Processing...
                    </>
                  ) : (
                    <>
                      <Sparkles className="w-4 h-4" />
                      Apply{" "}
                      {selectedAction === "automark"
                        ? "AI Mark"
                        : selectedAction.charAt(0).toUpperCase() +
                          selectedAction.slice(1)}
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Right Column */}
      <div className="flex-1 flex flex-col gap-4">
        {/* Preview Area (Upper) */}
        <div
          className={`flex-1 bg-white dark:bg-slate-900 rounded-xl shadow-sm border border-slate-200 dark:border-slate-700 overflow-hidden flex flex-col transition-all`}
        >
          {/* Preview Header & Toolbar */}
          <div className="p-2 border-b border-slate-100 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-800/50 flex justify-between items-center">
            <div className="flex items-center gap-2">
              <div className="text-[10px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-wider">
                Preview
              </div>
              <div className="flex items-center gap-1">
                <Sparkles className="w-3 h-3 text-purple-400" />
                <span className="text-[10px] text-slate-400 dark:text-slate-500">
                  Live Preview · Synced Scroll
                </span>
              </div>
            </div>

            {/* Moved Action Buttons to Preview Header */}
            <div className="flex items-center gap-1">
              <button
                onClick={() => setShowNotebookModal(true)}
                className="flex items-center gap-1 px-2 py-1 text-xs text-indigo-600 dark:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-900/30 rounded transition-all"
                title="Save to Notebook"
              >
                <Book className="w-3.5 h-3.5" />
                Save
              </button>
              <Divider />
              <button
                onClick={() => setHideAiMarks(!hideAiMarks)}
                className={`flex items-center gap-1 px-2 py-1 text-xs rounded transition-all ${hideAiMarks ? "bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-400" : "text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700"}`}
                title={hideAiMarks ? "Show AI Marks" : "Hide AI Marks"}
              >
                {hideAiMarks ? (
                  <Eye className="w-3.5 h-3.5" />
                ) : (
                  <EyeOff className="w-3.5 h-3.5" />
                )}
              </button>
              <Divider />
              <button
                onClick={exportMarkdown}
                className="flex items-center gap-1 px-2 py-1 text-xs text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700 rounded transition-all"
                title="Export Markdown"
              >
                <FileText className="w-3.5 h-3.5" />
                .md
              </button>
              <button
                onClick={exportPDF}
                disabled={isProcessing}
                className="flex items-center gap-1 px-2 py-1 text-xs text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700 rounded transition-all disabled:opacity-50"
                title="Export PDF"
              >
                <Download className="w-3.5 h-3.5" />
                .pdf
              </button>
              <Divider />
              <button
                onClick={() => setShowHistory(!showHistory)}
                className={`flex items-center gap-1 text-xs px-2 py-1 rounded transition-all ${showHistory ? "bg-purple-100 dark:bg-purple-900/40 text-purple-700 dark:text-purple-400" : "text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700"}`}
                title="History"
              >
                <History className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>

          {/* Markdown Preview Content */}
          <div className="flex-1 flex flex-col relative min-h-0">
            <div
              ref={previewRef}
              className="flex-1 overflow-y-auto p-6 prose prose-slate dark:prose-invert prose-sm max-w-none prose-headings:text-slate-900 dark:prose-headings:text-slate-100 prose-p:text-slate-700 dark:prose-p:text-slate-300 prose-a:text-purple-600 dark:prose-a:text-purple-400 rough-notation-container"
              onScroll={handlePreviewScroll}
              style={{ minHeight: 0 }}
            >
              <ReactMarkdown
                remarkPlugins={[remarkGfm, remarkMath]}
                rehypePlugins={[rehypeKatex, rehypeRaw]}
                components={{
                  mark: ({ node, ...props }) => (
                    <mark className="bg-yellow-200 px-0.5 rounded" {...props} />
                  ),
                  u: ({ node, ...props }) => (
                    <u
                      className="underline decoration-2 decoration-slate-400"
                      {...props}
                    />
                  ),
                  span: ({ node, ...props }) => {
                    const dataAttr = (props as any)["data-rough-notation"];
                    if (dataAttr) {
                      // Handwritten style annotation styles
                      const styleClasses: Record<string, string> = {
                        circle: "rough-circle",
                        highlight: "rough-highlight",
                        box: "rough-box",
                        underline: "rough-underline",
                        bracket: "rough-bracket",
                      };
                      return (
                        <span
                          className={`rough-notation ${styleClasses[dataAttr] || ""}`}
                          data-rough-notation={dataAttr}
                          {...props}
                        />
                      );
                    }
                    return <span {...props} />;
                  },
                  // Handle paragraphs containing rough-notation
                  p: ({ node, children, ...props }) => {
                    // Check if contains bracket type span
                    const childArray = React.Children.toArray(children);
                    const hasBracket = childArray.some((child: any) => {
                      if (React.isValidElement(child)) {
                        const childProps = child.props as any;
                        return (
                          childProps?.["data-rough-notation"] === "bracket"
                        );
                      }
                      return false;
                    });

                    if (hasBracket) {
                      return (
                        <p className="rough-bracket-container" {...props}>
                          {children}
                        </p>
                      );
                    }
                    return <p {...props}>{children}</p>;
                  },
                  table: ({ node, ...props }) => (
                    <div className="overflow-x-auto my-4">
                      <table
                        className="min-w-full border-collapse border border-slate-300"
                        {...props}
                      />
                    </div>
                  ),
                  th: ({ node, ...props }) => (
                    <th
                      className="border border-slate-300 px-3 py-2 bg-slate-100 font-semibold text-left"
                      {...props}
                    />
                  ),
                  td: ({ node, ...props }) => (
                    <td
                      className="border border-slate-300 px-3 py-2"
                      {...props}
                    />
                  ),
                  code: ({ node, className, children, ...props }) => {
                    const match = /language-(\w+)/.exec(className || "");
                    const isInline = !match && !className;

                    if (isInline) {
                      return (
                        <code
                          className="bg-slate-100 px-1.5 py-0.5 rounded text-sm font-mono text-pink-600"
                          {...props}
                        >
                          {children}
                        </code>
                      );
                    }

                    return (
                      <pre className="bg-slate-900 text-slate-100 p-4 rounded-lg overflow-x-auto my-4">
                        <code className={className} {...props}>
                          {children}
                        </code>
                      </pre>
                    );
                  },
                  blockquote: ({ node, ...props }) => (
                    <blockquote
                      className="border-l-4 border-purple-500 pl-4 my-4 italic text-slate-600 bg-purple-50/50 py-2 rounded-r"
                      {...props}
                    />
                  ),
                }}
              >
                {processLatexContent(content)}
              </ReactMarkdown>
            </div>

            {/* History Panel Overlay */}
            {showHistory && (
              <div className="absolute inset-0 z-10 bg-white/95 dark:bg-slate-900/95 backdrop-blur-sm flex flex-col animate-in fade-in duration-200">
                <div className="p-3 border-b border-slate-100 dark:border-slate-700 flex justify-between items-center bg-slate-50/50 dark:bg-slate-800/50">
                  <h3 className="text-xs font-bold text-slate-600 dark:text-slate-300 uppercase tracking-wider">
                    Version History
                  </h3>
                  <button
                    onClick={() => setShowHistory(false)}
                    className="text-slate-400 hover:text-slate-600 dark:text-slate-500 dark:hover:text-slate-300 p-1 hover:bg-slate-100 dark:hover:bg-slate-700 rounded"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>
                <div className="flex-1 overflow-y-auto p-2">
                  {operationHistory.length === 0 ? (
                    <div className="text-center py-10 text-slate-400 dark:text-slate-500 text-sm">
                      No history available
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {[...operationHistory].reverse().map((op) => (
                        <div
                          key={op.id}
                          className="p-3 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg hover:shadow-sm transition-all cursor-pointer group"
                        >
                          <div className="flex items-center justify-between mb-1">
                            <span
                              className={`text-[10px] font-bold uppercase px-1.5 py-0.5 rounded ${
                                op.action === "rewrite"
                                  ? "bg-purple-100 dark:bg-purple-900/50 text-purple-700 dark:text-purple-300"
                                  : op.action === "shorten"
                                    ? "bg-amber-100 dark:bg-amber-900/50 text-amber-700 dark:text-amber-300"
                                    : op.action === "automark"
                                      ? "bg-emerald-100 dark:bg-emerald-900/50 text-emerald-700 dark:text-emerald-300"
                                      : "bg-blue-100 dark:bg-blue-900/50 text-blue-700 dark:text-blue-300"
                              }`}
                            >
                              {op.action}
                            </span>
                            <span className="text-[10px] text-slate-400 dark:text-slate-500">
                              {new Date(op.timestamp).toLocaleTimeString()}
                            </span>
                          </div>
                          <div className="text-xs text-slate-600 dark:text-slate-400 truncate mb-1">
                            &quot;{op.input?.original_text?.substring(0, 35)}...&quot;
                          </div>
                          <div className="flex items-center gap-2 text-[10px] text-slate-400 dark:text-slate-500">
                            {op.source && (
                              <span className="flex items-center gap-0.5">
                                {op.source === "rag" ? (
                                  <Database className="w-2.5 h-2.5" />
                                ) : (
                                  <Globe className="w-2.5 h-2.5" />
                                )}
                                {op.source.toUpperCase()}
                              </span>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Podcast / Narration Area (Bottom Collapsible) */}
        <div className="shrink-0 bg-white dark:bg-slate-900 rounded-xl shadow-sm border border-slate-200 dark:border-slate-700 overflow-hidden transition-all">
          <div
            className="p-2 bg-slate-50/50 dark:bg-slate-800/50 flex justify-between items-center cursor-pointer hover:bg-slate-100/50 dark:hover:bg-slate-700/50 transition-colors"
            onClick={() => setIsPodcastExpanded(!isPodcastExpanded)}
          >
            <div className="flex items-center gap-2">
              {isPodcastExpanded ? (
                <ChevronDown className="w-4 h-4 text-slate-400 dark:text-slate-500" />
              ) : (
                <ChevronRight className="w-4 h-4 text-slate-400 dark:text-slate-500" />
              )}
              <div className="flex items-center gap-1 text-[10px] font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                <Radio className="w-3.5 h-3.5 text-purple-600 dark:text-purple-400" />
                Podcast Narration
              </div>
            </div>
            {!isPodcastExpanded && (
              <span className="text-[10px] text-slate-400 dark:text-slate-500 px-2">
                Click to expand
              </span>
            )}
          </div>

          {isPodcastExpanded && (
            <div className="p-4 border-t border-slate-100 dark:border-slate-700 animate-in slide-in-from-top-2">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  {ttsAvailable === false && (
                    <span className="text-[10px] text-amber-600 dark:text-amber-400 bg-amber-100 dark:bg-amber-900/40 px-1.5 py-0.5 rounded-full flex items-center gap-1">
                      <AlertCircle className="w-3 h-3" />
                      Script only (TTS not configured)
                    </span>
                  )}
                </div>
              </div>

              <div className="flex flex-col md:flex-row gap-3">
                <div className="flex-1 space-y-2">
                  <div className="flex gap-2">
                    <button
                      onClick={async () => {
                        if (!content.trim()) {
                          setNarrationError(
                            "Current note is empty, cannot generate narration.",
                          );
                          return;
                        }
                        setNarrationLoading(true);
                        setNarrationError(null);
                        try {
                          const res = await fetch(
                            apiUrl("/api/v1/co_writer/narrate"),
                            {
                              method: "POST",
                              headers: { "Content-Type": "application/json" },
                              body: JSON.stringify({
                                content,
                                style: narrationStyle,
                                skip_audio: !ttsAvailable,
                              }),
                            },
                          );
                          if (!res.ok) {
                            const detail = await res.text();
                            throw new Error(detail || `HTTP ${res.status}`);
                          }
                          const data = await res.json();
                          setNarrationScript(data.script || "");
                          setNarrationKeyPoints(data.key_points || []);
                          if (data.has_audio && data.audio_url) {
                            // Ensure the audio URL is properly formatted
                            const audioUrl = data.audio_url.startsWith("http")
                              ? data.audio_url
                              : apiUrl(data.audio_url);
                            setAudioInfo({
                              audioUrl: audioUrl,
                              audioId: data.audio_id,
                              voice: data.voice,
                            });
                          } else {
                            setAudioInfo(null);
                          }
                        } catch (e: any) {
                          setNarrationError(
                            e?.message ||
                              "Failed to generate narration, please try again.",
                          );
                        } finally {
                          setNarrationLoading(false);
                        }
                      }}
                      disabled={narrationLoading}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-gradient-to-r from-purple-600 to-indigo-600 text-white hover:from-purple-700 hover:to-indigo-700 disabled:opacity-60 shadow-sm"
                    >
                      {narrationLoading ? (
                        <>
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                          Generating Podcast
                        </>
                      ) : (
                        <>
                          <Mic className="w-3.5 h-3.5" />
                          Generate Podcast
                        </>
                      )}
                    </button>
                    <button
                      onClick={() => {
                        if (!narrationScript) return;
                        setShowNarrationNotebookModal(true);
                      }}
                      disabled={!narrationScript}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border border-slate-200 dark:border-slate-600 text-slate-700 dark:text-slate-300 hover:bg-white dark:hover:bg-slate-700 disabled:opacity-50"
                    >
                      <Book className="w-3.5 h-3.5" />
                      Save Podcast to Notebook
                    </button>
                  </div>
                  {narrationError && (
                    <div className="text-[11px] text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/30 border border-amber-200 dark:border-amber-800 rounded px-2 py-1 flex items-center gap-1">
                      <AlertCircle className="w-3 h-3" />
                      <span>{narrationError}</span>
                    </div>
                  )}
                  <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-600 rounded-lg p-2 h-32 overflow-y-auto text-xs text-slate-700 dark:text-slate-300">
                    {narrationScript ? (
                      <p className="whitespace-pre-wrap leading-relaxed">
                        {narrationScript}
                      </p>
                    ) : (
                      <span className="text-slate-400 dark:text-slate-500">
                        After generation, the narration script will appear here.
                      </span>
                    )}
                  </div>
                </div>

                <div className="w-full md:w-56 space-y-2">
                  <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-600 rounded-lg p-2 h-20 overflow-y-auto">
                    <div className="flex items-center gap-1 text-[10px] font-semibold text-slate-500 dark:text-slate-400 mb-1">
                      <Headphones className="w-3.5 h-3.5 text-indigo-600 dark:text-indigo-400" />
                      Key Points
                    </div>
                    {narrationKeyPoints && narrationKeyPoints.length > 0 ? (
                      <ul className="list-disc pl-4 text-[11px] text-slate-700 dark:text-slate-300 space-y-0.5">
                        {narrationKeyPoints.map((kp, idx) => (
                          <li key={idx} className="leading-snug">
                            {kp}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <div className="text-[11px] text-slate-400 dark:text-slate-500">
                        After generation, 3-5 key points will be listed here.
                      </div>
                    )}
                  </div>
                  <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-600 rounded-lg p-3">
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-1.5 text-[10px] font-semibold text-slate-600 dark:text-slate-400">
                        <Headphones className="w-3.5 h-3.5 text-purple-600 dark:text-purple-400" />
                        Podcast Audio
                      </div>
                      {audioInfo?.voice && (
                        <span className="text-[10px] text-slate-500 dark:text-slate-400 bg-purple-50 dark:bg-purple-900/40 px-1.5 py-0.5 rounded-full">
                          {audioInfo.voice}
                        </span>
                      )}
                    </div>
                    {audioInfo?.audioUrl ? (
                      <div className="w-full">
                        <audio
                          controls
                          className="w-full h-9"
                          style={{
                            borderRadius: "6px",
                            backgroundColor: "#f8fafc",
                          }}
                        >
                          <source src={audioInfo.audioUrl} type="audio/mpeg" />
                          Your browser does not support the audio element.
                        </audio>
                      </div>
                    ) : (
                      <div className="text-[11px] text-slate-400 dark:text-slate-500 italic py-2">
                        {ttsAvailable === false
                          ? "TTS not configured, script generation only."
                          : "After generation, you can play the podcast audio here."}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Global Loading Overlay */}
      {isProcessing && !popover && (
        <div className="fixed inset-0 bg-white/80 dark:bg-slate-900/80 backdrop-blur-sm z-50 flex items-center justify-center">
          <div className="bg-white dark:bg-slate-800 p-8 rounded-2xl shadow-2xl flex flex-col items-center gap-4 border border-slate-200 dark:border-slate-700">
            <Loader2 className="w-8 h-8 text-purple-600 dark:text-purple-400 animate-spin" />
            <span className="font-medium text-slate-700 dark:text-slate-200">
              Exporting...
            </span>
          </div>
        </div>
      )}

      {/* Add to Notebook Modal */}
      <AddToNotebookModal
        isOpen={showNotebookModal}
        onClose={() => setShowNotebookModal(false)}
        recordType="co_writer"
        title={`Co-Writer Document - ${new Date().toLocaleDateString()}`}
        userQuery="Co-Writer edited document"
        output={content}
        metadata={{
          char_count: content.length,
          line_count: content.split("\n").length,
        }}
      />

      {/* Notebook Import Modal */}
      <NotebookImportModal
        isOpen={showImportModal}
        onClose={() => setShowImportModal(false)}
        onImport={(importedContent) => {
          // Insert at current selection or end
          const newContent = content
            ? content + "\n\n" + importedContent
            : importedContent;
          setContent(newContent);
        }}
      />

      {/* Narration save to Notebook Modal */}
      <AddToNotebookModal
        isOpen={showNarrationNotebookModal}
        onClose={() => setShowNarrationNotebookModal(false)}
        recordType="co_writer"
        title={`Co-Writer Podcast - ${new Date().toLocaleDateString()}`}
        userQuery={content.substring(0, 120)}
        output={narrationScript}
        metadata={{
          char_count: narrationScript.length,
          style: narrationStyle,
          key_points: narrationKeyPoints,
          audio_url: audioInfo?.audioUrl,
          audio_id: audioInfo?.audioId,
          voice: audioInfo?.voice,
        }}
      />
    </div>
  );
}
