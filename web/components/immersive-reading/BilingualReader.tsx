"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  AudioLines,
  Bookmark,
  BookmarkPlus,
  BookOpen,
  BookOpenCheck,
  Brain,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  ChevronsDownUp,
  ChevronsUpDown,
  ClipboardList,
  Columns2,
  Download,
  Eye,
  FileText,
  Flag,
  Keyboard,
  Languages,
  Link2,
  ListChecks,
  Loader2,
  MousePointerClick,
  MoreHorizontal,
  Pencil,
  Trash2,
  Type,
  Unlink2,
  Volume2,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  annotationApi,
  bilingualApi,
  immersiveReadingApi,
  type BilingualAnnotation,
  type BilingualBookmark,
  type BilingualExportStyle,
  type BilingualNavigation,
  type BilingualPairing,
  type BilingualPositionInput,
  type BilingualReadingPosition,
  type BilingualSection,
  type ChapterMapEntry,
  type DictionaryResult,
  type VocabEntry,
  type VocabularyBand,
  type VocabularyDifficultyPreview,
  type VocabularyDifficultyWord,
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
import MiniDictionaryTooltip from "@/components/common/MiniDictionaryTooltip";
import TranslationTaskBoardPanel from "@/components/translation/TranslationTaskBoard";
import { useResponsiveLayout } from "@/hooks/useResponsiveLayout";
import {
  translationTaskApi,
  type TranslationChapterSummary,
  type TranslationTask,
} from "@/lib/translation-tasks-api";
import { apiFetch } from "@/lib/api";
import {
  BILINGUAL_CLICK_LOOKUP_STORAGE_KEY,
  BILINGUAL_DUAL_PANE_MIN_CONTAINER_WIDTH_PX,
  BILINGUAL_FONT_FAMILY_STORAGE_KEY,
  BILINGUAL_FONT_SIZE_STORAGE_KEY,
  BILINGUAL_READER_MODE_STORAGE_KEY,
  BILINGUAL_THEME_STORAGE_KEY,
  breaksDualScrollLink,
  isParagraphSideTap,
  parseBilingualFontFamily,
  parseBilingualFontSize,
  parseBilingualReaderMode,
  parseBilingualTheme,
  paragraphSwipeFromPoints,
  parseStoredBoolean,
  readerShortcutFromKeyboardEvent,
  nextReaderToolbarVisible,
  scrollPaneToGroup,
  shouldIgnoreLookupTarget,
  supportsDualPaneAtContainerWidth,
  visibleGroupFromElements,
  wordRangeAtPoint,
  type BilingualFontFamily,
  type BilingualFontSize,
  type BilingualReaderMode,
  type BilingualReaderShortcut,
  type BilingualTheme,
} from "@/lib/bilingual-reader-ux";
import {
  playWordPronunciation,
  subscribePronunciationState,
  type PronunciationPlaybackState,
  type WordPronunciationAccent,
} from "@/lib/word-pronunciation";

interface BilingualReaderProps {
  pairingId: string;
  onBack: () => void;
  initialChapterId?: string;
  initialGroupIndex?: number;
  onVocabularyAdded: () => void;
  onToast: (message: string) => void;
  onErrorToast: (message: string) => void;
}

type ReviewMode = "cloze" | "choice";

type ChapterPreviewState = {
  chapterIndex: number;
  loading: boolean;
  error: string | null;
  data: VocabularyDifficultyPreview | null;
};

type IssueType = "misalignment" | "wrong_chapter" | "missing_translation" | "translation_error" | "other";
type DictionaryPresentation = "mini" | "full";

const THEME_STYLES: Record<BilingualTheme, CSSProperties> = {
  system: {},
  sepia: {
    backgroundColor: "#f8f1e3",
    color: "#2d241e",
    "--background": "#f8f1e3",
    "--foreground": "#2d241e",
    "--card": "#efe6d5",
    "--muted": "#e8deca",
    "--muted-foreground": "#786b5e",
    "--border": "#dfd3be",
    "--primary": "#8c4f27",
    "--primary-foreground": "#ffffff",
  } as CSSProperties,
  dark: {
    backgroundColor: "#18181b",
    color: "#fafafa",
    "--background": "#18181b",
    "--foreground": "#fafafa",
    "--card": "#27272a",
    "--muted": "#3f3f46",
    "--muted-foreground": "#a1a1aa",
    "--border": "#3f3f46",
    "--primary": "#60a5fa",
    "--primary-foreground": "#000000",
  } as CSSProperties,
  oled: {
    backgroundColor: "#000000",
    color: "#f1f5f9",
    "--background": "#000000",
    "--foreground": "#f1f5f9",
    "--card": "#0a0a0a",
    "--muted": "#171717",
    "--muted-foreground": "#94a3b8",
    "--border": "#262626",
    "--primary": "#38bdf8",
    "--primary-foreground": "#000000",
  } as CSSProperties,
};

const FONT_SIZE_STYLES: Record<BilingualFontSize, { en: string; zh: string }> = {
  sm: { en: "text-[14px] leading-[1.65]", zh: "text-[13px] leading-[1.65]" },
  base: { en: "text-[16px] leading-[1.8]", zh: "text-[14px] leading-[1.8]" },
  lg: { en: "text-[18px] leading-[1.9]", zh: "text-[16px] leading-[1.9]" },
  xl: { en: "text-[20px] leading-[2.0]", zh: "text-[18px] leading-[2.0]" },
  "2xl": { en: "text-[22px] leading-[2.1]", zh: "text-[20px] leading-[2.1]" },
};

const KEYBOARD_HINT_STORAGE_KEY = "deeptutor.bilingual-reader.shortcut-hint-shown";
const TOUCH_LOOKUP_TAP_MAX_DURATION_MS = 320;
const TOUCH_LOOKUP_MOVE_TOLERANCE_PX = 10;
const TOUCH_LOOKUP_CLICK_GUARD_MS = 420;

function paragraphSwipeEdgeInset(width: number): number {
  return Math.max(36, Math.min(88, Math.round(width * 0.14)));
}

function rangePointFromOffsets(container: HTMLElement, start: number, end: number): Range | null {
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
  let cursor = 0;
  let currentNode: Node | null;
  let rangeStart: { node: Node; offset: number } | null = null;
  let rangeEnd: { node: Node; offset: number } | null = null;
  while ((currentNode = walker.nextNode())) {
    const text = currentNode.textContent || "";
    const nodeEnd = cursor + text.length;
    if (!rangeStart && start >= cursor && start <= nodeEnd) {
      rangeStart = { node: currentNode, offset: start - cursor };
    }
    if (end >= cursor && end <= nodeEnd) {
      rangeEnd = { node: currentNode, offset: end - cursor };
      break;
    }
    cursor = nodeEnd;
  }
  if (!rangeStart || !rangeEnd) return null;
  const range = document.createRange();
  range.setStart(rangeStart.node, rangeStart.offset);
  range.setEnd(rangeEnd.node, rangeEnd.offset);
  return range;
}

function normalizeFingerprint(text: string): string {
  return text
    .toLowerCase()
    .replace(/<[^>]+>/g, " ")
    .replace(/[\s\u200b]+/g, " ")
    .trim();
}

function groupIndexFromNode(node: Node | null, fallback: number): number {
  const element = node instanceof Element ? node : node?.parentElement;
  const group = element?.closest<HTMLElement>("[data-group-index]");
  const value = Number(group?.dataset.groupIndex);
  return Number.isFinite(value) && value >= 0 ? value : fallback;
}

function dictionarySeedFromGroup(group: { en: string[] } | undefined): string {
  const words = (group?.en?.join(" ") || "").match(/[A-Za-z][A-Za-z'-]*/g) || [];
  const stopWords = new Set([
    "the", "a", "an", "and", "or", "but", "if", "of", "to", "in", "on", "at",
    "for", "with", "from", "by", "as", "is", "are", "was", "were", "be", "been",
    "it", "its", "this", "that", "these", "those", "he", "she", "they", "we",
  ]);
  return words.find((word) => word.length >= 4 && !stopWords.has(word.toLowerCase())) || words[0] || "";
}

function paragraphLineRectAtY(paragraph: HTMLParagraphElement, y: number) {
  const range = document.createRange();
  range.selectNodeContents(paragraph);
  const rects = Array.from(range.getClientRects());
  return (
    rects.find((rect) => y >= rect.top - 4 && y <= rect.bottom + 4) ||
    rects[rects.length - 1] ||
    null
  );
}

const DIFFICULTY_CLASSES: Record<VocabularyBand, string> = {
  core: "decoration-primary/50 underline decoration-dotted underline-offset-4",
  common: "decoration-primary/40 underline decoration-dotted underline-offset-4",
  advanced: "rounded bg-amber-500/12 px-0.5 text-amber-700 dark:text-amber-300",
  low: "rounded bg-rose-500/12 px-0.5 text-rose-700 dark:text-rose-300",
  unknown: "rounded bg-sky-500/12 px-0.5 text-sky-700 dark:text-sky-300",
};

function difficultyIndex(words: VocabularyDifficultyWord[]): Map<string, VocabularyBand> {
  const result = new Map<string, VocabularyBand>();
  for (const item of words) {
    result.set(item.word.toLowerCase(), item.band);
    result.set(item.lemma.toLowerCase(), item.band);
  }
  return result;
}

function renderEnglishParagraph(
  paragraph: string,
  words: Map<string, VocabularyBand>,
): ReactNode {
  if (!words.size) return paragraph;
  const pattern = /[A-Za-z]+(?:['’-][A-Za-z]+)?/g;
  const nodes: ReactNode[] = [];
  let cursor = 0;
  let match: RegExpExecArray | null;
  let key = 0;
  while ((match = pattern.exec(paragraph))) {
    if (match.index > cursor) nodes.push(paragraph.slice(cursor, match.index));
    const band = words.get(match[0].toLowerCase());
    nodes.push(
      band ? (
        <span key={key++} className={DIFFICULTY_CLASSES[band]}>
          {match[0]}
        </span>
      ) : (
        match[0]
      ),
    );
    cursor = match.index + match[0].length;
  }
  if (cursor < paragraph.length) nodes.push(paragraph.slice(cursor));
  return nodes;
}

export function BilingualReader({
  pairingId,
  onBack,
  initialChapterId,
  initialGroupIndex = 0,
  onVocabularyAdded,
  onToast,
  onErrorToast,
}: BilingualReaderProps) {
  const { t } = useTranslation();
  const [pairing, setPairing] = useState<BilingualPairing | null>(null);
  const [section, setSection] = useState<BilingualSection | null>(null);
  const [chapterIndex, setChapterIndex] = useState(0);
  const [loading, setLoading] = useState(true);
  const [sectionLoading, setSectionLoading] = useState(false);
  const [preferredReaderMode, setPreferredReaderMode] = useState<BilingualReaderMode>(() =>
    parseBilingualReaderMode(
      typeof window === "undefined"
        ? null
        : window.localStorage.getItem(BILINGUAL_READER_MODE_STORAGE_KEY),
    ),
  );
  const [theme, setTheme] = useState<BilingualTheme>(() =>
    parseBilingualTheme(
      typeof window === "undefined"
        ? null
        : window.localStorage.getItem(BILINGUAL_THEME_STORAGE_KEY),
    ),
  );
  const [fontSize, setFontSize] = useState<BilingualFontSize>(() =>
    parseBilingualFontSize(
      typeof window === "undefined"
        ? null
        : window.localStorage.getItem(BILINGUAL_FONT_SIZE_STORAGE_KEY),
    ),
  );
  const [fontFamily, setFontFamily] = useState<BilingualFontFamily>(() =>
    parseBilingualFontFamily(
      typeof window === "undefined"
        ? null
        : window.localStorage.getItem(BILINGUAL_FONT_FAMILY_STORAGE_KEY),
    ),
  );
  const [readerContainerWidth, setReaderContainerWidth] = useState<number | null>(null);
  const [dualScrollLinked, setDualScrollLinked] = useState(true);
  const [keyboardHint, setKeyboardHint] = useState<string | null>(null);
  const [expandAll, setExpandAll] = useState(false);
  const [manualOpenGroups, setManualOpenGroups] = useState<Set<number>>(new Set());
  const [manualClosedGroups, setManualClosedGroups] = useState<Set<number>>(new Set());
  const [activeGroup, setActiveGroup] = useState(0);
  const [hoveredGroup, setHoveredGroup] = useState<number | null>(null);
  const [pinnedHoverGroup, setPinnedHoverGroup] = useState<number | null>(null);
  const [clickLookupEnabled, setClickLookupEnabled] = useState(() =>
    typeof window === "undefined"
      ? false
      : parseStoredBoolean(window.localStorage.getItem(BILINGUAL_CLICK_LOOKUP_STORAGE_KEY)),
  );
  const layout = useResponsiveLayout();
  const [mobileToolbarVisible, setMobileToolbarVisible] = useState(true);
  const [showMoreMenu, setShowMoreMenu] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [annotations, setAnnotations] = useState<BilingualAnnotation[]>([]);
  const [bookmarks, setBookmarks] = useState<BilingualBookmark[]>([]);
  const [navigation, setNavigation] = useState<BilingualNavigation | null>(null);
  const [flagTarget, setFlagTarget] = useState<number | null>(null);
  const [showReview, setShowReview] = useState(false);
  const [showBookmarks, setShowBookmarks] = useState(false);
  const [showTaskBoard, setShowTaskBoard] = useState(false);
  const [showExportDialog, setShowExportDialog] = useState(false);
  const [exportStyle, setExportStyle] = useState<BilingualExportStyle>("folded");
  const [exportFontFamily, setExportFontFamily] = useState("Noto Serif CJK TC");
  const [exportFontAssetId, setExportFontAssetId] = useState("");
  const [fontFileName, setFontFileName] = useState("");
  const [exportCss, setExportCss] = useState("");
  const [uploadingFont, setUploadingFont] = useState(false);
  const [showAppearanceModal, setShowAppearanceModal] = useState(false);
  const [showShortcutsModal, setShowShortcutsModal] = useState(false);
  const [chapterTaskSummaries, setChapterTaskSummaries] = useState<TranslationChapterSummary[]>([]);
  const [chapterPreview, setChapterPreview] = useState<ChapterPreviewState | null>(null);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [audioState, setAudioState] = useState<PronunciationPlaybackState>({
    isPlaying: false,
    word: null,
    accent: null,
  });

  const contentRef = useRef<HTMLDivElement>(null);
  const inlinePaneRef = useRef<HTMLDivElement>(null);
  const englishPaneRef = useRef<HTMLDivElement>(null);
  const chinesePaneRef = useRef<HTMLDivElement>(null);
  const dualSyncGuardRef = useRef(0);
  const dualScrollLinkedRef = useRef(true);
  const dualPointerScrollRef = useRef<{ x: number; y: number } | null>(null);
  const keyboardHintTimerRef = useRef<number | null>(null);
  const keyboardHintShownRef = useRef(false);
  const pendingPositionRef = useRef<BilingualReadingPosition | null>(null);
  const pendingGroupJumpRef = useRef(false);
  const scrollPercentRef = useRef(0);
  const visibleGroupRef = useRef(0);
  const lastScrollTopRef = useRef(0);
  const toolbarStopTimerRef = useRef<number | null>(null);
  const paragraphSwipeRef = useRef<{ x: number; y: number } | null>(null);
  const saveTimerRef = useRef<number | null>(null);
  const sectionRequestRef = useRef(0);
  const [dictPopover, setDictPopover] = useState<{
    word: string;
    context: string;
    anchor: DictionaryAnchorRect;
    selectedText: string;
    initialMode: "dictionary" | "translate";
    groupIndex: number;
    presentation: DictionaryPresentation;
  } | null>(null);
  const [dictResult, setDictResult] = useState<DictionaryResult | null>(null);
  const [dictLoading, setDictLoading] = useState(false);
  const [dictError, setDictError] = useState<string | null>(null);
  const [savingWord, setSavingWord] = useState(false);
  const dictReqIdRef = useRef(0);
  const dictAbortRef = useRef<AbortController | null>(null);
  const lastSelectionRef = useRef("");
  const miniLookupRef = useRef<{ word: string; at: number }>({ word: "", at: 0 });
  const touchLookupRef = useRef<
    { x: number; y: number; startedAt: number; moved: boolean; target: EventTarget | null } | null
  >(null);
  const suppressTouchSelectionRef = useRef(0);
  const suppressTouchLookupClickRef = useRef(0);
  const lastPronunciationAccentRef = useRef<WordPronunciationAccent>("en-US");
  const lastCompletedChapterCountRef = useRef<number | null>(null);

  const dualPaneSupported = supportsDualPaneAtContainerWidth(readerContainerWidth);
  const focusedReading = layout === "mobile";
  const readerMode: BilingualReaderMode =
    focusedReading
      ? "inline"
      : preferredReaderMode === "dual" && !dualPaneSupported
        ? "inline"
        : preferredReaderMode;

  useEffect(() => {
    return subscribePronunciationState(setAudioState);
  }, []);

  useEffect(() => {
    window.localStorage.setItem(BILINGUAL_READER_MODE_STORAGE_KEY, preferredReaderMode);
  }, [preferredReaderMode]);

  useEffect(() => {
    window.localStorage.setItem(BILINGUAL_THEME_STORAGE_KEY, theme);
  }, [theme]);

  useEffect(() => {
    window.localStorage.setItem(BILINGUAL_FONT_SIZE_STORAGE_KEY, fontSize);
  }, [fontSize]);

  useEffect(() => {
    window.localStorage.setItem(BILINGUAL_FONT_FAMILY_STORAGE_KEY, fontFamily);
  }, [fontFamily]);

  useEffect(() => {
    window.localStorage.setItem(BILINGUAL_CLICK_LOOKUP_STORAGE_KEY, String(clickLookupEnabled));
  }, [clickLookupEnabled]);

  useEffect(() => {
    const element = contentRef.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const updateWidth = (width: number) => setReaderContainerWidth(width);
    updateWidth(element.clientWidth);
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) updateWidth(entry.contentRect.width);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [loading, pairing?.aligned]);

  useEffect(() => {
    dualScrollLinkedRef.current = dualScrollLinked;
  }, [dualScrollLinked]);

  useEffect(() => {
    try {
      keyboardHintShownRef.current =
        window.sessionStorage.getItem(KEYBOARD_HINT_STORAGE_KEY) === "true";
    } catch {
      keyboardHintShownRef.current = false;
    }
    return () => {
      if (keyboardHintTimerRef.current !== null) window.clearTimeout(keyboardHintTimerRef.current);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      bilingualApi.get(pairingId),
      bilingualApi.readingPosition(pairingId),
      bilingualApi.navigation(pairingId),
      bilingualApi.bookmarks(pairingId),
    ])
      .then(([pairingData, positionData, navigationData, bookmarkData]) => {
        if (cancelled) return;
        setPairing(pairingData);
        setNavigation(navigationData.navigation);
        setBookmarks(bookmarkData.bookmarks);
        const chapters = pairingData.chapter_map || [];
        let initialChapter = 0;
        if (initialChapterId) {
          const matched = chapters.findIndex((c: ChapterMapEntry) => c.id === initialChapterId);
          if (matched >= 0) {
            initialChapter = matched;
            pendingGroupJumpRef.current = true;
            pendingPositionRef.current = {
              pairing_id: pairingId,
              chapter_id: initialChapterId,
              chapter_index: matched,
              group_index: initialGroupIndex,
              epub_cfi: "",
              section_href: "",
              scroll_percent: 0,
              text_fingerprint: "",
              updated_at: Date.now(),
            };
          }
        } else if (positionData.position) {
          initialChapter = positionData.position.chapter_index;
          pendingPositionRef.current = positionData.position;
        }
        loadChapter(initialChapter, { recordHistory: false }, pairingData.chapter_map);
        void loadAnnotations();
        void loadTaskSummaries();
      })
      .catch((err) => {
        if (!cancelled) {
          onErrorToast(err instanceof Error ? err.message : t("Failed to load pairing."));
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [initialChapterId, initialGroupIndex, pairingId]);

  const loadAnnotations = async () => {
    try {
      const data = await annotationApi.list(pairingId);
      setAnnotations(data.annotations);
    } catch {
      // Annotations are non-critical.
    }
  };

  const loadTaskSummaries = useCallback(async () => {
    try {
      const board = await translationTaskApi.list({ sourceType: "bilingual", sourceId: pairingId });
      const summaries = board.chapters || [];
      setChapterTaskSummaries(summaries);
      const completedCount = summaries.filter((item: TranslationChapterSummary) => item.completed).length;
      if (
        lastCompletedChapterCountRef.current !== null &&
        completedCount > lastCompletedChapterCountRef.current
      ) {
        const activeEntry = pairing?.chapter_map?.[chapterIndex];
        if (activeEntry) {
          bilingualApi
            .section(pairingId, activeEntry.id)
            .then((nextSection) => {
              setSection(nextSection);
            })
            .catch(() => undefined);
        }
      }
      lastCompletedChapterCountRef.current = completedCount;
    } catch {
      // Translation tasks are optional.
    }
  }, [chapterIndex, pairing?.chapter_map, pairingId]);

  const loadChapter = useCallback(
    (
      index: number,
      options: { recordHistory?: boolean } = {},
      chapterMap: ChapterMapEntry[] | undefined = pairing?.chapter_map,
    ) => {
      const entry = chapterMap?.[index];
      if (!entry) return;
      const clamped = Math.max(0, Math.min(index, (chapterMap?.length || 1) - 1));
      const requestId = ++sectionRequestRef.current;
      if (options.recordHistory !== false) {
        pendingPositionRef.current = null;
      }
      setChapterIndex(clamped);
      setSectionLoading(true);
      setChapterPreview({ chapterIndex: clamped, loading: true, error: null, data: null });
      immersiveReadingApi
        .bilingualVocabularyDifficulty(pairingId, entry.id)
        .then((data) => {
          setChapterPreview((current) =>
            current?.chapterIndex === clamped
              ? { chapterIndex: clamped, loading: false, error: null, data }
              : current,
          );
        })
        .catch(() => {
          setChapterPreview((current) =>
            current?.chapterIndex === clamped
              ? {
                  chapterIndex: clamped,
                  loading: false,
                  error: t("Difficult words are unavailable right now."),
                  data: null,
                }
              : current,
          );
        });
      bilingualApi
        .section(pairingId, entry.id)
        .then((nextSection) => {
          if (requestId === sectionRequestRef.current) {
            setSection(nextSection);
            setLoading(false);
            setSectionLoading(false);
          }
        })
        .catch(() => {
          if (requestId === sectionRequestRef.current) {
            setSection(null);
            setLoading(false);
            setSectionLoading(false);
          }
        });
    },
    [pairing, pairingId, t],
  );

  useEffect(() => {
    const handlePopState = (event: PopStateEvent) => {
      const state = event.state as { chapterIndex?: number; groupIndex?: number } | null;
      if (state && typeof state.chapterIndex === "number") {
        pendingPositionRef.current = {
          pairing_id: pairingId,
          chapter_id: pairing?.chapter_map?.[state.chapterIndex]?.id || "",
          chapter_index: state.chapterIndex,
          group_index: state.groupIndex || 0,
          epub_cfi: "",
          section_href: "",
          scroll_percent: 0,
          text_fingerprint: "",
          updated_at: Date.now(),
        };
        loadChapter(state.chapterIndex, { recordHistory: false });
      }
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, [loadChapter, pairing?.chapter_map, pairingId]);

  useEffect(() => {
    const content = readerMode === "dual" ? englishPaneRef.current : inlinePaneRef.current;
    const saved = pendingPositionRef.current;
    if (!content || sectionLoading || !section) return;
    if (!saved) {
      content.scrollTop = 0;
      if (readerMode === "dual") scrollPaneToGroup(chinesePaneRef.current, 0);
      scrollPercentRef.current = 0;
      visibleGroupRef.current = 0;
      setActiveGroup(0);
      return;
    }
    const sameChapter = saved.chapter_id === section.chapter;
    let groupIndex = sameChapter ? saved.group_index : 0;
    if (sameChapter && saved.text_fingerprint && section.groups.length > 0) {
      const target = normalizeFingerprint(saved.text_fingerprint);
      const matched = section.groups.findIndex((g) => {
        const text = normalizeFingerprint(g.en.join(" ") || g.zh.join(" "));
        return text && (text.startsWith(target) || target.startsWith(text));
      });
      if (matched >= 0) groupIndex = matched;
    }
    visibleGroupRef.current = groupIndex;
    setActiveGroup(groupIndex);
    if (pendingGroupJumpRef.current && sameChapter) {
      const groupElement = content.querySelector<HTMLElement>(
        `[data-group-index="${groupIndex}"]`,
      );
      if (groupElement) {
        content.scrollTop = Math.max(0, groupElement.offsetTop - 24);
        if (readerMode === "dual") scrollPaneToGroup(chinesePaneRef.current, groupIndex);
        const maxScroll = Math.max(1, content.scrollHeight - content.clientHeight);
        scrollPercentRef.current = Math.max(
          0,
          Math.min(100, (content.scrollTop / maxScroll) * 100),
        );
      }
      pendingPositionRef.current = null;
      pendingGroupJumpRef.current = false;
      return;
    }
    const maxScroll = Math.max(1, content.scrollHeight - content.clientHeight);
    scrollPercentRef.current = sameChapter ? saved.scroll_percent : 0;
    content.scrollTop = (maxScroll * scrollPercentRef.current) / 100;
    if (readerMode === "dual") scrollPaneToGroup(chinesePaneRef.current, groupIndex);
    pendingPositionRef.current = null;
  }, [readerMode, section, sectionLoading]);

  const currentPositionInput = useCallback((): BilingualPositionInput => {
    const group = section?.groups?.[visibleGroupRef.current];
    const preview = group?.en?.join(" ") || group?.zh?.join(" ") || "";
    return {
      chapter_index: chapterIndex,
      group_index: visibleGroupRef.current,
      epub_cfi: "",
      section_href: "",
      scroll_percent: scrollPercentRef.current,
      text_fingerprint: preview.slice(0, 120),
    };
  }, [chapterIndex, section?.groups]);

  const savePosition = useCallback(async () => {
    if (!pairing || !section) return;
    try {
      const updated = await bilingualApi.recordNavigation(pairingId, currentPositionInput());
      setNavigation(updated.navigation);
    } catch {
      // Position saving is background and silent.
    }
  }, [currentPositionInput, pairing, pairingId, section]);

  const handleNavigateHistory = async (direction: "back" | "forward") => {
    try {
      const result =
        direction === "back"
          ? await bilingualApi.navigateBack(pairingId)
          : await bilingualApi.navigateForward(pairingId);
      if (!result?.position) return;
      pendingPositionRef.current = result.position;
      setNavigation(result.navigation);
      loadChapter(result.position.chapter_index, { recordHistory: false });
    } catch {
      // Ignore history navigation errors.
    }
  };

  const alignDualPanes = useCallback(
    (groupIndex = visibleGroupRef.current, behavior: ScrollBehavior = "smooth") => {
      if (readerMode !== "dual") return;
      dualSyncGuardRef.current = performance.now() + 120;
      scrollPaneToGroup(englishPaneRef.current, groupIndex, behavior, 48);
      scrollPaneToGroup(chinesePaneRef.current, groupIndex, behavior, 48);
    },
    [readerMode],
  );

  const setDualScrollMode = useCallback(
    (linked: boolean) => {
      dualScrollLinkedRef.current = linked;
      setDualScrollLinked(linked);
      // Restoring the link is a mode change, not a reading navigation. Align
      // immediately so linked scroll handlers cannot race a smooth animation.
      if (linked) alignDualPanes(visibleGroupRef.current, "auto");
    },
    [alignDualPanes],
  );

  const breakDualScrollLinkFromGesture = useCallback(() => {
    if (!dualScrollLinkedRef.current) return;
    dualScrollLinkedRef.current = false;
    setDualScrollLinked(false);
  }, []);

  const handleDualPaneWheel = useCallback(() => {
    if (readerMode === "dual") breakDualScrollLinkFromGesture();
  }, [breakDualScrollLinkFromGesture, readerMode]);

  const handleDualPanePointerDown = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    if (event.pointerType === "mouse" && event.button !== 0) return;
    dualPointerScrollRef.current = { x: event.clientX, y: event.clientY };
  }, []);

  const handleDualPanePointerMove = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      const start = dualPointerScrollRef.current;
      if (!start || readerMode !== "dual") return;
      if (
        breaksDualScrollLink({
          dx: event.clientX - start.x,
          dy: event.clientY - start.y,
        })
      ) {
        breakDualScrollLinkFromGesture();
      }
    },
    [breakDualScrollLinkFromGesture, readerMode],
  );

  const handleDualPanePointerEnd = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      const start = dualPointerScrollRef.current;
      dualPointerScrollRef.current = null;
      if (!start || readerMode !== "dual") return;
      if (
        breaksDualScrollLink({
          dx: event.clientX - start.x,
          dy: event.clientY - start.y,
        })
      ) {
        breakDualScrollLinkFromGesture();
      }
    },
    [breakDualScrollLinkFromGesture, readerMode],
  );

  useEffect(() => {
    if (readerMode !== "dual") {
      const content = inlinePaneRef.current;
      if (!content) return;
      lastScrollTopRef.current = content.scrollTop;
      const handleScroll = () => {
        const maxScroll = Math.max(1, content.scrollHeight - content.clientHeight);
        scrollPercentRef.current = Math.max(0, Math.min(100, (content.scrollTop / maxScroll) * 100));
        const elements = Array.from(content.querySelectorAll<HTMLElement>("[data-group-index]"));
        const visible = visibleGroupFromElements(
          elements,
          content.scrollTop,
          content.clientHeight,
          visibleGroupRef.current,
        );
        visibleGroupRef.current = visible;
        setActiveGroup(visible);
        setMobileToolbarVisible((current) =>
          nextReaderToolbarVisible(current, content.scrollTop - lastScrollTopRef.current),
        );
        lastScrollTopRef.current = content.scrollTop;
        if (saveTimerRef.current !== null) window.clearTimeout(saveTimerRef.current);
        saveTimerRef.current = window.setTimeout(savePosition, 1000);
        if (toolbarStopTimerRef.current !== null) {
          window.clearTimeout(toolbarStopTimerRef.current);
        }
        toolbarStopTimerRef.current = window.setTimeout(() => {
          setMobileToolbarVisible(true);
          toolbarStopTimerRef.current = null;
        }, 500);
      };
      content.addEventListener("scroll", handleScroll, { passive: true });
      return () => {
        content.removeEventListener("scroll", handleScroll);
        if (saveTimerRef.current !== null) window.clearTimeout(saveTimerRef.current);
        if (toolbarStopTimerRef.current !== null) {
          window.clearTimeout(toolbarStopTimerRef.current);
          toolbarStopTimerRef.current = null;
        }
      };
    }

    const english = englishPaneRef.current;
    const chinese = chinesePaneRef.current;
    if (!english || !chinese) return;
    const handleDualScroll = (source: HTMLDivElement, other: HTMLDivElement) => {
      if (performance.now() < dualSyncGuardRef.current) return;
      const elements = Array.from(source.querySelectorAll<HTMLElement>("[data-group-index]"));
      const visible = visibleGroupFromElements(
        elements,
        source.scrollTop,
        source.clientHeight,
        visibleGroupRef.current,
      );
      if (dualScrollLinkedRef.current && visible !== visibleGroupRef.current) {
        visibleGroupRef.current = visible;
        setActiveGroup(visible);
        dualSyncGuardRef.current = performance.now() + 100;
        scrollPaneToGroup(other, visible, "auto", 48);
      }
      if (!dualScrollLinkedRef.current && visible !== visibleGroupRef.current) {
        visibleGroupRef.current = visible;
        setActiveGroup(visible);
      }
      if (source === english) {
        const maxScroll = Math.max(1, english.scrollHeight - english.clientHeight);
        scrollPercentRef.current = Math.max(0, Math.min(100, (english.scrollTop / maxScroll) * 100));
      }
      if (saveTimerRef.current !== null) window.clearTimeout(saveTimerRef.current);
      saveTimerRef.current = window.setTimeout(savePosition, 1000);
    };
    const onEnglishScroll = () => handleDualScroll(english, chinese);
    const onChineseScroll = () => handleDualScroll(chinese, english);
    english.addEventListener("scroll", onEnglishScroll, { passive: true });
    chinese.addEventListener("scroll", onChineseScroll, { passive: true });
    return () => {
      english.removeEventListener("scroll", onEnglishScroll);
      chinese.removeEventListener("scroll", onChineseScroll);
      if (saveTimerRef.current !== null) window.clearTimeout(saveTimerRef.current);
    };
  }, [readerMode, savePosition, section]);

  useEffect(() => {
    setManualOpenGroups(new Set());
    setManualClosedGroups(new Set());
    setHoveredGroup(null);
    setPinnedHoverGroup(null);
    dualScrollLinkedRef.current = true;
    setDualScrollLinked(true);
    if (readerMode === "dual") {
      scrollPaneToGroup(englishPaneRef.current, visibleGroupRef.current, "auto", 48);
      scrollPaneToGroup(chinesePaneRef.current, visibleGroupRef.current, "auto", 48);
    } else {
      scrollPaneToGroup(inlinePaneRef.current, visibleGroupRef.current, "auto", 48);
    }
  }, [readerMode, chapterIndex]);

  useEffect(() => {
    setManualOpenGroups(new Set());
    setManualClosedGroups(new Set());
  }, [expandAll]);

  // Cancel any pending dictionary lookup when chapter changes.
  useEffect(() => {
    closeDictionary();
  }, [chapterIndex]);

  const handleExport = async () => {
    setExporting(true);
    try {
      const response = await apiFetch(bilingualApi.exportUrl(pairingId), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          style: exportStyle,
          font_family: exportFontFamily,
          custom_css: exportCss,
          font_asset_id: exportFontAssetId,
        }),
      });
      if (!response.ok) throw new Error(t("Export failed."));
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${pairing?.en_title || "bilingual"}_${exportStyle}.epub`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      onToast(t("EPUB exported successfully."));
      setShowExportDialog(false);
    } catch (err) {
      onErrorToast(err instanceof Error ? err.message : t("Export failed."));
    } finally {
      setExporting(false);
    }
  };

  const handleFontUpload = async (file: File | null) => {
    if (!file) return;
    setUploadingFont(true);
    try {
      const uploaded = await bilingualApi.uploadFont(pairingId, file, exportFontFamily);
      setExportFontAssetId(uploaded.font_asset_id);
      setExportFontFamily(uploaded.family);
      setFontFileName(file.name);
      onToast(t("Font embedded."));
    } catch (err) {
      onErrorToast(err instanceof Error ? err.message : t("Font upload failed."));
    } finally {
      setUploadingFont(false);
    }
  };

  const handleFlag = async (groupIndex: number, issueType: IssueType, note: string) => {
    const group = section?.groups?.[groupIndex];
    if (!group || !pairing) return;
    const currentChapter = pairing.chapter_map?.[chapterIndex];
    try {
      const created = await annotationApi.add(pairingId, {
        chapter_id: currentChapter?.id || `ch_${chapterIndex}`,
        group_index: groupIndex,
        issue_type: issueType,
        note: note || undefined,
      });
      setAnnotations((prev) => [...prev, created]);
      setFlagTarget(null);
      onToast(t("Issue flagged."));
    } catch (err) {
      onErrorToast(err instanceof Error ? err.message : t("Failed to flag issue."));
    }
  };

  const handleResolveAnnotation = async (annotationId: string) => {
    try {
      await annotationApi.resolve(pairingId, annotationId);
      setAnnotations((prev) => prev.filter((a) => a.id !== annotationId));
      onToast(t("Issue resolved."));
    } catch (err) {
      onErrorToast(err instanceof Error ? err.message : t("Failed to resolve issue."));
    }
  };

  const handleTaskBoardChange = useCallback(async () => {
    await loadTaskSummaries();
    const entry = pairing?.chapter_map?.[chapterIndex];
    if (entry) {
      try {
        const nextSection = await bilingualApi.section(pairingId, entry.id);
        setSection(nextSection);
      } catch {
        // Ignore background refresh failure.
      }
    }
  }, [chapterIndex, loadTaskSummaries, pairing?.chapter_map, pairingId]);

  const handleGroupTranslated = useCallback(
    (task: TranslationTask & { translation?: string }) => {
      if (
        task.source_type !== "bilingual" ||
        task.source_id !== pairingId ||
        !task.translation ||
        section?.chapter !== task.chapter_id
      ) {
        return;
      }
      const groupIndex = Number(task.group_index);
      setSection((current) => {
        if (!current || current.chapter !== task.chapter_id) return current;
        if (groupIndex < 0 || groupIndex >= current.groups.length) return current;
        const groups = current.groups.map((group, index) =>
          index === groupIndex
            ? {
                ...group,
                zh: [task.translation ?? ""],
                translation_source: "translation_task",
                translation_task_id: task.id,
                low_confidence: false,
              }
            : group,
        );
        return { ...current, groups };
      });
    },
    [pairingId, section?.chapter],
  );

  const bookmarkedGroupSet = useMemo(() => {
    const set = new Set<number>();
    if (!section?.chapter) return set;
    for (const b of bookmarks) {
      if (b.chapter_id === section.chapter) {
        set.add(b.group_index);
      }
    }
    return set;
  }, [bookmarks, section?.chapter]);

  const isCurrentGroupBookmarked = bookmarkedGroupSet.has(activeGroup);

  const handleAddBookmark = useCallback(async () => {
    try {
      const input = currentPositionInput();
      const group = section?.groups?.[input.group_index];
      const preview = group?.en?.join(" ") || group?.zh?.join(" ") || "";
      const bookmark = await bilingualApi.addBookmark(
        pairingId,
        input,
        "",
        preview.slice(0, 160),
      );
      setBookmarks((prev) => [bookmark, ...prev]);
      onToast(t("Bookmark added at paragraph #{{group}}", { group: input.group_index + 1 }));
    } catch {
      // Keep reading if bookmark persistence fails.
    }
  }, [currentPositionInput, onToast, pairingId, section, t]);

  const handleJumpBookmark = async (bookmark: BilingualBookmark) => {
    pendingPositionRef.current = bookmark;
    try {
      await bilingualApi.recordNavigation(pairingId, {
        chapter_index: bookmark.chapter_index,
        group_index: bookmark.group_index,
        epub_cfi: bookmark.epub_cfi,
        section_href: bookmark.section_href,
        scroll_percent: bookmark.scroll_percent,
        text_fingerprint: bookmark.text_fingerprint,
      });
    } catch {
      // Non-critical.
    }
    loadChapter(bookmark.chapter_index, { recordHistory: false });
    setShowBookmarks(false);
  };

  const handleRenameBookmark = async (bookmarkId: string, title: string) => {
    try {
      const updated = await bilingualApi.renameBookmark(pairingId, bookmarkId, title);
      setBookmarks((prev) => prev.map((item) => (item.id === bookmarkId ? updated : item)));
    } catch {
      // Keep previous title.
    }
  };

  const handleDeleteBookmark = async (bookmarkId: string) => {
    try {
      await bilingualApi.deleteBookmark(pairingId, bookmarkId);
      setBookmarks((prev) => prev.filter((item) => item.id !== bookmarkId));
    } catch {
      // Keep bookmark.
    }
  };

  const handleDictionaryLookup = useCallback(
    async (rawWord: string, contextText: string) => {
      const word = extractDictionaryWord(rawWord);
      if (!word) return;
      dictAbortRef.current?.abort();
      const controller = new AbortController();
      dictAbortRef.current = controller;
      const reqId = ++dictReqIdRef.current;
      setDictLoading(true);
      setDictError(null);

      const cached = getCachedWord(word);
      if (cached) {
        setDictResult(cached);
        setDictLoading(false);
        return;
      }

      try {
        const result = await immersiveReadingApi.dictionary(word, contextText, controller.signal);
        if (dictReqIdRef.current === reqId) {
          setCachedWord(word, result);
          setDictResult(result);
          setDictLoading(false);
        }
      } catch (cause) {
        if (dictReqIdRef.current === reqId) {
          setDictResult(null);
          setDictError(
            cause instanceof ApiRequestError
              ? cause.message
              : cause instanceof Error
                ? cause.message
                : t("Dictionary lookup failed."),
          );
          setDictLoading(false);
        }
      }
    },
    [t],
  );

  const handleTranslateText = useCallback(
    async (text: string) => {
      if (!text.trim()) return;
      dictAbortRef.current?.abort();
      const controller = new AbortController();
      dictAbortRef.current = controller;
      const reqId = ++dictReqIdRef.current;
      const targetLanguage = "Chinese";
      setDictLoading(true);
      setDictError(null);

      const cached = getCachedTranslation(text, targetLanguage);
      if (cached) {
        setDictResult({
          word: text,
          phonetic: "",
          definitions: [],
          chinese: cached,
          context_note: cached,
        });
        setDictLoading(false);
        return;
      }

      let jobId: string | null = null;
      let translation = "";
      let jobError: ApiRequestError | null = null;

      try {
        const job = await immersiveReadingApi.translateJob(text, targetLanguage, []);
        jobId = job.job_id;
        await immersiveReadingApi.translateJobStream(
          jobId,
          (event) => {
            if (dictReqIdRef.current !== reqId || controller.signal.aborted) {
              return;
            }

            if (event.type === "delta" && event.delta) {
              translation += event.delta;
              setDictResult({
                word: text,
                phonetic: "",
                definitions: [],
                chinese: translation,
                context_note: translation,
              });
              return;
            }

            if (event.type === "completed") {
              translation = event.translation || translation;
              return;
            }

            if (event.type === "failed" || event.type === "cancelled") {
              jobError = new ApiRequestError(
                event.error || "Translation failed.",
                event.type === "failed" ? 500 : 499,
              );
            }
          },
          controller.signal,
        );

        if (jobError) throw jobError;

        if (dictReqIdRef.current === reqId && !controller.signal.aborted) {
          if (!translation) {
            throw new ApiRequestError("Translation produced no content.", 500);
          }
          setCachedTranslation(text, targetLanguage, translation);
          setDictResult({
            word: text,
            phonetic: "",
            definitions: [],
            chinese: translation,
            context_note: translation,
          });
        }
      } catch (cause) {
        if (dictReqIdRef.current === reqId) {
          if (controller.signal.aborted && jobId) {
            void immersiveReadingApi.translateJobCancel(jobId).catch(() => undefined);
            return;
          }

          setDictResult(null);
          const status = cause instanceof ApiRequestError ? cause.status : undefined;
          const msg = cause instanceof Error ? cause.message : String(cause);
          if (status === 504) {
            setDictError(t("Translation timed out. The model may still be loading."));
          } else if (status === 503) {
            setDictError(
              msg || t("Local translation service unavailable. Start Ollama to enable translation."),
            );
          } else if (status === 429) {
            setDictError(t("Rate limit exceeded. Please wait a moment."));
          } else if (status && status >= 500) {
            setDictError(t("Local translation service unavailable. Please try again."));
          } else {
            setDictError(t("Translation failed.") + (msg ? ` ${msg}` : ""));
          }
        }
      } finally {
        if (dictReqIdRef.current === reqId) {
          setDictLoading(false);
        }
      }
    },
    [t],
  );

  const openWordLookupAtPoint = useCallback(
    (x: number, y: number, target: EventTarget | null) => {
      if (shouldIgnoreLookupTarget(target)) return;
      const surface = contentRef.current;
      const targetNode = target instanceof Node ? target : null;
      const targetElement = target instanceof Element ? target : targetNode?.parentElement;
      const paragraph = targetElement?.closest("p");
      if (!surface || !paragraph || !surface.contains(paragraph)) return;

      const range = wordRangeAtPoint(paragraph, x, y);
      if (!range) return;
      const rawWord = range.toString();
      const word = extractDictionaryWord(rawWord);
      if (!word) return;
      const rect = range.getBoundingClientRect();
      const anchor: DictionaryAnchorRect =
        rect.width || rect.height
          ? { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom }
          : { left: x, right: x + 1, top: y, bottom: y + 1 };
      const groupIndex = groupIndexFromNode(range.startContainer, visibleGroupRef.current);
      miniLookupRef.current = { word, at: performance.now() };
      setDictPopover({
        word,
        context: (paragraph.textContent || "").slice(0, 2000),
        selectedText: word,
        initialMode: "dictionary",
        groupIndex,
        anchor,
        presentation: layout === "mobile" ? "full" : "mini",
      });
      handleDictionaryLookup(word, paragraph.textContent || "");
    },
    [handleDictionaryLookup, layout],
  );

  const handleTextSelection = useCallback(() => {
    if (layout === "mobile" && suppressTouchSelectionRef.current > Date.now()) return;
    const selection = window.getSelection();
    const text = selection?.toString().trim() || "";
    if (!text) {
      lastSelectionRef.current = "";
      return;
    }
    if (
      miniLookupRef.current.word === text &&
      performance.now() - miniLookupRef.current.at < 400
    ) {
      return;
    }
    const anchor = selection?.anchorNode;
    if (!anchor || !contentRef.current?.contains(anchor)) {
      return;
    }
    const range = selection && selection.rangeCount > 0 ? selection.getRangeAt(0) : null;
    const rect = range?.getBoundingClientRect();
    if (!rect || (rect.width === 0 && rect.height === 0)) {
      return;
    }
    const singleWord = extractDictionaryWord(text);
    const initialMode: "dictionary" | "translate" = singleWord ? "dictionary" : "translate";
    const groupElement = (anchor instanceof Element ? anchor : anchor.parentElement)?.closest(
      "[data-group-index]",
    );
    const groupIndex = Number(groupElement?.getAttribute("data-group-index") ?? visibleGroupRef.current);
    const context = (groupElement?.textContent || text).slice(0, 2000);
    lastSelectionRef.current = text;
    setDictPopover({
      word: singleWord || text,
      context,
      selectedText: text,
      initialMode,
      groupIndex,
      anchor: { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom },
      presentation: "full",
    });
    if (initialMode === "dictionary") {
      handleDictionaryLookup(singleWord, context);
    } else {
      handleTranslateText(text);
    }
  }, [handleDictionaryLookup, handleTranslateText, layout]);

  useEffect(() => {
    const content = contentRef.current;
    if (!content) return;
    let selectionTimer: number | null = null;
    const onMouseUp = () => {
      window.setTimeout(handleTextSelection, 10);
    };
    const onSelectionChange = () => {
      if (selectionTimer !== null) window.clearTimeout(selectionTimer);
      selectionTimer = window.setTimeout(handleTextSelection, 180);
    };
    const onClick = (event: MouseEvent) => {
      const now = Date.now();
      if (suppressTouchLookupClickRef.current > now) return;
      if (!clickLookupEnabled || window.getSelection()?.toString().trim()) return;
      openWordLookupAtPoint(event.clientX, event.clientY, event.target);
    };
    content.addEventListener("mouseup", onMouseUp);
    document.addEventListener("selectionchange", onSelectionChange);
    content.addEventListener("click", onClick);
    return () => {
      content.removeEventListener("mouseup", onMouseUp);
      document.removeEventListener("selectionchange", onSelectionChange);
      content.removeEventListener("click", onClick);
      if (selectionTimer !== null) window.clearTimeout(selectionTimer);
    };
  }, [clickLookupEnabled, handleTextSelection, openWordLookupAtPoint]);

  const handleDictLookupClick = () => {
    if (!dictPopover) return;
    handleDictionaryLookup(dictPopover.word, dictPopover.context);
  };

  const handleTranslateSelection = async () => {
    if (!dictPopover) return;
    handleTranslateText(dictPopover.selectedText || dictPopover.word);
  };

  const closeDictionary = () => {
    lastSelectionRef.current = "";
    dictAbortRef.current?.abort();
    dictReqIdRef.current++;
    setDictPopover(null);
    setDictResult(null);
    setDictError(null);
    setDictLoading(false);
  };

  const handlePronounce = useCallback(
    (accent: WordPronunciationAccent = "en-US", wordOverride?: string) => {
      lastPronunciationAccentRef.current = accent;
      const selectionWord = extractDictionaryWord(window.getSelection()?.toString() || "");
      const word =
        wordOverride ||
        selectionWord ||
        dictPopover?.word ||
        dictionarySeedFromGroup(section?.groups?.[activeGroup]);
      if (!word) return;
      void playWordPronunciation(word, accent, {
        onError: (err) => {
          onToast(typeof err === "string" ? err : err.message);
        },
      });
    },
    [activeGroup, dictPopover?.word, onToast, section],
  );

  const handleOpenFullDictionary = useCallback(() => {
    setDictPopover((current) =>
      current ? { ...current, presentation: "full" } : current,
    );
  }, []);

  const moveGroup = useCallback(
    (delta: number) => {
      if (!section?.groups?.length) return;
      const next = Math.max(0, Math.min(activeGroup + delta, section.groups.length - 1));
      visibleGroupRef.current = next;
      setActiveGroup(next);
      closeDictionary();
      if (readerMode === "dual") {
        scrollPaneToGroup(englishPaneRef.current, next, "smooth", 60);
        scrollPaneToGroup(chinesePaneRef.current, next, "smooth", 60);
      } else {
        scrollPaneToGroup(inlinePaneRef.current, next, "smooth", 60);
      }
    },
    [activeGroup, readerMode, section],
  );

  const handleGroupSelect = useCallback(
    (groupIndex: number) => {
      visibleGroupRef.current = groupIndex;
      setActiveGroup(groupIndex);
      if (readerMode === "dual" && !dualScrollLinkedRef.current) {
        setDualScrollMode(true);
      }
    },
    [readerMode, setDualScrollMode],
  );

  const handleContentTouchStart = useCallback((event: React.TouchEvent<HTMLDivElement>) => {
    suppressTouchSelectionRef.current = Date.now() + 600;
    touchLookupRef.current = null;
    paragraphSwipeRef.current = null;
    if (event.touches.length !== 1 || dictPopover || showMoreMenu || flagTarget !== null) return;
    if (
      showBookmarks ||
      showTaskBoard ||
      showAppearanceModal ||
      showShortcutsModal ||
      reviewOpen ||
      showReview
    ) {
      return;
    }
    const touch = event.touches[0];
    const width = contentRef.current?.clientWidth || window.innerWidth;
    touchLookupRef.current = {
      x: touch.clientX,
      y: touch.clientY,
      startedAt: Date.now(),
      moved: false,
      target: event.target,
    };
    const edgeInset = paragraphSwipeEdgeInset(width);
    if (touch.clientX <= edgeInset || touch.clientX >= width - edgeInset) return;
    paragraphSwipeRef.current = { x: touch.clientX, y: touch.clientY };
  }, []);

  const handleContentTouchMove = useCallback((event: React.TouchEvent<HTMLDivElement>) => {
    const lookup = touchLookupRef.current;
    if (!lookup || event.touches.length !== 1) return;
    const touch = event.touches[0];
    if (!touch) return;
    if (
      Math.abs(touch.clientX - lookup.x) > TOUCH_LOOKUP_MOVE_TOLERANCE_PX ||
      Math.abs(touch.clientY - lookup.y) > TOUCH_LOOKUP_MOVE_TOLERANCE_PX
    ) {
      touchLookupRef.current = { ...lookup, moved: true };
    }
  }, []);

  const handleContentTouchEnd = useCallback((event: React.TouchEvent<HTMLDivElement>) => {
    const lookup = touchLookupRef.current;
    const start = paragraphSwipeRef.current;
    paragraphSwipeRef.current = null;
    touchLookupRef.current = null;
    const end = event.changedTouches[0];
    if (!end) return;

    const now = Date.now();
    const swipeWidth = readerContainerWidth || window.innerWidth;
    if (start) {
      const direction = paragraphSwipeFromPoints(
        start,
        { x: end.clientX, y: end.clientY },
        swipeWidth,
        {
          edgeInset: paragraphSwipeEdgeInset(swipeWidth),
          minDistance: Math.max(44, Math.round(swipeWidth * 0.09)),
          maxVertical: 28,
        },
      );
      if (direction === "next") {
        moveGroup(1);
        suppressTouchLookupClickRef.current = now + TOUCH_LOOKUP_CLICK_GUARD_MS;
        return;
      }
      if (direction === "previous") {
        moveGroup(-1);
        suppressTouchLookupClickRef.current = now + TOUCH_LOOKUP_CLICK_GUARD_MS;
        return;
      }
    }

    if (!lookup) return;
    const tapDuration = now - lookup.startedAt;
    const isQuickTap = !lookup.moved && tapDuration <= TOUCH_LOOKUP_TAP_MAX_DURATION_MS;

    if (clickLookupEnabled && isQuickTap) {
      openWordLookupAtPoint(end.clientX, end.clientY, lookup.target);
      suppressTouchLookupClickRef.current = now + TOUCH_LOOKUP_CLICK_GUARD_MS;
      suppressTouchSelectionRef.current = now + 700;
      return;
    }

    if (lookup.moved || tapDuration > TOUCH_LOOKUP_TAP_MAX_DURATION_MS) {
      suppressTouchLookupClickRef.current = now + TOUCH_LOOKUP_CLICK_GUARD_MS;
      suppressTouchSelectionRef.current = now + 700;
    }
  }, [readerContainerWidth, clickLookupEnabled, moveGroup, openWordLookupAtPoint]);

  const toggleTranslation = useCallback(
    (groupIndex = activeGroup) => {
      if (readerMode === "hover") {
        setPinnedHoverGroup((current) => (current === groupIndex ? null : groupIndex));
        return;
      }
      if (readerMode === "dual") {
        onToast(t("Translations are always visible in dual-pane mode."));
        return;
      }
      const isOpen = expandAll
        ? !manualClosedGroups.has(groupIndex)
        : manualOpenGroups.has(groupIndex);
      setManualOpenGroups((current) => {
        const next = new Set(current);
        if (isOpen) next.delete(groupIndex);
        else next.add(groupIndex);
        return next;
      });
      setManualClosedGroups((current) => {
        const next = new Set(current);
        if (isOpen) next.add(groupIndex);
        else next.delete(groupIndex);
        return next;
      });
    },
    [activeGroup, expandAll, manualClosedGroups, manualOpenGroups, onToast, readerMode, t],
  );

  const lookupFromKeyboard = useCallback(() => {
    const selection = window.getSelection();
    const selectedWord = extractDictionaryWord(selection?.toString() || "");
    const word = selectedWord || dictPopover?.word || dictionarySeedFromGroup(section?.groups?.[activeGroup]);
    if (!word || !section) return;
    const surface = readerMode === "dual" ? englishPaneRef.current : contentRef.current;
    const groupElement = surface?.querySelector<HTMLElement>(`[data-group-index="${activeGroup}"]`);
    const paragraph = groupElement?.querySelector("p");
    const rect =
      selection && selection.rangeCount > 0 && selection.toString().trim()
        ? selection.getRangeAt(0).getBoundingClientRect()
        : paragraph?.getBoundingClientRect();
    if (!rect) return;
    setDictPopover({
      word,
      context: (paragraph?.textContent || section.groups[activeGroup]?.en.join(" ") || "").slice(0, 2000),
      selectedText: word,
      initialMode: "dictionary",
      groupIndex: activeGroup,
      anchor: { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom },
      presentation: "full",
    });
    handleDictionaryLookup(word, paragraph?.textContent || section.groups[activeGroup]?.en.join(" ") || "");
  }, [activeGroup, dictPopover?.word, handleDictionaryLookup, readerMode, section]);

  const showKeyboardHint = useCallback(
    (shortcut: BilingualReaderShortcut) => {
      if (keyboardHintShownRef.current) return;
      keyboardHintShownRef.current = true;
      try {
        window.sessionStorage.setItem(KEYBOARD_HINT_STORAGE_KEY, "true");
      } catch {
        // The hint remains one-time for this component instance.
      }
      const labels: Record<BilingualReaderShortcut, string> = {
        "previous-group": t("Previous paragraph"),
        "next-group": t("Next paragraph"),
        "toggle-translation": t("Toggle paragraph translation"),
        lookup: t("Dictionary lookup"),
        bookmark: t("Add bookmark"),
        pronounce: t("Play US pronunciation (P)"),
        "pronounce-uk": t("Play UK pronunciation (Shift+P)"),
        "toggle-shortcuts": t("Help & Shortcuts (?)"),
        "close-modal": t("Close"),
      };
      setKeyboardHint(labels[shortcut]);
      if (keyboardHintTimerRef.current !== null) window.clearTimeout(keyboardHintTimerRef.current);
      keyboardHintTimerRef.current = window.setTimeout(() => {
        setKeyboardHint(null);
        keyboardHintTimerRef.current = null;
      }, 2200);
    },
    [t],
  );

  useEffect(() => {
    const modalOpen =
      flagTarget !== null ||
      reviewOpen ||
      showReview ||
      showBookmarks ||
      showTaskBoard ||
      showAppearanceModal ||
      showShortcutsModal ||
      showMoreMenu;

    const onKeyDown = (event: KeyboardEvent) => {
      const shortcut = readerShortcutFromKeyboardEvent(event, { modalOpen });
      if (!shortcut) return;
      showKeyboardHint(shortcut);

      if (shortcut === "close-modal") {
        if (showShortcutsModal) setShowShortcutsModal(false);
        else if (showAppearanceModal) setShowAppearanceModal(false);
        else if (dictPopover) closeDictionary();
        return;
      }

      event.preventDefault();
      switch (shortcut) {
        case "next-group":
          moveGroup(1);
          break;
        case "previous-group":
          moveGroup(-1);
          break;
        case "toggle-translation":
          toggleTranslation();
          break;
        case "lookup":
          lookupFromKeyboard();
          break;
        case "bookmark":
          void handleAddBookmark();
          break;
        case "pronounce":
          handlePronounce("en-US");
          break;
        case "pronounce-uk":
          handlePronounce("en-GB");
          break;
        case "toggle-shortcuts":
          setShowShortcutsModal((v) => !v);
          break;
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [
    dictPopover,
    flagTarget,
    handleAddBookmark,
    handlePronounce,
    lookupFromKeyboard,
    moveGroup,
    showAppearanceModal,
    showBookmarks,
    showKeyboardHint,
    showReview,
    showShortcutsModal,
    showTaskBoard,
    showMoreMenu,
    reviewOpen,
    toggleTranslation,
  ]);

  const handleSaveVocabulary = async () => {
    if (!dictPopover || !pairing || savingWord) return;
    const chapter = pairing.chapter_map?.[chapterIndex];
    if (!chapter) return;
    setSavingWord(true);
    try {
      const word = extractDictionaryWord(dictPopover.selectedText) || dictPopover.word;
      const { lookup_warning } = await immersiveReadingApi.addWord(
        word,
        dictPopover.context,
        pairing.en_document_id,
        pairing.en_title,
        chapter.en_title || chapter.english,
        {
          pairing_id: pairingId,
          chapter_id: chapter.id,
          chapter_index: chapterIndex,
          group_index: dictPopover.groupIndex,
        },
      );
      onVocabularyAdded();
      onToast(
        lookup_warning
          ? `${t("Added to vocabulary")} (${t("Definition unavailable")})`
          : t("Added to vocabulary"),
      );
      closeDictionary();
    } catch (cause) {
      onErrorToast(
        cause instanceof ApiRequestError
          ? cause.message
          : cause instanceof Error
            ? cause.message
            : t("Failed to save word."),
      );
    } finally {
      setSavingWord(false);
    }
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
  const currentChapterCompleted = chapterTaskSummaries.find(
    (item) => item.chapter_id === currentChapter?.id,
  )?.completed;
  const flaggedGroups = new Set(
    annotations
      .filter((a) => a.chapter_id === currentChapter?.id)
      .map((a) => a.group_index),
  );
  const peekGroup = pinnedHoverGroup ?? hoveredGroup;
  const compactParagraphFocus = readerMode === "inline" && (focusedReading || !dualPaneSupported);
  const groupIsOpen = (index: number) =>
    compactParagraphFocus
      ? index === activeGroup && !manualClosedGroups.has(index)
      : manualClosedGroups.has(index)
      ? false
      : manualOpenGroups.has(index) || expandAll;
  const difficultyWords =
    chapterPreview?.chapterIndex === chapterIndex ? chapterPreview.data?.words || [] : [];
  const difficultyByWord = difficultyIndex(difficultyWords);

  const totalGroups = section?.groups?.length || 0;
  const progressPercent = totalGroups > 0 ? Math.round(((activeGroup + 1) / totalGroups) * 100) : 0;
  const isPronouncing = audioState.isPlaying;

  const renderGroups = (pane: "combined" | "english" | "chinese") => {
    if (!section) return null;
    return (
      <>
        {pane === "chinese" ? null : (
          <ChapterDifficultyPanel
            state={chapterPreview?.chapterIndex === chapterIndex ? chapterPreview : null}
          />
        )}
        {pane === "chinese" ? null : section.en_title && (
          <h2 className="mb-4 text-xl font-bold tracking-tight">{section.en_title}</h2>
        )}
        {section.groups.map((group, gi) => (
          <BilingualGroup
            key={`${pane}-${gi}`}
            group={group}
            index={gi}
            mode={readerMode}
            pane={pane}
            open={groupIsOpen(gi)}
            active={activeGroup === gi}
            focusedReading={compactParagraphFocus}
            isBookmarked={bookmarkedGroupSet.has(gi)}
            fontSize={fontSize}
            fontFamily={fontFamily}
            peekVisible={readerMode === "hover" && peekGroup === gi}
            isFlagged={flaggedGroups.has(gi)}
            difficultyByWord={difficultyByWord}
            onSelect={() => handleGroupSelect(gi)}
            onToggle={() => toggleTranslation(gi)}
            onSideTap={() => toggleTranslation(gi)}
            onFlag={() => setFlagTarget(gi)}
            onPointerEnter={() => setHoveredGroup(gi)}
            onPointerLeave={() => setHoveredGroup((current) => (current === gi ? null : current))}
            onPeekToggle={() => setPinnedHoverGroup((current) => (current === gi ? null : gi))}
          />
        ))}
        {section.groups.length === 0 && (
          <p className="py-8 text-center text-[var(--muted-foreground)]">
            {t("No aligned content in this chapter.")}
          </p>
        )}
      </>
    );
  };

  return (
    <div
      className="flex h-full flex-col transition-colors duration-200"
      style={THEME_STYLES[theme]}
    >
      {/* Top Reading Progress Bar */}
      <div className="h-1 w-full bg-[var(--border)]/40 overflow-hidden">
        <div
          className="h-full bg-[var(--primary)] transition-all duration-300"
          style={{ width: `${progressPercent}%` }}
        />
      </div>

      {/* Main Top Header */}
      <div className="flex min-w-0 items-center gap-2 overflow-x-auto border-b border-[var(--border)] px-4 py-2 bg-[var(--background)]/90 backdrop-blur">
        <button
          onClick={onBack}
          aria-label={t("Back")}
          className="flex h-9 w-9 items-center justify-center rounded-lg text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
        >
          <ChevronLeft size={18} />
        </button>
        <div className="flex min-w-0 flex-1 flex-col">
          <span className="truncate text-sm font-medium">{pairing.en_title}</span>
          <span className="truncate text-xs text-[var(--muted-foreground)]">
            {currentChapter?.en_title || currentChapter?.id} · {chapterIndex + 1}/{chapters.length}
            {totalGroups > 0 ? ` · ${t("Paragraph")} ${activeGroup + 1}/${totalGroups} (${progressPercent}%)` : ""}
            {currentChapterCompleted ? ` · ${t("Chapter translated")}` : ""}
            {annotations.length > 0 && ` · ${annotations.length} ${t("flagged")}`}
          </span>
        </div>
        <button
          onClick={() => void handleNavigateHistory("back")}
          disabled={!navigation?.can_back}
          className="hidden rounded-md p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)] disabled:opacity-30 md:block"
          title={t("Back")}
        >
          <ArrowLeft size={16} />
        </button>
        <button
          onClick={() => void handleNavigateHistory("forward")}
          disabled={!navigation?.can_forward}
          className="hidden rounded-md p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)] disabled:opacity-30 md:block"
          title={t("Forward")}
        >
          <ArrowRight size={16} />
        </button>
        <button
          onClick={() => void handleAddBookmark()}
          className="hidden rounded-md p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)] md:block"
          title={t("Add bookmark") + " (B)"}
        >
          <BookmarkPlus size={16} />
        </button>
        <button
          onClick={() => setShowBookmarks((value) => !value)}
          className={`hidden rounded-md p-1.5 hover:bg-[var(--muted)] md:block ${
            showBookmarks
              ? "text-[var(--primary)]"
              : "text-[var(--muted-foreground)]"
          }`}
          title={t("Bookmarks")}
        >
          <Bookmark size={16} />
        </button>
        <button
          onClick={() => setShowTaskBoard((value) => !value)}
          className="hidden rounded-md p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)] md:block"
          title={t("Translate this chapter")}
        >
          <ListChecks size={16} />
        </button>
        <button
          type="button"
          onClick={() => setReviewOpen(true)}
          className="hidden rounded-md p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)] md:block"
          title={t("Today: review 10 words")}
          aria-label={t("Today: review 10 words")}
        >
          <Brain size={16} />
        </button>
        {readerMode === "inline" && !focusedReading && (
          <button
            onClick={() => setExpandAll((v) => !v)}
            className="flex items-center gap-1 rounded-lg px-2 py-1.5 text-xs text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
            title={expandAll ? t("Collapse all") : t("Expand all")}
          >
            {expandAll ? <ChevronsDownUp size={15} /> : <ChevronsUpDown size={15} />}
          </button>
        )}
        {annotations.length > 0 && !focusedReading && (
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
          type="button"
          onClick={() => setShowExportDialog(true)}
          className="hidden items-center gap-1 rounded-lg bg-[var(--primary)] px-3 py-1.5 text-xs font-medium text-[var(--primary-foreground)] hover:opacity-90 disabled:opacity-50 md:flex"
        >
          <Download size={14} />
          {t("Export EPUB")}
        </button>
      </div>

      {/* Chapter navigation and modes bar */}
      <div className="hidden items-center gap-2 border-b border-[var(--border)] px-4 py-1.5 bg-[var(--background)]/80 md:flex">
        <div
          data-reader-control
          className="flex shrink-0 items-center gap-1 rounded-lg bg-[var(--muted)] p-0.5"
          role="group"
          aria-label={t("Reader mode")}
        >
          {([
            { value: "inline", icon: ChevronsUpDown, label: t("Inline") },
            { value: "dual", icon: Columns2, label: t("Dual pane") },
            { value: "hover", icon: Eye, label: t("Hover peek") },
          ] as const).map(({ value, icon: Icon, label }) => (
            <button
              key={value}
              type="button"
              onClick={() => setPreferredReaderMode(value)}
              disabled={value === "dual" && !dualPaneSupported}
              aria-pressed={readerMode === value}
              title={label}
              className="flex h-8 min-w-8 items-center justify-center rounded-md px-2 text-xs transition disabled:opacity-40"
              style={{
                background: readerMode === value ? "var(--card)" : "transparent",
                color: readerMode === value ? "var(--foreground)" : "var(--muted-foreground)",
                boxShadow: readerMode === value ? "0 1px 2px rgb(0 0 0 / 0.08)" : undefined,
                fontWeight: readerMode === value ? 600 : 400,
              }}
            >
              <Icon size={14} />
              <span className="ml-1 hidden lg:inline">{label}</span>
            </button>
          ))}
        </div>
        {readerMode === "dual" && (
          <button
            type="button"
            data-reader-control
            onClick={() => setDualScrollMode(!dualScrollLinked)}
            aria-pressed={dualScrollLinked}
            aria-label={t(dualScrollLinked ? "Linked scrolling" : "Independent scrolling")}
            title={`${t(dualScrollLinked ? "Linked scrolling" : "Independent scrolling")} · ${BILINGUAL_DUAL_PANE_MIN_CONTAINER_WIDTH_PX}px+`}
            className={`flex h-8 shrink-0 items-center gap-1 rounded-lg border px-2 text-xs transition ${
              dualScrollLinked
                ? "border-[var(--primary)]/50 bg-[var(--primary)]/10 text-[var(--primary)]"
                : "border-[var(--border)] text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
            }`}
          >
            {dualScrollLinked ? <Link2 size={14} /> : <Unlink2 size={14} />}
            <span className="hidden xl:inline">
              {t(dualScrollLinked ? "Linked scrolling" : "Independent scrolling")}
            </span>
          </button>
        )}
        <button
          type="button"
          data-reader-control
          onClick={() => setClickLookupEnabled((value) => !value)}
          aria-pressed={clickLookupEnabled}
          title={t("Tap-to-lookup mode")}
          className={`flex h-8 shrink-0 items-center gap-1 rounded-lg border px-2 text-xs transition ${
            clickLookupEnabled
              ? "border-[var(--primary)]/50 bg-[var(--primary)]/10 text-[var(--primary)]"
              : "border-[var(--border)] text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
          }`}
        >
          <MousePointerClick size={14} />
          <span className="hidden md:inline">{t("Tap words")}</span>
        </button>

        <button
          type="button"
          data-reader-control
          onClick={() => setShowShortcutsModal(true)}
          title={t("Shortcuts: J/K paragraphs, T translation, D dictionary, B bookmark, P pronunciation")}
          className="hidden h-8 shrink-0 items-center gap-1 rounded-lg border border-[var(--border)] px-2 text-xs text-[var(--muted-foreground)] hover:bg-[var(--muted)] sm:flex"
        >
          <Keyboard size={14} />
          <span>{t("J/K")}</span>
        </button>

        <button
          type="button"
          data-reader-control
          onClick={() => setShowAppearanceModal(true)}
          title={t("Appearance & Typography")}
          className="flex h-8 shrink-0 items-center gap-1 rounded-lg border border-[var(--border)] px-2 text-xs text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
        >
          <Type size={14} />
          <span className="hidden sm:inline">{t("Appearance")}</span>
        </button>

        <button
          onClick={() => loadChapter(chapterIndex - 1)}
          disabled={chapterIndex === 0}
          aria-label={t("Previous section")}
          className="rounded-md p-1 text-[var(--muted-foreground)] hover:bg-[var(--muted)] disabled:opacity-30"
        >
          <ChevronLeft size={18} />
        </button>
        <select
          value={chapterIndex}
          onChange={(e) => loadChapter(Number(e.target.value))}
          className="min-w-0 flex-1 rounded-md border border-[var(--border)] bg-[var(--background)] px-2 py-1 text-sm text-[var(--foreground)]"
        >
          {chapters.map((ch, i) => (
            <option key={ch.id} value={i}>
              {chapterTaskSummaries.find((item: TranslationChapterSummary) => item.chapter_id === ch.id)?.completed ? "✓ " : ""}
              {ch.en_title || ch.id}
            </option>
          ))}
        </select>
        <button
          onClick={() => loadChapter(chapterIndex + 1)}
          disabled={chapterIndex >= chapters.length - 1}
          aria-label={t("Next section")}
          className="rounded-md p-1 text-[var(--muted-foreground)] hover:bg-[var(--muted)] disabled:opacity-30"
        >
          <ChevronRight size={18} />
        </button>
      </div>

      {/* Content surface */}
      <div
        ref={contentRef}
        data-reader-surface="true"
        className="relative min-h-0 flex-1 pb-28 md:pb-20"
        onMouseLeave={() => setHoveredGroup(null)}
        onTouchStart={handleContentTouchStart}
        onTouchMove={handleContentTouchMove}
        onTouchEnd={handleContentTouchEnd}
      >
        {sectionLoading ? (
          <div className="flex h-full justify-center py-12">
            <Loader2 className="size-6 animate-spin text-[var(--muted-foreground)]" />
          </div>
        ) : section ? (
          readerMode === "dual" ? (
            <div className="grid h-full grid-cols-2 divide-x divide-[var(--border)] overflow-hidden">
              <div
                ref={englishPaneRef}
                aria-label={t("English pane")}
                className="relative h-full overflow-y-auto px-6 py-6"
                onWheel={handleDualPaneWheel}
                onPointerDown={handleDualPanePointerDown}
                onPointerMove={handleDualPanePointerMove}
                onPointerUp={handleDualPanePointerEnd}
                onPointerCancel={handleDualPanePointerEnd}
              >
                <div className="mx-auto max-w-2xl space-y-4">{renderGroups("english")}</div>
              </div>
              <div
                ref={chinesePaneRef}
                aria-label={t("Chinese pane")}
                className="relative h-full overflow-y-auto bg-[var(--muted)]/20 px-6 py-6"
                onWheel={handleDualPaneWheel}
                onPointerDown={handleDualPanePointerDown}
                onPointerMove={handleDualPanePointerMove}
                onPointerUp={handleDualPanePointerEnd}
                onPointerCancel={handleDualPanePointerEnd}
              >
                <div className="mx-auto max-w-2xl space-y-4">{renderGroups("chinese")}</div>
              </div>
            </div>
          ) : (
            <div ref={inlinePaneRef} className="h-full overflow-y-auto px-4 py-6">
              <div className="mx-auto max-w-2xl space-y-2">{renderGroups("combined")}</div>
            </div>
          )
        ) : (
          <div ref={inlinePaneRef} className="h-full overflow-y-auto px-4 py-6">
            <p className="py-8 text-center text-[var(--muted-foreground)]">
              {t("Failed to load this chapter.")}
            </p>
          </div>
        )}

        {/* Dictionary popovers */}
        {dictPopover?.presentation === "mini" && (
          <MiniDictionaryTooltip
            word={dictPopover.word}
            anchor={dictPopover.anchor}
            loading={dictLoading}
            result={dictResult}
            error={dictError}
            onOpenFull={handleOpenFullDictionary}
            onPronounce={handlePronounce}
            onClose={closeDictionary}
          />
        )}
        {dictPopover?.presentation === "full" && (
          <DictionaryPanel
            word={dictPopover.word}
            anchor={dictPopover.anchor}
            loading={dictLoading}
            result={dictResult}
            error={dictError}
            initialMode={dictPopover.initialMode}
            onLookup={handleDictLookupClick}
            onTranslate={handleTranslateSelection}
            onClose={closeDictionary}
            saveBusy={savingWord}
            onSaveToVocabulary={() => void handleSaveVocabulary()}
            onPronounce={handlePronounce}
          />
        )}
      </div>

      {keyboardHint && (
        <div
          role="status"
          aria-live="polite"
          className="pointer-events-none fixed left-1/2 z-50 -translate-x-1/2 rounded-full border border-[var(--border)] bg-[var(--background)]/95 px-4 py-2 text-xs font-medium text-[var(--foreground)] shadow-xl backdrop-blur"
          style={{ bottom: "calc(max(12px, env(safe-area-inset-bottom, 12px)) + 64px)" }}
        >
          {keyboardHint}
        </div>
      )}

      {layout === "mobile" && showMoreMenu && (
        <button
          type="button"
          aria-label={t("Close")}
          className="fixed inset-0 z-30 bg-black/20 backdrop-blur-[1px]"
          onClick={() => setShowMoreMenu(false)}
        />
      )}

      {/* One-hand mobile toolbar; low-frequency actions stay in More. */}
      {layout === "mobile" && (
        <div
          className="fixed z-40 select-none transition-transform duration-200 ease-out"
          style={{
            left: "max(12px, env(safe-area-inset-left, 12px))",
            right: "max(12px, env(safe-area-inset-right, 12px))",
            bottom: "max(10px, env(safe-area-inset-bottom, 10px))",
            transform: mobileToolbarVisible || showMoreMenu ? "translateY(0)" : "translateY(calc(100% + 18px))",
            touchAction: "manipulation",
          }}
          data-reader-control
        >
          {showMoreMenu && (
            <div className="absolute bottom-full right-0 mb-2 w-44 overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--background)] shadow-2xl">
              {[
                { icon: Bookmark, label: t("Bookmarks"), onClick: () => setShowBookmarks(true) },
                { icon: Type, label: t("Appearance & Typography"), onClick: () => setShowAppearanceModal(true) },
                { icon: ListChecks, label: t("Translate this chapter"), onClick: () => setShowTaskBoard(true) },
                { icon: Brain, label: t("Today: review 10 words"), onClick: () => setReviewOpen(true) },
                { icon: Download, label: t("Export EPUB"), onClick: () => setShowExportDialog(true) },
                {
                  icon: MousePointerClick,
                  label: t("Tap words"),
                  active: clickLookupEnabled,
                  onClick: () => setClickLookupEnabled((value) => !value),
                },
              ].map(({ icon: Icon, label, onClick, active = false }) => (
                <button
                  key={label}
                  type="button"
                  aria-pressed={active}
                  className="flex min-h-11 w-full items-center gap-2 px-3 py-2 text-left text-xs text-[var(--foreground)] transition hover:bg-[var(--muted)] active:bg-[var(--muted)]"
                  onClick={() => {
                    onClick();
                    setShowMoreMenu(false);
                  }}
                >
                  <Icon size={14} className="text-[var(--muted-foreground)]" />
                  {label}
                </button>
              ))}
            </div>
          )}
          <div
            role="toolbar"
            aria-label={t("Reading toolbar")}
            className="grid grid-cols-5 gap-1 rounded-xl border border-[var(--border)] bg-[var(--background)]/94 p-1.5 shadow-2xl backdrop-blur-lg"
          >
            {[
              { icon: Languages, label: t("Translation"), active: groupIsOpen(activeGroup), onClick: () => toggleTranslation() },
              { icon: BookOpen, label: t("Dictionary lookup"), active: !!dictPopover, onClick: lookupFromKeyboard },
              { icon: isPronouncing ? AudioLines : Volume2, label: t("Pronounce"), active: isPronouncing, onClick: () => handlePronounce("en-US") },
              { icon: Bookmark, label: t("Add bookmark"), active: isCurrentGroupBookmarked, onClick: () => void handleAddBookmark() },
              { icon: MoreHorizontal, label: t("More"), active: showMoreMenu, onClick: () => setShowMoreMenu((value) => !value) },
            ].map(({ icon: Icon, label, active, onClick }) => (
              <button
                key={label}
                type="button"
                onClick={onClick}
                aria-pressed={active}
                className={`flex h-14 min-w-0 flex-col items-center justify-center gap-1 rounded-lg text-[11px] font-medium transition ${
                  active
                    ? "bg-[var(--primary)]/15 text-[var(--primary)]"
                    : "text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)] active:bg-[var(--muted)]"
                }`}
              >
                <Icon size={17} className="shrink-0" />
                <span className="max-w-full truncate">{label}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Floating desktop action bar for keyboard readers */}
      {layout !== "mobile" && (
      <div
        className="fixed bottom-3 left-1/2 z-40 -translate-x-1/2 select-none"
        style={{
          bottom: "max(12px, env(safe-area-inset-bottom, 12px))",
          touchAction: "manipulation",
        }}
        data-reader-control
      >
        <div className="flex items-center gap-1 rounded-full border border-[var(--border)] bg-[var(--background)]/92 px-3 py-1.5 shadow-2xl backdrop-blur-lg">
          {/* Previous paragraph (K) */}
          <button
            type="button"
            onClick={() => moveGroup(-1)}
            disabled={activeGroup <= 0}
            title={t("Previous paragraph") + " (K / ↑)"}
            aria-label={t("Previous paragraph")}
            className="flex h-9 w-9 items-center justify-center rounded-full text-[var(--muted-foreground)] transition hover:bg-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-30"
          >
            <ChevronUp size={18} />
          </button>
          {/* Next paragraph (J) */}
          <button
            type="button"
            onClick={() => moveGroup(1)}
            disabled={!section?.groups?.length || activeGroup >= section.groups.length - 1}
            title={t("Next paragraph") + " (J / ↓)"}
            aria-label={t("Next paragraph")}
            className="flex h-9 w-9 items-center justify-center rounded-full text-[var(--muted-foreground)] transition hover:bg-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-30"
          >
            <ChevronDown size={18} />
          </button>

          <div className="mx-0.5 h-4 w-[1px] bg-[var(--border)]" />

          {/* Toggle translation (T) */}
          <button
            type="button"
            onClick={() => toggleTranslation()}
            title={t("Toggle paragraph translation") + " (T)"}
            aria-label={t("Toggle paragraph translation")}
            className={`flex h-9 w-9 items-center justify-center rounded-full transition ${
              groupIsOpen(activeGroup)
                ? "bg-[var(--primary)]/15 text-[var(--primary)]"
                : "text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            }`}
          >
            <Languages size={17} />
          </button>

          {/* Dictionary lookup (D) */}
          <button
            type="button"
            onClick={lookupFromKeyboard}
            title={t("Dictionary lookup") + " (D)"}
            aria-label={t("Dictionary lookup")}
            className="flex h-9 w-9 items-center justify-center rounded-full text-[var(--muted-foreground)] transition hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
          >
            <BookOpen size={17} />
          </button>

          {/* Bookmark (B) */}
          <button
            type="button"
            onClick={() => void handleAddBookmark()}
            title={t("Add bookmark") + " (B)"}
            aria-label={t("Add bookmark")}
            className={`flex h-9 w-9 items-center justify-center rounded-full transition ${
              isCurrentGroupBookmarked
                ? "text-[var(--primary)]"
                : "text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            }`}
          >
            <Bookmark size={17} className={isCurrentGroupBookmarked ? "fill-[var(--primary)]" : ""} />
          </button>

          {/* Pronounce (P) */}
          <button
            type="button"
            onClick={() => handlePronounce("en-US")}
            title={t("Play US pronunciation (P)")}
            aria-label={t("Play US pronunciation (P)")}
            className={`flex h-9 w-9 items-center justify-center rounded-full transition ${
              isPronouncing
                ? "bg-[var(--primary)]/20 text-[var(--primary)] animate-pulse"
                : "text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            }`}
          >
            {isPronouncing ? <AudioLines size={17} /> : <Volume2 size={17} />}
          </button>

          <div className="mx-0.5 h-4 w-[1px] bg-[var(--border)]" />

          {/* Appearance (Aa) */}
          <button
            type="button"
            onClick={() => setShowAppearanceModal(true)}
            title={t("Appearance & Typography")}
            aria-label={t("Appearance & Typography")}
            className={`flex h-9 w-9 items-center justify-center rounded-full transition ${
              showAppearanceModal
                ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
                : "text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            }`}
          >
            <Type size={16} />
          </button>

          {/* Shortcuts (?) */}
          <button
            type="button"
            onClick={() => setShowShortcutsModal(true)}
            title={t("Help & Shortcuts (?)")}
            aria-label={t("Help & Shortcuts (?)")}
            className={`hidden sm:flex h-9 w-9 items-center justify-center rounded-full transition ${
              showShortcutsModal
                ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
                : "text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            }`}
          >
            <Keyboard size={16} />
          </button>

          {/* Counter badge */}
          {totalGroups > 0 && (
            <span className="ml-1 select-none pr-1.5 font-mono text-[11px] text-[var(--muted-foreground)]">
              #{activeGroup + 1}/{totalGroups}
            </span>
          )}
        </div>
      </div>
      )}

      {/* Appearance Modal */}
      {showAppearanceModal && (
        <div
          className="fixed inset-0 z-[130] flex items-end justify-center sm:items-center bg-black/40 p-4 backdrop-blur-xs"
          onClick={() => setShowAppearanceModal(false)}
        >
          <div
            className="w-full max-w-sm rounded-2xl border border-[var(--border)] bg-[var(--background)] p-5 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-4 flex items-center justify-between">
              <h3 className="flex items-center gap-2 text-sm font-semibold">
                <Type size={16} className="text-[var(--primary)]" />
                {t("Appearance & Typography")}
              </h3>
              <button
                type="button"
                onClick={() => setShowAppearanceModal(false)}
                className="rounded p-1 text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
              >
                <X size={16} />
              </button>
            </div>

            <div className="space-y-4 text-sm">
              {/* Themes */}
              <div>
                <label className="text-xs font-medium text-[var(--muted-foreground)]">{t("Reading Theme")}</label>
                <div className="mt-2 grid grid-cols-4 gap-2">
                  {[
                    { key: "system", label: t("System"), bg: "bg-gradient-to-tr from-zinc-800 to-zinc-200" },
                    { key: "sepia", label: t("Sepia (Warm)"), bg: "bg-[#f8f1e3] text-[#2d241e] border-[#dfd3be]" },
                    { key: "dark", label: t("Zinc Dark"), bg: "bg-[#18181b] text-white border-[#3f3f46]" },
                    { key: "oled", label: t("OLED Black"), bg: "bg-black text-white border-zinc-800" },
                  ].map((th) => (
                    <button
                      key={th.key}
                      type="button"
                      onClick={() => setTheme(th.key as BilingualTheme)}
                      className={`flex flex-col items-center gap-1.5 rounded-xl border p-2 text-xs transition ${
                        theme === th.key
                          ? "border-[var(--primary)] ring-2 ring-[var(--primary)]/30 font-medium"
                          : "border-[var(--border)] hover:bg-[var(--muted)]"
                      }`}
                    >
                      <div className={`h-6 w-full rounded-md border shadow-sm ${th.bg}`} />
                      <span className="text-[11px] truncate w-full text-center">{th.label}</span>
                    </button>
                  ))}
                </div>
              </div>

              {/* Font size */}
              <div>
                <label className="text-xs font-medium text-[var(--muted-foreground)]">{t("Font Size")}</label>
                <div className="mt-2 flex items-center justify-between gap-1 rounded-xl bg-[var(--muted)]/50 p-1">
                  {(["sm", "base", "lg", "xl", "2xl"] as const).map((sz, idx) => (
                    <button
                      key={sz}
                      type="button"
                      onClick={() => setFontSize(sz)}
                      className={`flex-1 rounded-lg py-1.5 text-xs transition ${
                        fontSize === sz
                          ? "bg-[var(--background)] font-semibold text-[var(--foreground)] shadow-sm"
                          : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                      }`}
                    >
                      {idx === 0 ? "A-" : idx === 4 ? "A++" : `A${"+".repeat(idx - 1)}`}
                    </button>
                  ))}
                </div>
              </div>

              {/* Font family */}
              <div>
                <label className="text-xs font-medium text-[var(--muted-foreground)]">{t("Font Family")}</label>
                <div className="mt-2 flex gap-2">
                  {[
                    { key: "sans", label: t("Modern Sans"), fontClass: "font-sans" },
                    { key: "serif", label: t("Literary Serif"), fontClass: "font-serif" },
                  ].map((f) => (
                    <button
                      key={f.key}
                      type="button"
                      onClick={() => setFontFamily(f.key as BilingualFontFamily)}
                      className={`flex-1 rounded-xl border py-2 text-xs transition ${f.fontClass} ${
                        fontFamily === f.key
                          ? "border-[var(--primary)] bg-[var(--primary)]/10 font-medium text-[var(--primary)]"
                          : "border-[var(--border)] hover:bg-[var(--muted)]"
                      }`}
                    >
                      {f.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Shortcuts Cheatsheet Modal */}
      {showShortcutsModal && (
        <div
          className="fixed inset-0 z-[130] flex items-center justify-center bg-black/40 p-4 backdrop-blur-xs"
          onClick={() => setShowShortcutsModal(false)}
        >
          <div
            className="w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--background)] p-6 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-4 flex items-center justify-between border-b border-[var(--border)] pb-3">
              <h3 className="flex items-center gap-2 text-base font-semibold">
                <Keyboard size={18} className="text-[var(--primary)]" />
                {t("Keyboard Shortcuts")}
              </h3>
              <button
                type="button"
                onClick={() => setShowShortcutsModal(false)}
                aria-label={t("Close shortcuts")}
                className="rounded p-1 text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
              >
                <X size={16} />
              </button>
            </div>

            <div className="space-y-3">
              <p className="text-xs text-[var(--muted-foreground)]">
                {t("Continuous Reading Flow")}
              </p>
              <div className="grid gap-2">
                {[
                  { key: "J / ↓", desc: t("Next paragraph") },
                  { key: "K / ↑", desc: t("Previous paragraph") },
                  { key: "T", desc: t("Toggle paragraph translation") },
                  { key: "D", desc: t("Dictionary lookup") },
                  { key: "B", desc: t("Add bookmark") },
                  { key: "P", desc: t("Play US pronunciation (P)") },
                  { key: "Shift + P", desc: t("Play UK pronunciation (Shift+P)") },
                  { key: "? / H", desc: t("Help & Shortcuts (?)") },
                  { key: "Esc", desc: t("Close") },
                ].map((item) => (
                  <div
                    key={item.key}
                    className="flex items-center justify-between rounded-lg bg-[var(--muted)]/40 px-3 py-2 text-xs"
                  >
                    <span className="text-[var(--foreground)]">{item.desc}</span>
                    <kbd className="rounded border border-[var(--border)] bg-[var(--card)] px-2 py-0.5 font-mono font-semibold text-[var(--foreground)] shadow-xs">
                      {item.key}
                    </kbd>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

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

      {/* Bookmarks drawer */}
      {showBookmarks && (
        <BookmarkPanel
          bookmarks={bookmarks}
          onClose={() => setShowBookmarks(false)}
          onJump={handleJumpBookmark}
          onRename={handleRenameBookmark}
          onDelete={handleDeleteBookmark}
        />
      )}

      {/* EPUB export modal */}
      {showExportDialog && (
        <div className="fixed inset-0 z-[125] flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-lg rounded-xl border border-[var(--border)] bg-[var(--background)] p-5 shadow-2xl">
            <div className="mb-4 flex items-center justify-between border-b border-[var(--border)] pb-3">
              <h3 className="text-base font-semibold">{t("Export bilingual EPUB")}</h3>
              <button
                type="button"
                onClick={() => setShowExportDialog(false)}
                aria-label={t("Close")}
                className="rounded p-1 text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
              >
                <X size={16} />
              </button>
            </div>
            <div className="space-y-4">
              <div className="grid gap-2 sm:grid-cols-3">
                {(
                  [
                    { value: "folded", icon: ChevronsUpDown, label: t("Folded") },
                    { value: "alternating", icon: FileText, label: t("Alternating") },
                    { value: "two_column", icon: Columns2, label: t("Two columns") },
                  ] as Array<{ value: BilingualExportStyle; icon: typeof FileText; label: string }>
                ).map(({ value, icon: Icon, label }) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => setExportStyle(value)}
                    aria-pressed={exportStyle === value}
                    className={`flex h-20 flex-col items-center justify-center gap-2 rounded-lg border text-xs transition ${
                      exportStyle === value
                        ? "border-[var(--primary)] bg-[var(--primary)]/10 font-semibold text-[var(--primary)]"
                        : "border-[var(--border)] text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
                    }`}
                  >
                    <Icon size={18} />
                    {label}
                  </button>
                ))}
              </div>
              <label className="block space-y-1.5 text-xs font-medium">
                {t("Font family")}
                <input
                  value={exportFontFamily}
                  onChange={(event) => setExportFontFamily(event.target.value)}
                  maxLength={300}
                  className="h-9 w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 text-sm font-normal text-[var(--foreground)]"
                />
              </label>
              <div className="space-y-1.5 text-xs font-medium">
                {t("Embedded font")}
                <div className="flex items-center gap-2">
                  <input
                    type="file"
                    accept=".woff2,.woff,.otf,.ttf"
                    onChange={(event) => void handleFontUpload(event.target.files?.[0] ?? null)}
                    className="h-9 min-w-0 flex-1 rounded-lg border border-[var(--border)] bg-[var(--background)] px-2 text-xs font-normal file:mr-2 file:rounded file:border-0 file:bg-[var(--muted)] file:px-2 file:py-1"
                  />
                  {uploadingFont && <Loader2 size={14} className="animate-spin" />}
                </div>
                {fontFileName && (
                  <div className="text-[11px] text-[var(--muted-foreground)]">{fontFileName}</div>
                )}
              </div>
              <label className="block space-y-1.5 text-xs font-medium">
                {t("Custom CSS")}
                <textarea
                  value={exportCss}
                  onChange={(event) => setExportCss(event.target.value)}
                  rows={5}
                  spellCheck={false}
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] p-3 font-mono text-xs font-normal text-[var(--foreground)]"
                />
              </label>
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setShowExportDialog(false)}
                  className="rounded-lg border border-[var(--border)] px-3 py-2 text-xs"
                >
                  {t("Cancel")}
                </button>
                <button
                  type="button"
                  onClick={() => void handleExport()}
                  disabled={exporting}
                  className="flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3 py-2 text-xs font-medium text-[var(--primary-foreground)] disabled:opacity-50"
                >
                  {exporting ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
                  {t("Export")}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Task board modal */}
      {showTaskBoard && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40 p-4"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setShowTaskBoard(false);
          }}
        >
          <div className="flex h-[80vh] w-full max-w-3xl flex-col overflow-hidden rounded-xl bg-[var(--background)] shadow-2xl">
            <TranslationTaskBoardPanel
              sourceType="bilingual"
              sourceId={pairingId}
              chapterId={currentChapter?.id}
              onClose={() => setShowTaskBoard(false)}
              onBoardLoaded={handleTaskBoardChange}
              onGroupTranslated={handleGroupTranslated}
            />
          </div>
        </div>
      )}

      {/* Vocabulary review drawer */}
      {reviewOpen && (
        <VocabularyReviewDrawer
          onClose={() => setReviewOpen(false)}
          onReviewed={() => onVocabularyAdded()}
        />
      )}
    </div>
  );
}

function BookmarkPanel({
  bookmarks,
  onClose,
  onJump,
  onRename,
  onDelete,
}: {
  bookmarks: BilingualBookmark[];
  onClose: () => void;
  onJump: (bookmark: BilingualBookmark) => void;
  onRename: (id: string, title: string) => void;
  onDelete: (id: string) => void;
}) {
  const { t } = useTranslation();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draftTitle, setDraftTitle] = useState("");

  const commitRename = (bookmarkId: string) => {
    if (editingId !== bookmarkId) return;
    const title = draftTitle.trim();
    setEditingId(null);
    if (title) onRename(bookmarkId, title);
  };

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40" onClick={onClose}>
      <div
        className="flex max-h-[80vh] w-[560px] flex-col rounded-xl bg-[var(--background)] shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-[var(--border)] px-5 py-3">
          <h3 className="flex items-center gap-2 text-sm font-semibold">
            <Bookmark size={16} className="text-[var(--primary)]" />
            {t("Bookmarks")} ({bookmarks.length})
          </h3>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("Close")}
            className="rounded p-1 text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
          >
            <X size={16} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-4">
          {bookmarks.length === 0 ? (
            <p className="text-center text-sm text-[var(--muted-foreground)]">{t("No bookmarks yet.")}</p>
          ) : (
            <div className="space-y-2">
              {bookmarks.map((bookmark) => (
                <div key={bookmark.id} className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-3">
                  {editingId === bookmark.id ? (
                    <div className="flex items-center gap-2">
                      <input
                        value={draftTitle}
                        onChange={(event) => setDraftTitle(event.target.value)}
                        onBlur={() => commitRename(bookmark.id)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter") commitRename(bookmark.id);
                          if (event.key === "Escape") setEditingId(null);
                        }}
                        autoFocus
                        className="w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-2 py-1 text-sm font-medium"
                      />
                    </div>
                  ) : (
                    <div className="flex items-start justify-between gap-3">
                      <button
                        type="button"
                        onClick={() => onJump(bookmark)}
                        className="min-w-0 flex-1 text-left hover:text-[var(--primary)]"
                        title={t("Jump to bookmark")}
                      >
                        <span className="block truncate text-sm font-medium">{bookmark.title}</span>
                        <span className="block text-xs text-[var(--muted-foreground)]">
                          {bookmark.chapter_title} · #{bookmark.group_index + 1} · {Math.round(bookmark.scroll_percent)}%
                        </span>
                      </button>
                      <div className="flex items-center gap-1">
                        <button
                          type="button"
                          onClick={() => {
                            setEditingId(bookmark.id);
                            setDraftTitle(bookmark.title);
                          }}
                          aria-label={t("Rename bookmark")}
                          className="rounded p-1 text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
                        >
                          <Pencil size={14} />
                        </button>
                        <button
                          type="button"
                          onClick={() => onDelete(bookmark.id)}
                          aria-label={t("Delete bookmark")}
                          className="rounded p-1 text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </div>
                  )}
                  {bookmark.preview && (
                    <p className="mt-2 line-clamp-2 text-xs text-[var(--muted-foreground)]">{bookmark.preview}</p>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function ChapterDifficultyPanel({ state }: { state: ChapterPreviewState | null }) {
  const { t } = useTranslation();
  if (!state || state.loading) return null;

  const bands: Array<{ key: VocabularyBand; label: string }> = [
    { key: "advanced", label: t("Advanced") },
    { key: "low", label: t("Low frequency") },
    { key: "unknown", label: t("Unclassified") },
  ];

  return (
    <section className="mb-5 rounded-lg border border-[var(--border)] bg-[var(--card)]/70 p-3">
      <div className="flex items-start justify-between gap-3">
        <h3 className="flex items-center gap-2 text-xs font-semibold text-[var(--foreground)]">
          <BookOpenCheck size={15} className="text-[var(--primary)]" />
          {t("Difficult words in this chapter")}
        </h3>
        <div className="flex flex-wrap justify-end gap-1.5 text-[10px] text-[var(--muted-foreground)]">
          {bands.map((band) => (
            <span key={band.key} className="rounded bg-[var(--muted)] px-1.5 py-0.5">
              {band.label} {state.data?.distribution?.[band.key] || 0}
            </span>
          ))}
        </div>
      </div>
      {state.error ? (
        <p className="mt-2 text-xs text-amber-600">{state.error}</p>
      ) : !state.data?.available ? (
        <p className="mt-2 text-xs text-[var(--muted-foreground)]">
          {t("Vocabulary difficulty needs an ECDICT import with frequency fields.")}
        </p>
      ) : state.data.words.length === 0 ? (
        <p className="mt-2 text-xs text-[var(--muted-foreground)]">
          {t("No difficult words detected.")}
        </p>
      ) : (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {state.data.words.slice(0, 18).map((word) => (
            <span
              key={`${word.lemma}-${word.word}`}
              className={`inline-flex max-w-full items-center gap-1 rounded px-1.5 py-0.5 text-xs ${DIFFICULTY_CLASSES[word.band]}`}
              title={[word.phonetic, word.chinese || word.definition].filter(Boolean).join(" · ")}
            >
              <span className="truncate">{word.word}</span>
              {word.count > 1 && <span className="text-[10px] opacity-75">×{word.count}</span>}
            </span>
          ))}
        </div>
      )}
    </section>
  );
}

function VocabularyReviewDrawer({
  onClose,
  onReviewed,
}: {
  onClose: () => void;
  onReviewed: () => void;
}) {
  const { t } = useTranslation();
  const [entries, setEntries] = useState<VocabEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [revealed, setRevealed] = useState(false);
  const [mode, setMode] = useState<ReviewMode>("cloze");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    immersiveReadingApi
      .reviewVocabulary(10)
      .then((data) => {
        if (!cancelled) setEntries(data.entries || []);
      })
      .catch((cause) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : String(cause));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  const current = entries[0];
  const card = current?.cards.find((item) => item.card_type === mode);
  const choices =
    mode === "choice"
      ? card?.choices?.length
        ? card.choices
        : current
          ? [current.word]
          : []
      : [];

  const grade = async (correct: boolean) => {
    if (!current || busy) return;
    setBusy(true);
    try {
      await immersiveReadingApi.gradeVocabularyReview(current.id, correct);
      setEntries((previous) => previous.filter((item) => item.id !== current.id));
      setRevealed(false);
      setMode("cloze");
      onReviewed();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  return (
    <aside
      role="complementary"
      aria-label={t("Today: review 10 words")}
      className="fixed right-0 top-0 z-[110] flex h-full w-full max-w-[380px] flex-col border-l border-[var(--border)] bg-[var(--background)] shadow-2xl"
    >
      <div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-3">
        <div className="min-w-0">
          <h3 className="flex items-center gap-2 text-sm font-semibold">
            <Brain size={16} className="text-[var(--primary)]" />
            {t("Today: review 10 words")}
          </h3>
          {!loading && !error && entries.length > 0 && (
            <p className="mt-0.5 text-xs text-[var(--muted-foreground)]">
              {t("{{count}} remaining", { count: entries.length })}
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label={t("Close")}
          className="rounded p-1 text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
        >
          <X size={16} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {loading ? (
          <div className="flex h-full items-center justify-center">
            <Loader2 className="size-6 animate-spin text-[var(--muted-foreground)]" />
          </div>
        ) : error ? (
          <div className="space-y-3 text-center">
            <FileText size={28} className="mx-auto text-[var(--muted-foreground)]" />
            <p className="text-sm text-red-500">{error}</p>
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg px-3 py-1.5 text-sm text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
            >
              {t("Close")}
            </button>
          </div>
        ) : !current ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
            <BookOpenCheck size={30} className="text-emerald-500" />
            <p className="text-sm font-medium">{t("Today's review is complete")}</p>
            <p className="text-xs text-[var(--muted-foreground)]">
              {t("Due words will return on their spaced-repetition schedule.")}
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="flex items-center gap-1 rounded-lg bg-[var(--muted)] p-1">
              {(["cloze", "choice"] as const).map((value) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => {
                    setMode(value);
                    setRevealed(false);
                  }}
                  className={`flex-1 rounded-md px-2 py-1.5 text-xs transition ${
                    mode === value
                      ? "bg-[var(--background)] font-medium text-[var(--foreground)] shadow-sm"
                      : "text-[var(--muted-foreground)]"
                  }`}
                >
                  {value === "cloze" ? t("Fill in the blank") : t("Multiple choice")}
                </button>
              ))}
            </div>

            <article className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-4">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-xs text-[var(--muted-foreground)]">
                    {current.section_title || current.document_title}
                  </p>
                  {(current.occurrence_count || 1) > 1 && (
                    <p className="mt-0.5 text-[10px] text-[var(--primary)]">
                      {t("Seen {{count}} times", { count: current.occurrence_count })}
                    </p>
                  )}
                </div>
              </div>

              <p className="mt-3 text-base font-medium leading-7 text-[var(--foreground)]">
                {card?.front || current.context_en || current.word}
              </p>
              {current.context_zh && (
                <p className="mt-2 text-sm leading-6 text-[var(--muted-foreground)]">
                  {current.context_zh}
                </p>
              )}

              {mode === "choice" && choices.length > 0 ? (
                <div className="mt-4 grid gap-2">
                  {choices.map((choice) => (
                    <button
                      key={choice}
                      type="button"
                      disabled={busy}
                      onClick={() => void grade(choice.toLowerCase() === current.word.toLowerCase())}
                      className="rounded-lg border border-[var(--border)] px-3 py-2 text-left text-sm transition hover:border-[var(--primary)]/50 hover:bg-[var(--primary)]/8 disabled:opacity-50"
                    >
                      {choice}
                    </button>
                  ))}
                </div>
              ) : revealed ? (
                <div className="mt-4 space-y-2 border-t border-[var(--border)] pt-3">
                  <p className="text-sm">
                    <span className="font-semibold">{current.word}</span>
                    {current.phonetic && (
                      <span className="ml-2 text-xs text-[var(--muted-foreground)]">
                        {current.phonetic}
                      </span>
                    )}
                  </p>
                  {(current.chinese || current.context_note) && (
                    <p className="text-sm text-[var(--muted-foreground)]">
                      {current.chinese || current.context_note}
                    </p>
                  )}
                  {current.definitions[0] && (
                    <p className="text-xs leading-5 text-[var(--muted-foreground)]">
                      {current.definitions[0].part_of_speech}{" "}
                      {current.definitions[0].definition}
                    </p>
                  )}
                </div>
              ) : null}
            </article>

            {mode === "cloze" && (
              <div className="flex gap-2">
                {!revealed ? (
                  <button
                    type="button"
                    onClick={() => setRevealed(true)}
                    className="flex-1 rounded-lg bg-[var(--primary)] px-3 py-2 text-sm font-medium text-[var(--primary-foreground)]"
                  >
                    {t("Show answer")}
                  </button>
                ) : (
                  <>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void grade(false)}
                      className="flex-1 rounded-lg border border-rose-500/35 px-3 py-2 text-sm font-medium text-rose-600 hover:bg-rose-500/10 disabled:opacity-50"
                    >
                      {t("Still learning")}
                    </button>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void grade(true)}
                      className="flex-1 rounded-lg border border-emerald-500/35 px-3 py-2 text-sm font-medium text-emerald-600 hover:bg-emerald-500/10 disabled:opacity-50"
                    >
                      {busy ? <Loader2 size={14} className="mx-auto animate-spin" /> : t("Knew it")}
                    </button>
                  </>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </aside>
  );
}

function BilingualGroup({
  group,
  index,
  mode,
  pane,
  open,
  active,
  focusedReading,
  isBookmarked,
  fontSize,
  fontFamily,
  peekVisible,
  isFlagged,
  difficultyByWord,
  onSelect,
  onToggle,
  onSideTap,
  onFlag,
  onPointerEnter,
  onPointerLeave,
  onPeekToggle,
}: {
  group: import("@/lib/immersive-reading-api").BilingualAlignGroup;
  index: number;
  mode: BilingualReaderMode;
  pane: "combined" | "english" | "chinese";
  open: boolean;
  active: boolean;
  focusedReading: boolean;
  isBookmarked: boolean;
  fontSize: BilingualFontSize;
  fontFamily: BilingualFontFamily;
  peekVisible: boolean;
  isFlagged: boolean;
  difficultyByWord: Map<string, VocabularyBand>;
  onSelect: () => void;
  onToggle: () => void;
  onSideTap: () => void;
  onFlag: () => void;
  onPointerEnter: () => void;
  onPointerLeave: () => void;
  onPeekToggle: () => void;
}) {
  const { t } = useTranslation();
  const activeClass = active
    ? "rounded-xl bg-[var(--primary)]/8 shadow-[inset_4px_0_0_0_var(--primary)] ring-1 ring-[var(--primary)]/20"
    : focusedReading
      ? "rounded-xl opacity-70"
      : "rounded-xl hover:bg-[var(--muted)]/20";
  const handleTap = (event: React.MouseEvent<HTMLDivElement>) => {
    onSelect();
    if (pane !== "combined" || shouldIgnoreLookupTarget(event.target)) return;
    if (window.getSelection()?.toString().trim()) return;

    const target = event.target instanceof Element ? event.target : null;
    const paragraphs = Array.from(event.currentTarget.querySelectorAll("p"));
    const paragraph =
      target?.closest("p") ||
      paragraphs.find((item) => {
        const rect = item.getBoundingClientRect();
        return event.clientY >= rect.top && event.clientY <= rect.bottom;
      });
    if (!(paragraph instanceof HTMLParagraphElement)) return;
    const line = paragraphLineRectAtY(paragraph, event.clientY);
    if (line && isParagraphSideTap({ x: event.clientX, y: event.clientY }, line)) {
      onSideTap();
    }
  };

  const fontClass = fontFamily === "serif" ? "font-serif" : "font-sans";
  const sizeStyles = FONT_SIZE_STYLES[fontSize];

  const chineseFont = {
    fontFamily:
      fontFamily === "serif"
        ? '"Songti SC","Noto Serif CJK SC","PingFang TC","Heiti TC",serif'
        : '"PingFang SC","Microsoft YaHei","Heiti SC",sans-serif',
  };

  if (pane === "chinese") {
    return (
      <div
        className={`group/para relative px-3.5 py-2.5 transition-all duration-150 cursor-pointer ${activeClass}`}
        data-group-index={index}
        data-active={active || undefined}
        onClick={handleTap}
        onPointerEnter={onPointerEnter}
        onPointerLeave={onPointerLeave}
      >
        {isBookmarked && (
          <span
            className="absolute right-2 top-2 text-[var(--primary)]"
            title={t("Bookmarked")}
          >
            <Bookmark size={13} className="fill-current" />
          </span>
        )}
        {group.zh.length > 0 ? (
          group.zh.map((para, pi) => (
            <p
              key={pi}
              className={`${fontClass} ${sizeStyles.zh} text-[var(--foreground)]`}
              style={chineseFont}
            >
              {para}
            </p>
          ))
        ) : (
          <p className="text-sm text-[var(--muted-foreground)]">{t("No Chinese translation")}</p>
        )}
      </div>
    );
  }

  if (pane === "english") {
    return (
      <div
        className={`group/para relative px-3.5 py-2.5 transition-all duration-150 cursor-pointer ${activeClass}`}
        data-group-index={index}
        data-active={active || undefined}
        onClick={handleTap}
        onPointerEnter={onPointerEnter}
        onPointerLeave={onPointerLeave}
      >
        {isBookmarked && (
          <span
            className="absolute right-6 top-2 text-[var(--primary)]"
            title={t("Bookmarked")}
          >
            <Bookmark size={13} className="fill-current" />
          </span>
        )}
        {group.en.map((para, pi) => (
          <p key={pi} className={`select-text ${fontClass} ${sizeStyles.en} text-[var(--foreground)]`}>
            {renderEnglishParagraph(para, difficultyByWord)}
          </p>
        ))}
        {group.low_confidence && group.shape !== "1:1" && (
          <span className="text-xs text-[var(--muted-foreground)]">({group.shape})</span>
        )}
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onFlag();
          }}
          className="absolute right-1 top-1 rounded p-1 text-[var(--muted-foreground)] opacity-0 transition hover:bg-[var(--muted)] focus-visible:opacity-100 group-hover/para:opacity-100"
          title={t("Flag issue")}
          aria-label={t("Flag issue")}
        >
          <Flag size={14} className={isFlagged ? "fill-amber-400 text-amber-500" : ""} />
        </button>
      </div>
    );
  }

  return (
    <div
      className={`group/para relative space-y-1 px-3 py-2 transition-all duration-150 cursor-pointer ${activeClass}`}
      data-group-index={index}
      data-active={active || undefined}
      onClick={handleTap}
      onPointerEnter={onPointerEnter}
      onPointerLeave={onPointerLeave}
    >
      {isBookmarked && (
        <span
          className="absolute right-6 top-2 text-[var(--primary)]"
          title={t("Bookmarked")}
        >
          <Bookmark size={13} className="fill-current" />
        </span>
      )}
      {group.en.map((para, pi) => (
        <p key={pi} className={`select-text ${fontClass} ${sizeStyles.en} text-[var(--foreground)]`}>
          {renderEnglishParagraph(para, difficultyByWord)}
        </p>
      ))}

      {mode === "hover" ? (
        <>
          <button
            type="button"
            data-reader-control
            onClick={(e) => {
              e.stopPropagation();
              onPeekToggle();
            }}
            className="absolute right-0 top-0 rounded p-1 text-[var(--muted-foreground)] opacity-100 transition hover:bg-[var(--muted)] focus-visible:opacity-100 sm:opacity-0 sm:group-hover/para:opacity-100"
            title={t("Show translation")}
            aria-label={t("Show translation")}
            aria-expanded={peekVisible}
          >
            <Eye size={14} />
          </button>
          <div
            className={`absolute right-0 top-7 z-20 w-[min(24rem,calc(100%-0.5rem))] rounded-lg border border-[var(--border)] bg-[var(--background)] p-3 shadow-xl transition-opacity duration-150 ${
              peekVisible
                ? "pointer-events-auto opacity-100"
                : "pointer-events-none opacity-0 group-hover/para:opacity-100"
            }`}
          >
            {group.zh.length > 0 ? (
              group.zh.map((para, pi) => (
                <p key={pi} className={`${fontClass} ${sizeStyles.zh} text-[var(--foreground)]`} style={chineseFont}>
                  {para}
                </p>
              ))
            ) : (
              <p className="text-sm text-[var(--muted-foreground)]">{t("No Chinese translation")}</p>
            )}
          </div>
        </>
      ) : group.zh.length > 0 ? (
        <details
          open={open}
          onClick={(e) => e.stopPropagation()}
          onToggle={(event) => {
            if ((event.target as HTMLDetailsElement).open !== open) onToggle();
          }}
          className="bilingual-zh-details my-1.5 rounded-lg border-l-[3px] border-l-[var(--primary)] bg-[var(--muted)]/40 px-3.5 py-2.5"
        >
          <summary data-reader-control className="cursor-pointer text-xs font-semibold text-[var(--primary)] select-none">
            {open ? t("Hide Chinese") : t("Show Chinese")}
          </summary>
          <div className="mt-2 space-y-1.5 pt-1">
            {group.zh.map((para, pi) => (
              <p
                key={pi}
                className={`${fontClass} ${sizeStyles.zh} text-[var(--foreground)]`}
                style={chineseFont}
              >
                {para}
              </p>
            ))}
          </div>
        </details>
      ) : null}

      {mode !== "hover" && group.low_confidence && group.shape !== "1:1" && (
        <span className="text-xs text-[var(--muted-foreground)]">({group.shape})</span>
      )}
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onFlag();
        }}
        className="absolute right-0 top-0 rounded p-1 text-[var(--muted-foreground)] opacity-0 transition hover:bg-[var(--muted)] focus-visible:opacity-100 group-hover/para:opacity-100"
        title={t("Flag issue")}
        aria-label={t("Flag issue")}
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
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm text-[var(--foreground)]"
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
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm text-[var(--foreground)]"
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
      const data = await bilingualApi.report(pairingId);
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
                      {t("EN")}: {ann.en_text}
                    </p>
                    <p className="line-clamp-2 text-xs text-[var(--muted-foreground)]">
                      {t("ZH")}: {ann.zh_text}
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
