"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  ChevronsDownUp,
  ChevronsUpDown,
  ClipboardList,
  Download,
  Flag,
  Languages,
  Loader2,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  annotationApi,
  bilingualApi,
  immersiveReadingApi,
  type BilingualAnnotation,
  type BilingualPairing,
  type BilingualSection,
  type ChapterMapEntry,
  type DictionaryResult,
  ApiRequestError,
} from "@/lib/immersive-reading-api";
import { extractDictionaryWord, type DictionaryAnchorRect } from "@/lib/dictionary-ui";
import {
  getCachedWord,
  setCachedWord,
  getCachedTranslation,
  setCachedTranslation,
} from "@/lib/dictionary-cache";
import DictionaryPanel from "@/components/common/DictionaryPanel";
import { apiFetch } from "@/lib/api";

interface BilingualReaderProps {
  pairingId: string;
  onBack: () => void;
}

type IssueType = "misalignment" | "wrong_chapter" | "missing_translation" | "translation_error" | "other";

export function BilingualReader({ pairingId, onBack }: BilingualReaderProps) {
  const { t } = useTranslation();
  const [pairing, setPairing] = useState<BilingualPairing | null>(null);
  const [section, setSection] = useState<BilingualSection | null>(null);
  const [chapterIndex, setChapterIndex] = useState(0);
  const [loading, setLoading] = useState(true);
  const [sectionLoading, setSectionLoading] = useState(false);
  const [expandAll, setExpandAll] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [annotations, setAnnotations] = useState<BilingualAnnotation[]>([]);
  const [flagTarget, setFlagTarget] = useState<number | null>(null);
  const [showReview, setShowReview] = useState(false);
  const contentRef = useRef<HTMLDivElement>(null);
  const [dictPopover, setDictPopover] = useState<{ word: string; context: string; anchor: DictionaryAnchorRect; selectedText: string; initialMode: "dictionary" | "translate" } | null>(null);
  const [dictResult, setDictResult] = useState<DictionaryResult | null>(null);
  const [dictLoading, setDictLoading] = useState(false);
  const [dictError, setDictError] = useState<string | null>(null);
  const dictReqIdRef = useRef(0);
  const dictAbortRef = useRef<AbortController | null>(null);
  const lastSelectionRef = useRef("");

  useEffect(() => {
    bilingualApi.get(pairingId).then((data) => {
      setPairing(data);
      setLoading(false);
    });
    annotationApi.list(pairingId, "open").then((data) => {
      setAnnotations(data.annotations);
    });
  }, [pairingId]);

  const loadChapter = useCallback(
    (index: number) => {
      if (!pairing?.chapter_map?.length) return;
      const clamped = Math.max(0, Math.min(index, pairing.chapter_map.length - 1));
      setChapterIndex(clamped);
      const entry = pairing.chapter_map[clamped];
      setSectionLoading(true);
      bilingualApi
        .section(pairingId, entry.id)
        .then(setSection)
        .catch(() => setSection(null))
        .finally(() => setSectionLoading(false));
    },
    [pairing, pairingId],
  );

  useEffect(() => {
    if (pairing?.aligned && pairing.chapter_map?.length) {
      loadChapter(0);
    }
  }, [pairing, loadChapter]);

  // Cancel any pending dictionary lookup when chapter changes.
  useEffect(() => {
    dictAbortRef.current?.abort();
    dictReqIdRef.current++;
    setDictPopover(null);
    setDictResult(null);
    setDictLoading(false);
  }, [chapterIndex, pairingId]);

  // Cancel on unmount.
  useEffect(() => {
    return () => {
      dictAbortRef.current?.abort();
    };
  }, []);

  const handleExport = async () => {
    setExporting(true);
    try {
      const response = await apiFetch(bilingualApi.exportUrl(pairingId), { method: "POST" });
      if (!response.ok) throw new Error("Export failed");
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${pairing?.en_title || "book"}_bilingual.epub`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch {
      // ignore
    } finally {
      setExporting(false);
    }
  };

  const handleFlag = async (groupIndex: number, issueType: IssueType, note: string) => {
    if (!pairing?.chapter_map?.[chapterIndex]) return;
    const chapterId = pairing.chapter_map[chapterIndex].id;
    try {
      const ann = await annotationApi.add(pairingId, {
        chapter_id: chapterId,
        group_index: groupIndex,
        issue_type: issueType,
        note,
      });
      setAnnotations((prev) => [...prev, ann]);
    } catch {
      // ignore
    }
    setFlagTarget(null);
  };

  const handleResolveAnnotation = async (annotationId: string) => {
    try {
      await annotationApi.resolve(pairingId, annotationId, true);
      setAnnotations((prev) => prev.filter((a) => a.id !== annotationId));
    } catch {
      // ignore
    }
  };

  const handleDictionaryLookup = useCallback(async (word: string, context: string) => {
    dictAbortRef.current?.abort();
    const controller = new AbortController();
    dictAbortRef.current = controller;
    const reqId = ++dictReqIdRef.current;

    // Client-side cache: instant display for previously looked-up words.
    const cached = getCachedWord(word);
    if (cached) {
      setDictResult(cached);
      setDictError(null);
      setDictLoading(false);
      return;
    }

    setDictLoading(true);
    setDictResult(null);
    setDictError(null);
    try {
      const result = await immersiveReadingApi.dictionary(word, context, controller.signal);
      if (reqId !== dictReqIdRef.current) return;
      setCachedWord(word, result);
      setDictResult(result);
    } catch (err) {
      if (controller.signal.aborted || reqId !== dictReqIdRef.current) return;
      const msg = err instanceof Error ? err.message : String(err);
      const status = err instanceof ApiRequestError ? err.status : undefined;
      if (status === 503) {
        setDictError(msg || t("Local dictionary unavailable. Run `ollama serve` then `ollama pull qwen3.5:2b`."));
      } else if (status === 504) {
        setDictError(t("Dictionary lookup timed out. The local model may still be loading."));
      } else {
        setDictError(t("Lookup failed.") + " " + msg);
      }
    } finally {
      if (reqId === dictReqIdRef.current) setDictLoading(false);
    }
  }, [t]);

  const handleTranslateText = useCallback(async (text: string) => {
    dictAbortRef.current?.abort();
    const controller = new AbortController();
    dictAbortRef.current = controller;
    const reqId = ++dictReqIdRef.current;
    const targetLang = "Chinese";
    setDictLoading(true);
    setDictResult(null);
    // Client-side cache: instant display for previously translated text.
    const cached = getCachedTranslation(text, targetLang);
    if (cached) {
      setDictResult({
        word: text.length > 30 ? text.slice(0, 30) + "\u2026" : text,
        phonetic: "",
        definitions: [],
        context_note: cached,
      });
      setDictError(null);
      setDictLoading(false);
      return;
    }
    try {
      const result = await immersiveReadingApi.translate(text, targetLang, controller.signal);
      if (controller.signal.aborted || reqId !== dictReqIdRef.current) return;
      setCachedTranslation(text, targetLang, result.translation);
      setDictResult({
        word: text.length > 30 ? text.slice(0, 30) + "\u2026" : text,
        phonetic: "",
        definitions: [],
        context_note: result.translation,
      });
      setDictError(null);
    } catch (err) {
      if (controller.signal.aborted || reqId !== dictReqIdRef.current) return;
      const status = err instanceof ApiRequestError ? err.status : undefined;
      const msg = err instanceof Error ? err.message : String(err);
      let errorMessage: string;
      if (status === 504) {
        errorMessage = t("Translation timed out. The model may still be loading.");
      } else if (status === 503) {
        errorMessage = msg || t("Translation service unavailable. Please try again.");
      } else if (status === 429) {
        errorMessage = t("Rate limit exceeded. Please wait a moment.");
      } else if (status && status >= 500) {
        errorMessage = t("Translation service unavailable. Please try again.");
      } else {
        errorMessage = t("Translation failed.") + (msg ? ` ${msg}` : "");
      }
      setDictError(errorMessage);
    } finally {
      if (reqId === dictReqIdRef.current) setDictLoading(false);
    }
  }, [t]);

  const handleTextSelection = useCallback(() => {
    const selection = window.getSelection();
    const text = selection?.toString().trim() || "";
    if (!selection || !text || selection.rangeCount === 0 || !contentRef.current) {
      lastSelectionRef.current = "";
      return;
    }
    const anchor = selection.anchorNode;
    if (!anchor || !contentRef.current.contains(anchor)) {
      return;
    }
    if (lastSelectionRef.current === text) return;
    lastSelectionRef.current = text;
    // Get the sentence containing the selection for context.
    const fullText = selection.anchorNode.parentElement?.closest("p")?.textContent || "";
    const rect = selection.getRangeAt(0).getBoundingClientRect();
    const word = extractDictionaryWord(text);
    // Single English word → dictionary mode. Multi-word / sentence → translate.
    const isSingleWord = !!word;
    const selectedText = isSingleWord ? word : text.slice(0, 2000);
    if (!selectedText.trim()) return;
    const context = fullText.slice(0, 2000);
    const initialMode: "dictionary" | "translate" = isSingleWord ? "dictionary" : "translate";
    setDictPopover({
      word: isSingleWord ? word : selectedText,
      context,
      selectedText,
      initialMode,
      anchor: { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom },
    });
    if (isSingleWord) {
      handleDictionaryLookup(word, context);
    } else {
      handleTranslateText(selectedText);
    }
  }, [handleDictionaryLookup, handleTranslateText]);

  useEffect(() => {
    const ref = contentRef.current;
    if (!ref) return;
    let timer: number | null = null;
    const scheduleSelection = () => {
      if (timer !== null) window.clearTimeout(timer);
      // Mobile browsers may finish the native selection after pointerup.
      timer = window.setTimeout(handleTextSelection, 80);
    };
    ref.addEventListener("pointerup", scheduleSelection);
    document.addEventListener("selectionchange", scheduleSelection);
    return () => {
      ref.removeEventListener("pointerup", scheduleSelection);
      document.removeEventListener("selectionchange", scheduleSelection);
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [handleTextSelection, sectionLoading]);

  const handleDictLookupClick = () => {
    if (!dictPopover) return;
    handleDictionaryLookup(dictPopover.word, dictPopover.context);
  };

  const handleTranslateSelection = async () => {
    if (!dictPopover) return;
    handleTranslateText(dictPopover.selectedText || dictPopover.word);
  };

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="size-6 animate-spin text-[var(--muted-foreground)]" />
      </div>
    );
  }

  if (!pairing) return null;

  if (!pairing.aligned) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4 p-8 text-center">
        <Languages className="size-10 text-[var(--muted-foreground)]" />
        <p className="text-[var(--muted-foreground)]">
          {t("This pairing has not been aligned yet.")}
        </p>
      </div>
    );
  }

  const chapters: ChapterMapEntry[] = pairing.chapter_map || [];
  const currentChapter = chapters[chapterIndex];
  const flaggedGroups = new Set(
    annotations
      .filter((a) => a.chapter_id === currentChapter?.id)
      .map((a) => a.group_index),
  );

  return (
    <div className="flex h-full flex-col">
      {/* Toolbar */}
      <div className="flex items-center gap-2 border-b border-[var(--border)] px-4 py-2">
        <button
          onClick={onBack}
          className="flex items-center gap-1 rounded-lg px-2 py-1 text-sm text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
        >
          <ChevronLeft size={18} />
        </button>
        <div className="flex min-w-0 flex-1 flex-col">
          <span className="truncate text-sm font-medium">{pairing.en_title}</span>
          <span className="truncate text-xs text-[var(--muted-foreground)]">
            {currentChapter?.en_title || currentChapter?.id} · {chapterIndex + 1}/{chapters.length}
            {annotations.length > 0 && ` · ${annotations.length} ${t("flagged")}`}
          </span>
        </div>
        <button
          onClick={() => setExpandAll((v) => !v)}
          className="flex items-center gap-1 rounded-lg px-2 py-1.5 text-xs text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
          title={expandAll ? t("Collapse all") : t("Expand all")}
        >
          {expandAll ? <ChevronsDownUp size={15} /> : <ChevronsUpDown size={15} />}
        </button>
        {annotations.length > 0 && (
          <button
            onClick={() => setShowReview(true)}
            className="flex items-center gap-1 rounded-lg bg-amber-500/10 px-2 py-1.5 text-xs font-medium text-amber-600 hover:bg-amber-500/20"
            title={t("Review flagged issues")}
          >
            <ClipboardList size={14} />
            {annotations.length}
          </button>
        )}
        <button
          onClick={handleExport}
          disabled={exporting}
          className="flex items-center gap-1 rounded-lg bg-[var(--primary)] px-3 py-1.5 text-xs font-medium text-[var(--primary-foreground)] hover:opacity-90 disabled:opacity-50"
        >
          {exporting ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
          {t("Export EPUB")}
        </button>
      </div>

      {/* Chapter navigation */}
      <div className="flex items-center gap-2 border-b border-[var(--border)] px-4 py-1.5">
        <button
          onClick={() => loadChapter(chapterIndex - 1)}
          disabled={chapterIndex === 0}
          className="rounded-md p-1 text-[var(--muted-foreground)] hover:bg-[var(--muted)] disabled:opacity-30"
        >
          <ChevronLeft size={18} />
        </button>
        <select
          value={chapterIndex}
          onChange={(e) => loadChapter(Number(e.target.value))}
          className="min-w-0 flex-1 rounded-md border border-[var(--border)] bg-[var(--background)] px-2 py-1 text-sm"
        >
          {chapters.map((ch, i) => (
            <option key={ch.id} value={i}>
              {ch.en_title || ch.id}
            </option>
          ))}
        </select>
        <button
          onClick={() => loadChapter(chapterIndex + 1)}
          disabled={chapterIndex >= chapters.length - 1}
          className="rounded-md p-1 text-[var(--muted-foreground)] hover:bg-[var(--muted)] disabled:opacity-30"
        >
          <ChevronRight size={18} />
        </button>
      </div>

     {/* Content */}
     <div ref={contentRef} className="relative flex-1 overflow-y-auto px-4 py-6">
        {sectionLoading ? (
          <div className="flex justify-center py-12">
            <Loader2 className="size-6 animate-spin text-[var(--muted-foreground)]" />
          </div>
        ) : section ? (
          <div className="mx-auto max-w-2xl space-y-1">
            {section.en_title && (
              <h2 className="mb-4 text-xl font-bold">{section.en_title}</h2>
            )}
            {section.groups.map((group, gi) => (
              <BilingualGroup
                key={gi}
                group={group}
                index={gi}
                forceOpen={expandAll}
                isFlagged={flaggedGroups.has(gi)}
                onFlag={() => setFlagTarget(gi)}
              />
            ))}
            {section.groups.length === 0 && (
              <p className="py-8 text-center text-[var(--muted-foreground)]">
                {t("No aligned content in this chapter.")}
              </p>
            )}
          </div>
        ) : (
          <p className="py-8 text-center text-[var(--muted-foreground)]">
            {t("Failed to load this chapter.")}
          </p>
        )}
        {dictPopover && (
          <DictionaryPanel
            word={dictPopover.word}
            anchor={dictPopover.anchor}
            loading={dictLoading}
            result={dictResult}
            error={dictError}
            initialMode={dictPopover.initialMode}
            onLookup={handleDictLookupClick}
            onTranslate={handleTranslateSelection}
            onClose={() => { lastSelectionRef.current = ""; dictAbortRef.current?.abort(); dictReqIdRef.current++; setDictPopover(null); setDictResult(null); setDictError(null); setDictLoading(false); }}
          />
        )}
      </div>

      {/* Flag dialog */}
      {flagTarget !== null && (
        <FlagDialog
          groupIndex={flagTarget}
          onClose={() => setFlagTarget(null)}
          onSubmit={(issueType, note) => handleFlag(flagTarget, issueType, note)}
        />
      )}

      {/* Review panel */}
      {showReview && (
        <ReviewPanel
          annotations={annotations}
          onClose={() => setShowReview(false)}
          onResolve={handleResolveAnnotation}
          pairingId={pairingId}
        />
      )}
    </div>
  );
}

function BilingualGroup({
  group,
  index,
  forceOpen,
  isFlagged,
  onFlag,
}: {
  group: import("@/lib/immersive-reading-api").BilingualAlignGroup;
  index: number;
  forceOpen: boolean;
  isFlagged: boolean;
  onFlag: () => void;
}) {
  const [open, setOpen] = useState(false);
  const { t } = useTranslation();

  useEffect(() => {
    setOpen(forceOpen);
  }, [forceOpen]);

  if (group.zh.length === 0) {
    return (
      <div className="group/para relative space-y-1">
        {group.en.map((para, pi) => (
          <p key={pi} className="leading-7 text-[var(--foreground)]">
            {para}
          </p>
        ))}
        <button
          onClick={onFlag}
          className="absolute -right-8 top-0 rounded p-1 text-[var(--muted-foreground)] opacity-0 transition hover:bg-[var(--muted)] group-hover/para:opacity-100"
          title={t("Flag issue")}
        >
          <Flag size={14} className={isFlagged ? "fill-amber-400 text-amber-500" : ""} />
        </button>
      </div>
    );
  }

  return (
    <div className="group/para relative space-y-0.5">
      {group.en.map((para, pi) => (
        <p key={pi} className="leading-7 text-[var(--foreground)]">
          {para}
        </p>
      ))}
      <details
        open={open}
        onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}
        className="bilingual-zh-details my-1 rounded-md border-l-[3px] border-l-[var(--primary)] bg-[var(--muted)]/40 px-3 py-2"
      >
        <summary className="cursor-pointer text-sm font-semibold text-[var(--primary)]">
          {t("Show Chinese")}
        </summary>
        <div className="mt-1.5 space-y-1.5 pt-1">
          {group.zh.map((para, pi) => (
            <p
              key={pi}
              className="text-sm leading-7 text-[var(--foreground)]"
              style={{ fontFamily: '"PingFang TC","Heiti TC","Microsoft JhengHei","Noto Serif CJK TC",serif' }}
            >
              {para}
            </p>
          ))}
        </div>
      </details>
      {group.low_confidence && group.shape !== "1:1" && (
        <span className="text-xs text-[var(--muted-foreground)]">({group.shape})</span>
      )}
      <button
        onClick={onFlag}
        className="absolute -right-8 top-0 rounded p-1 text-[var(--muted-foreground)] opacity-0 transition hover:bg-[var(--muted)] group-hover/para:opacity-100"
        title={t("Flag issue")}
      >
        <Flag size={14} className={isFlagged ? "fill-amber-400 text-amber-500" : ""} />
      </button>
    </div>
  );
}

const ISSUE_TYPES: { value: IssueType; labelKey: string }[] = [
  { value: "misalignment", labelKey: "Misaligned paragraphs" },
  { value: "wrong_chapter", labelKey: "Wrong chapter mapping" },
  { value: "missing_translation", labelKey: "Missing translation" },
  { value: "translation_error", labelKey: "Translation quality issue" },
  { value: "other", labelKey: "Other" },
];

function FlagDialog({
  groupIndex,
  onClose,
  onSubmit,
}: {
  groupIndex: number;
  onClose: () => void;
  onSubmit: (issueType: IssueType, note: string) => void;
}) {
  const { t } = useTranslation();
  const [issueType, setIssueType] = useState<IssueType>("misalignment");
  const [note, setNote] = useState("");

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40" onClick={onClose}>
      <div
        className="w-[420px] rounded-xl bg-[var(--background)] p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h3 className="flex items-center gap-2 text-sm font-semibold">
            <AlertTriangle size={16} className="text-amber-500" />
            {t("Flag alignment issue")} (#{groupIndex + 1})
          </h3>
          <button onClick={onClose} className="rounded p-1 text-[var(--muted-foreground)] hover:bg-[var(--muted)]">
            <X size={16} />
          </button>
        </div>
        <div className="space-y-3">
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-[var(--muted-foreground)]">{t("Issue type")}</label>
            <select
              value={issueType}
              onChange={(e) => setIssueType(e.target.value as IssueType)}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm"
            >
              {ISSUE_TYPES.map((it) => (
                <option key={it.value} value={it.value}>
                  {t(it.labelKey)}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-[var(--muted-foreground)]">{t("Note (optional)")}</label>
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder={t("Describe what's wrong...")}
              rows={3}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm"
            />
          </div>
          <div className="flex justify-end gap-2 pt-1">
            <button
              onClick={onClose}
              className="rounded-lg px-3 py-1.5 text-sm text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
            >
              {t("Cancel")}
            </button>
            <button
              onClick={() => onSubmit(issueType, note)}
              className="rounded-lg bg-amber-500 px-4 py-1.5 text-sm font-medium text-white hover:bg-amber-600"
            >
              {t("Flag")}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function ReviewPanel({
  annotations,
  onClose,
  onResolve,
  pairingId,
}: {
  annotations: BilingualAnnotation[];
  onClose: () => void;
  onResolve: (id: string) => void;
  pairingId: string;
}) {
  const { t } = useTranslation();
  const [report, setReport] = useState("");
  const [copied, setCopied] = useState(false);

  const loadReport = useCallback(async () => {
    try {
      const data = await annotationApi.reviewReport(pairingId);
      setReport(data.report);
    } catch {
      // ignore
    }
  }, [pairingId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadReport(), 0);
    return () => window.clearTimeout(timer);
  }, [loadReport]);

  const handleCopy = () => {
    navigator.clipboard.writeText(report);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40" onClick={onClose}>
      <div
        className="flex max-h-[80vh] w-[640px] flex-col rounded-xl bg-[var(--background)] shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-[var(--border)] px-5 py-3">
          <h3 className="flex items-center gap-2 text-sm font-semibold">
            <ClipboardList size={16} />
            {t("Review Issues")} ({annotations.length})
          </h3>
          <div className="flex items-center gap-2">
            <button
              onClick={handleCopy}
              className="rounded-lg px-2 py-1 text-xs text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
            >
              {copied ? t("Copied!") : t("Copy report for Codex")}
            </button>
            <button onClick={onClose} className="rounded p-1 text-[var(--muted-foreground)] hover:bg-[var(--muted)]">
              <X size={16} />
            </button>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto p-5">
          {annotations.length === 0 ? (
            <p className="text-center text-sm text-[var(--muted-foreground)]">{t("No open issues.")}</p>
          ) : (
            <div className="space-y-3">
              {annotations.map((ann) => (
                <div
                  key={ann.id}
                  className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-3"
                >
                  <div className="mb-1 flex items-center justify-between">
                    <span className="flex items-center gap-1.5 text-xs font-medium text-amber-600">
                      <Flag size={12} className="fill-amber-400" />
                      {t(ISSUE_TYPES.find((it) => it.value === ann.issue_type)?.labelKey || ann.issue_type)}
                    </span>
                    <button
                      onClick={() => onResolve(ann.id)}
                      className="text-xs text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                    >
                      {t("Resolve")}
                    </button>
                  </div>
                  <p className="text-xs text-[var(--muted-foreground)]">
                    {ann.chapter_title} · #{ann.group_index + 1} · {ann.shape}
                  </p>
                  {ann.note && (
                    <p className="mt-1 text-sm italic text-[var(--foreground)]">&ldquo;{ann.note}&rdquo;</p>
                  )}
                  <div className="mt-2 space-y-1">
                    <p className="line-clamp-2 text-xs text-[var(--muted-foreground)]">
                      {t("English")}: {ann.en_text}
                    </p>
                    <p className="line-clamp-2 text-xs text-[var(--muted-foreground)]">
                      {t("Chinese")}: {ann.zh_text}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
        {report && (
          <div className="border-t border-[var(--border)] px-5 py-2">
            <p className="text-xs text-[var(--muted-foreground)]">
              {t("Copy the report above and paste it to Codex to generate alignment fixes.")}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
