"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import { Languages, Volume2, VolumeX } from "lucide-react";
import { ReactReaderStyle } from "react-reader";
import {
  kidsApi,
  resolveKidsReadingSectionId,
  type KidsLearnResult,
  type KidsWordHint,
  type KidsReadingSection,
  type KidsSafeQuestion,
  type KidsQuizGrade,
} from "@/lib/kids-api";
import { GuidedLearnModal } from "@/components/kids/GuidedLearnModal";
import { RewardSnapshotView } from "@/components/kids/RewardSnapshot";
import {
  detectKidsReadingLanguage,
  kidsLearningCopy,
  type KidsLearningLanguage,
} from "@/lib/kids-learning/learn-language";
import { shouldOpenChapterCheck } from "@/lib/kids-learning/chapter-check";
import {
  createInitialWordHintState,
  reduceWordHintState,
  type KidsWordHintState,
} from "@/lib/kids-learning/word-hint";
import {
  speakKidsText,
  stopKidsSpeech,
  subscribeKidsSpeechState,
} from "@/lib/kids-learning/pronunciation";
import {
  createKidsPageTurnGestureTracker,
  getKidsPageTurnDirectionForLayout,
  resolveKidsPageTurnSwipe,
  shouldAllowKidsPageTurnGesture,
  shouldAllowKidsPageTurnKeyboard,
} from "@/lib/kids-learning/page-turn";
import { getVisiblePageText } from "@/lib/kids-learning/visible-page-text";

const ReactReader = dynamic(
  () => import("react-reader").then((m) => m.ReactReader),
  { ssr: false, loading: () => <div style={{ textAlign: "center", padding: 40 }}>Opening book...</div> },
);

type Rendition = any;
type NavItem = any;

const ENGLISH_WORD_RE = /([A-Za-z][A-Za-z'-]*)/g;
const ENGLISH_WORD_TEST_RE = /[A-Za-z][A-Za-z'-]*/;

const kidsReaderStyles = {
  ...ReactReaderStyle,
  tocArea: {
    ...ReactReaderStyle.tocArea,
    background: "#fff8eb",
  },
  tocAreaButton: {
    ...ReactReaderStyle.tocAreaButton,
    color: "#3730a3",
    fontSize: "0.95em",
    fontWeight: 700,
    borderBottom: "1px solid #f2d9a8",
  },
  tocButtonBar: {
    ...ReactReaderStyle.tocButtonBar,
    background: "#6d28d9",
  },
  reader: {
    ...ReactReaderStyle.reader,
    top: 56,
    right: "max(20px, min(18vw, 96px))",
    bottom: 16,
    left: "max(20px, min(18vw, 96px))",
  },
  arrow: {
    ...ReactReaderStyle.arrow,
    display: "none",
  },
};

function decorateEpubWords(document: Document | undefined): void {
  if (!document?.body || document.body.dataset.kidsWordsReady === "true") return;
  document.body.dataset.kidsWordsReady = "true";
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const parent = node.parentElement;
      if (!parent || ["script", "style"].includes(parent.tagName.toLowerCase())) {
        return NodeFilter.FILTER_REJECT;
      }
      return ENGLISH_WORD_TEST_RE.test(node.nodeValue || "")
        ? NodeFilter.FILTER_ACCEPT
        : NodeFilter.FILTER_SKIP;
    },
  });

  const nodes: Text[] = [];
  while (walker.nextNode()) nodes.push(walker.currentNode as Text);
  for (const node of nodes) {
    const source = node.nodeValue || "";
    if (!source.trim()) continue;
    const fragment = document.createDocumentFragment();
    let cursor = 0;
    for (const match of source.matchAll(ENGLISH_WORD_RE)) {
      const index = match.index ?? 0;
      if (index > cursor) fragment.appendChild(document.createTextNode(source.slice(cursor, index)));
      const word = document.createElement("span");
      word.setAttribute("data-kids-word", match[0]);
      word.style.cursor = "pointer";
      word.textContent = match[0];
      fragment.appendChild(word);
      cursor = index + match[0].length;
    }
    if (cursor < source.length) fragment.appendChild(document.createTextNode(source.slice(cursor)));
    node.parentNode?.replaceChild(fragment, node);
  }
}

export default function KidsReaderPage() {
  const router = useRouter();
  const params = useParams();
  const documentId = params.documentId as string;

  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [epubUrl, setEpubUrl] = useState("");
  const [bookTitle, setBookTitle] = useState("");
  const [location, setLocation] = useState<string | null>(null);
  const [toc, setToc] = useState<NavItem[]>([]);
  const [showLearn, setShowLearn] = useState(false);
  const [learningMode, setLearningMode] = useState<"learn" | "quiz">("quiz");
  const [learnResult, setLearnResult] = useState<KidsLearnResult | null>(null);
  const [learnLoading, setLearnLoading] = useState(false);
  const [learnError, setLearnError] = useState("");
  const [contentLanguage, setContentLanguage] = useState<KidsLearningLanguage>("en");
  const [helpLanguage, setHelpLanguage] = useState<KidsLearningLanguage>("en");
  const [questions, setQuestions] = useState<KidsSafeQuestion[]>([]);
  const [quizLoading, setQuizLoading] = useState(false);
  const [answers, setAnswers] = useState<Record<number, number>>({});
  const [grade, setGrade] = useState<KidsQuizGrade | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [speakingId, setSpeakingId] = useState<string | null>(null);
  const [translateText, setTranslateText] = useState<string | null>(null);
  const [translateResult, setTranslateResult] = useState("");
  const [translating, setTranslating] = useState(false);
  const [wordHintData, setWordHintData] = useState<KidsWordHint | null>(null);
  const [wordHintState, setWordHintState] = useState<KidsWordHintState | null>(null);
  const [wordHintBusy, setWordHintBusy] = useState(false);
  const [wordHintMessage, setWordHintMessage] = useState("");
  // Exit-protection state
  const [showExitPin, setShowExitPin] = useState(false);
  const [exitPin, setExitPin] = useState("");
  const [exitPinError, setExitPinError] = useState("");
  const [profileHasPin, setProfileHasPin] = useState(false);
  const [profileId, setProfileId] = useState("");
  const [isRtl, setIsRtl] = useState(false);
  const renditionRef = useRef<Rendition | null>(null);
  const isRtlRef = useRef(false);
  const pageTurnTrackerRef = useRef(createKidsPageTurnGestureTracker());
  const keyboardPageTurnBlockedRef = useRef(false);
  const lastPageKeyEventRef = useRef<KeyboardEvent | null>(null);
  const currentHrefRef = useRef<string>("");
  const currentSectionIdRef = useRef<string>("");
  const quizSectionIdRef = useRef<string>("");
  const completedSectionIdsRef = useRef<string[]>([]);
  const shownSectionIdsRef = useRef<string[]>([]);
  const quizLoadTokenRef = useRef(0);
  const lastRelocatedCfiRef = useRef<string>("");
  const learningAbortRef = useRef<AbortController | null>(null);
  const sawInitialSectionRef = useRef(false);
  const sectionsRef = useRef<KidsReadingSection[]>([]);
  const tocRef = useRef<NavItem[]>([]);

  useEffect(() => {
    let cancelled = false;
    let objectUrl = "";
    (async () => {
      try {
        const data = await kidsApi.getBook(documentId);
        if (cancelled) return;
        const doc = data.document as Record<string, any>;
        setBookTitle(doc.title || "Book");
        setContentLanguage(doc.content_language === "zh" ? "zh" : "en");
        completedSectionIdsRef.current = data.progress?.completed_section_ids || [];
        const docSections = Array.isArray(doc.sections) ? doc.sections : [];
        sectionsRef.current = docSections;
        currentSectionIdRef.current =
          docSections.find((section: KidsReadingSection) => section.id === data.progress?.current_section_id)?.id || "";
        if (data.progress?.epub_cfi) {
          setLocation(data.progress.epub_cfi);
        }
        objectUrl = await kidsApi.getEpubBlobUrl(documentId);
        if (cancelled) {
          URL.revokeObjectURL(objectUrl);
          return;
        }
        setEpubUrl(objectUrl);
      } catch {
        if (!cancelled) {
          setBookTitle("Book");
          setLoadError("OPEN_BOOK_FAILED");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [documentId]);

  useEffect(() => () => {
    if (epubUrl) URL.revokeObjectURL(epubUrl);
  }, [epubUrl]);

  useEffect(() => {
    const unsubscribe = subscribeKidsSpeechState((state) => {
      setSpeakingId(state.isPlaying ? state.text : null);
    });
    return () => {
      unsubscribe();
      stopKidsSpeech();
    };
  }, []);

  // Check if the current profile has a PIN (for exit protection)
  useEffect(() => {
    const pid = localStorage.getItem("dt_kids_profile_id") || "";
    setProfileId(pid);
    if (!pid) return;
    kidsApi.bootstrap().then(({ profiles }) => {
      const p = profiles.find((x) => x.id === pid);
      if (p) {
        setProfileHasPin(!!p.has_pin);
        setHelpLanguage(p.help_language === "zh" ? "zh" : "en");
      }
    }).catch(() => {});
  }, []);

  const handleExitClick = () => {
    if (profileHasPin) {
      setShowExitPin(true);
      setExitPin("");
      setExitPinError("");
    } else {
      router.push("/kids");
    }
  };

  const handleExitPinSubmit = async () => {
    try {
      await kidsApi.exitVerify(profileId, exitPin);
      router.push("/kids");
    } catch {
      setExitPinError("Wrong PIN. Try again!");
      setExitPin("");
    }
  };

  const saveProgress = useCallback(
    (loc: string, href: string) => {
      const sectionId =
        currentSectionIdRef.current ||
        resolveKidsReadingSectionId(href, tocRef.current, sectionsRef.current);
      const sectionIndex = sectionsRef.current.find((section) => section.id === sectionId)?.index || 0;
      kidsApi.updateProgress(documentId, {
        section_id: sectionId,
        section_index: sectionIndex,
        scroll_percent: 0,
        epub_cfi: loc,
        section_href: href,
        time_delta: 0,
      }).catch(() => {});
    },
    [documentId],
  );

  const stopSpeaking = useCallback(() => {
    stopKidsSpeech();
    setSpeakingId(null);
  }, []);

  const turnPage = useCallback((direction: "previous" | "next") => {
    const rendition = renditionRef.current;
    if (!rendition) return;
    const layoutDirection = getKidsPageTurnDirectionForLayout(direction, isRtlRef.current);
    if (layoutDirection === "previous") rendition.prev();
    else rendition.next();
  }, []);

  const handlePageKey = useCallback((event: KeyboardEvent) => {
    if (lastPageKeyEventRef.current === event) return;
    lastPageKeyEventRef.current = event;
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    if (event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return;
    if (keyboardPageTurnBlockedRef.current) return;
    if (!shouldAllowKidsPageTurnKeyboard(event.target)) return;
    turnPage(event.key === "ArrowLeft" ? "previous" : "next");
  }, [turnPage]);

  useEffect(() => {
    keyboardPageTurnBlockedRef.current =
      showLearn || Boolean(wordHintState) || showExitPin || Boolean(translateText);
  }, [showExitPin, showLearn, translateText, wordHintState]);

  useEffect(() => {
    window.addEventListener("keyup", handlePageKey);
    return () => window.removeEventListener("keyup", handlePageKey);
  }, [handlePageKey]);

  const narrate = useCallback((id: string, text: string) => {
    if (speakingId === id) {
      stopSpeaking();
      return;
    }
    const started = speakKidsText(id, text, {
      onEnd: () => {
        setSpeakingId((currentId) => (currentId === id ? null : currentId));
      },
      onError: () => {
        setSpeakingId((currentId) => (currentId === id ? null : currentId));
      },
    });
    setSpeakingId(started ? id : null);
  }, [speakingId, stopSpeaking]);

  const handleReadAloud = useCallback(() => {
    if (speakingId === "read-aloud") {
      stopSpeaking();
      return;
    }

    let textToRead = "";
    try {
      const iframeWindow = (renditionRef.current as any)?.getContents?.()?.[0]?.window;
      const iframeSel = iframeWindow?.getSelection?.()?.toString()?.trim();
      if (iframeSel) {
        textToRead = iframeSel;
      }
    } catch {}

    if (!textToRead) {
      try {
        const winSel = window.getSelection?.()?.toString()?.trim();
        if (winSel) {
          textToRead = winSel;
        }
      } catch {}
    }

    if (!textToRead && renditionRef.current) {
      try {
        const contents = (renditionRef.current as any)?.getContents?.();
        if (contents && contents.length > 0) {
          const content = contents[0];
          const doc = content?.document as Document | undefined;
          const win = content?.window as Window | undefined;
          const visible = getVisiblePageText(doc, win, renditionRef.current);
          if (visible && visible.trim()) {
            textToRead = visible.trim();
          }
        }
      } catch {}
    }

    if (!textToRead && bookTitle) {
      textToRead = bookTitle;
    }

    if (!textToRead.trim()) return;

    narrate("read-aloud", textToRead);
  }, [bookTitle, narrate, speakingId, stopSpeaking]);

  const speakSelection = handleReadAloud;

  const speakQuizText = useCallback((id: string, text: string) => {
    narrate(id, text);
  }, [narrate]);

  const getVisibleText = useCallback(() => {
    try {
      const contents = (renditionRef.current as any)?.getContents?.();
      const content = contents?.[0];
      return getVisiblePageText(
        content?.document as Document | undefined,
        content?.window as Window | undefined,
        renditionRef.current,
      ).trim();
    } catch {
      return "";
    }
  }, []);

  const handleTranslate = useCallback(async (text: string) => {
    setTranslateText(text);
    setTranslating(true);
    setTranslateResult("");
    const pageLanguage = detectKidsReadingLanguage(text || getVisibleText(), contentLanguage);
    const targetLanguage =
      pageLanguage === "zh" ? "English" : helpLanguage === "zh" ? "Chinese" : "English";
    try {
      const { translation } = await kidsApi.translate(text, targetLanguage);
      setTranslateResult(translation);
    } catch {
      setTranslateResult(kidsLearningCopy(pageLanguage).translateUnavailable);
    } finally {
      setTranslating(false);
    }
  }, [contentLanguage, getVisibleText, helpLanguage]);

  const closeWordHint = useCallback(() => {
    setWordHintState(null);
    setWordHintData(null);
    setWordHintMessage("");
    stopSpeaking();
  }, [stopSpeaking]);

  const openWordHint = useCallback(
    async (word: string, context: string) => {
      const normalizedWord = word.replace(/[^A-Za-z'-]/g, "");
      if (!normalizedWord) return;
      const sectionId =
        currentSectionIdRef.current ||
        resolveKidsReadingSectionId(currentHrefRef.current, tocRef.current, sectionsRef.current);
      if (!sectionId) return;

      setShowLearn(false);
      stopSpeaking();
      setWordHintBusy(true);
      setWordHintMessage("");
      setWordHintData(null);
      setWordHintState(createInitialWordHintState(normalizedWord));
      try {
        const hint = await kidsApi.getWordHint(documentId, {
          word: normalizedWord,
          section_id: sectionId,
          context: context.slice(0, 2000),
        });
        setWordHintData(hint);
        if (!hint.available) setWordHintMessage("Let us try another word.");
      } catch {
        setWordHintMessage("Word help is resting. Try again.");
      } finally {
        setWordHintBusy(false);
      }
    },
    [documentId, stopSpeaking],
  );

  const showWordHintChoices = useCallback(async () => {
    if (!wordHintData?.hint_id || !wordHintState) return;
    setWordHintBusy(true);
    try {
      const { choices } = await kidsApi.getWordHintChoices(documentId, wordHintData.hint_id);
      setWordHintState((state) =>
        state ? reduceWordHintState(state, { type: "show-choices", choices }) : state,
      );
    } catch {
      setWordHintMessage("Choices are resting. Try again.");
    } finally {
      setWordHintBusy(false);
    }
  }, [documentId, wordHintData, wordHintState]);

  const checkWordHintChoice = useCallback(
    async (choice: string) => {
      if (!wordHintData?.hint_id || !wordHintState || wordHintState.phase !== "choices") return;
      const attempt = wordHintState.wrongAttempts + 1;
      setWordHintBusy(true);
      try {
        const result = await kidsApi.checkWordHint(
          documentId,
          wordHintData.hint_id,
          choice,
          attempt,
        );
        setWordHintState((state) =>
          state
            ? reduceWordHintState(state, {
                type: "check",
                correct: result.correct,
                attempt,
                feedback: result.feedback,
                correctChoice: result.correct_choice,
                chinese: result.chinese,
                explanation: result.explanation,
              })
            : state,
        );
      } catch {
        setWordHintMessage("Checking is resting. Try again.");
      } finally {
        setWordHintBusy(false);
      }
    },
    [documentId, wordHintData, wordHintState],
  );

  const revealWordHint = useCallback(async () => {
    if (!wordHintData?.hint_id || !wordHintState) return;
    setWordHintBusy(true);
    try {
      const result = await kidsApi.revealWordHint(documentId, wordHintData.hint_id);
      setWordHintState((state) =>
        state
          ? reduceWordHintState(state, {
              type: "reveal",
              correctChoice: result.correct_choice,
              chinese: result.chinese,
              explanation: result.explanation,
            })
          : state,
      );
    } catch {
      setWordHintMessage("Word help is resting. Try again.");
    } finally {
      setWordHintBusy(false);
    }
  }, [documentId, wordHintData, wordHintState]);

  const closeLearnQuestions = useCallback(() => {
    quizLoadTokenRef.current += 1;
    learningAbortRef.current?.abort();
    learningAbortRef.current = null;
    setShowLearn(false);
    setQuizLoading(false);
    setLearnLoading(false);
    setLearnError("");
    setLearnResult(null);
    stopSpeaking();
  }, [stopSpeaking]);

  const beginLearningRequest = useCallback(() => {
    learningAbortRef.current?.abort();
    const controller = new AbortController();
    learningAbortRef.current = controller;
    window.setTimeout(() => controller.abort(), 15000);
    return controller;
  }, []);

  const loadConceptLearn = useCallback(async () => {
    const token = ++quizLoadTokenRef.current;
    const controller = beginLearningRequest();
    const visibleText = getVisibleText().slice(0, 3000);
    if (!visibleText.trim()) {
      const pageLanguage = detectKidsReadingLanguage(visibleText, contentLanguage);
      setContentLanguage(pageLanguage);
      setWordHintState(null);
      setWordHintData(null);
      setWordHintMessage("");
      setLearningMode("learn");
      setShowLearn(true);
      setLearnResult(null);
      setLearnError(kidsLearningCopy(pageLanguage).learnError);
      setLearnLoading(false);
      stopSpeaking();
      return;
    }
    const pageLanguage = detectKidsReadingLanguage(visibleText, contentLanguage);
    setContentLanguage(pageLanguage);
    setWordHintState(null);
    setWordHintData(null);
    setWordHintMessage("");
    setLearningMode("learn");
    setShowLearn(true);
    setLearnResult(null);
    setLearnError("");
    stopSpeaking();
    setLearnLoading(true);

    const sectionId =
      currentSectionIdRef.current ||
      resolveKidsReadingSectionId(currentHrefRef.current, tocRef.current, sectionsRef.current) ||
      (sectionsRef.current.find((s) => s.checkpoint_kind === "chapter")?.id || sectionsRef.current[0]?.id || "");
    try {
      const result = await kidsApi.getLearn(
        documentId,
        { section_id: sectionId, visible_text: visibleText },
        controller.signal,
      );
      if (token !== quizLoadTokenRef.current) return;
      setContentLanguage(result.language);
      setLearnResult(result);
    } catch (error) {
      if (token !== quizLoadTokenRef.current || (error instanceof DOMException && error.name === "AbortError")) return;
      setLearnError(kidsLearningCopy(pageLanguage).learnError);
    } finally {
      if (token === quizLoadTokenRef.current) setLearnLoading(false);
    }
  }, [
    beginLearningRequest,
    contentLanguage,
    documentId,
    getVisibleText,
    stopSpeaking,
  ]);

  const loadLearnQuestions = useCallback(async (sectionIdOverride?: string) => {
    const token = ++quizLoadTokenRef.current;
    const controller = beginLearningRequest();
    setWordHintState(null);
    setWordHintData(null);
    setWordHintMessage("");
    setShowLearn(true);
    setLearningMode("quiz");
    setLearnResult(null);
    setLearnError("");
    setGrade(null);
    setAnswers({});
    stopSpeaking();
    setQuizLoading(true);
    try {
      const sectionId =
        sectionIdOverride ||
        currentSectionIdRef.current ||
        resolveKidsReadingSectionId(currentHrefRef.current, tocRef.current, sectionsRef.current);
      quizSectionIdRef.current = sectionId;
      const { questions: qs, language } = await kidsApi.getQuiz(
        documentId,
        sectionId,
        false,
        controller.signal,
      );
      if (token !== quizLoadTokenRef.current) return;
      setQuestions(qs);
      if (language) setContentLanguage(language);
    } catch (error) {
      if (token !== quizLoadTokenRef.current || (error instanceof DOMException && error.name === "AbortError")) return;
      if (token !== quizLoadTokenRef.current) return;
      setQuestions([]);
    } finally {
      if (token === quizLoadTokenRef.current) setQuizLoading(false);
    }
  }, [beginLearningRequest, documentId, stopSpeaking]);

  const handleLearnClick = useCallback(() => {
    const visibleText = getVisibleText();
    const pageLanguage = detectKidsReadingLanguage(visibleText, contentLanguage);
    setContentLanguage(pageLanguage);
    if (pageLanguage === "zh") {
      void loadConceptLearn();
      return;
    }

    if (renditionRef.current) {
      const selection = renditionRef.current.getRange?.();
      const text = selection?.toString()?.trim();
      if (text) {
        const word = text.split(/\s+/)[0].replace(/[^A-Za-z'-]/g, "");
        if (word) {
          void openWordHint(word, text);
          return;
        }
      }
    }

    const doc = (renditionRef.current as any)?.getContents?.()?.[0]?.document;
    const wordsInChapter: string[] = [];
    if (doc) {
      const spans = doc.querySelectorAll("[data-kids-word]");
      for (const span of Array.from(spans)) {
        const w = (span as HTMLElement).dataset.kidsWord;
        if (w && w.length >= 3 && !wordsInChapter.includes(w)) {
          wordsInChapter.push(w);
          if (wordsInChapter.length >= 6) break;
        }
      }
    }

    stopSpeaking();
    setShowLearn(false);
    setWordHintBusy(false);
    setWordHintData(null);
    setWordHintState({
      word: "Explore Words",
      phase: "picker",
      choices: wordsInChapter,
      wrongAttempts: 0,
    });
  }, [
    contentLanguage,
    getVisibleText,
    loadConceptLearn,
    openWordHint,
    stopSpeaking,
  ]);

  const submitLearnAnswers = async () => {
    setSubmitting(true);
    try {
      const answerArr = questions.map((_, i) => answers[i] ?? -1);
      const result = await kidsApi.submitQuiz(
        documentId,
        quizSectionIdRef.current ||
          currentSectionIdRef.current ||
          resolveKidsReadingSectionId(currentHrefRef.current, tocRef.current, sectionsRef.current),
        answerArr,
      );
      setGrade(result);
      completedSectionIdsRef.current = result.completed_section_ids || completedSectionIdsRef.current;
    } catch {
      // ignore
    } finally {
      setSubmitting(false);
    }
  };

  const copy = kidsLearningCopy(contentLanguage);

  if (loading) {
    return (
      <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "#e0f2ff" }}>
        <div style={{ fontSize: 60 }}>Book</div>
      </div>
    );
  }

  if (loadError || !epubUrl) {
    return (
      <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "#e0f2ff" }}>
        <div style={{ textAlign: "center", maxWidth: 360, padding: 24 }}>
          <div style={{ fontSize: 48, marginBottom: 12 }}>Book</div>
          <p style={{ fontSize: 18, color: "#4a3f6b", marginBottom: 20 }}>
            {loadError === "OPEN_BOOK_FAILED" ? copy.openBookError : copy.openingBook}
          </p>
          <button style={toolbarBtn} onClick={() => router.push("/kids")}>{copy.books}</button>
        </div>
      </div>
    );
  }

 return (
   <div className="kids-reader-shell" style={{ display: "flex", flexDirection: "column", background: "#fef9f0" }}>
      {/* Exit PIN modal */}
      {showExitPin && (
        <div style={{
          position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)",
          display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000,
        }}>
          <div style={{
            background: "white", borderRadius: 24, padding: 32,
            display: "flex", flexDirection: "column", alignItems: "center", gap: 16,
            boxShadow: "0 4px 14px rgba(0,0,0,0.1)", maxWidth: 360, width: "90%",
          }}>
            <p style={{ fontSize: 18, color: "#7c6f9b" }}>🔒 Enter PIN to exit</p>
            <input
              type="password"
              value={exitPin}
              onChange={(e) => setExitPin(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && exitPin.length >= 4 && handleExitPinSubmit()}
              maxLength={8}
              style={{
                fontSize: 32, textAlign: "center", letterSpacing: 12,
                border: "3px solid #667eea", borderRadius: 12, padding: "12px 16px",
                width: "100%", outline: "none",
              }}
              placeholder="• • • •"
              autoFocus
            />
            {exitPinError && <p style={{ fontSize: 16, color: "#e53e3e" }}>{exitPinError}</p>}
            <div style={{ display: "flex", gap: 12 }}>
              <button
                style={{ padding: "12px 24px", borderRadius: 12, border: "none", fontSize: 16, fontWeight: 700, cursor: "pointer", background: "#e2e8f0", color: "#4a5568" }}
                onClick={() => { setShowExitPin(false); setExitPin(""); setExitPinError(""); }}
              >
                Cancel
              </button>
              <button
                style={{ padding: "12px 24px", borderRadius: 12, border: "none", fontSize: 16, fontWeight: 700, cursor: "pointer", background: "#667eea", color: "white", opacity: exitPin.length < 4 ? 0.5 : 1 }}
                onClick={handleExitPinSubmit}
                disabled={exitPin.length < 4}
              >
                Exit
              </button>
            </div>
          </div>
        </div>
      )}
     <div style={{
       display: "flex",
       alignItems: "center",
       gap: 12,
       padding: "8px 16px",
       background: "white",
       boxShadow: "0 2px 6px rgba(0,0,0,0.06)",
       zIndex: 10,
       flexShrink: 0,
     }}>
        <button onClick={handleExitClick} style={toolbarBtn}>{copy.books}</button>
       <div style={{ flex: 1, textAlign: "center", fontWeight: 700, fontSize: 18, color: "#4a3f6b", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
         {bookTitle}
       </div>
        <button
          style={secondaryToolBtn}
          title="Translate selected words"
          aria-label="Translate selected words"
          onClick={async () => {
            if (!renditionRef.current) return;
            const sel = renditionRef.current.getRange?.();
            const text = sel?.toString() || "";
            if (text) handleTranslate(text);
          }}
        >
          <Languages size={18} />
        </button>
      </div>

      <div style={{ flex: 1, position: "relative", overflow: "hidden" }}>
        <button
          type="button"
          aria-label={copy.previousPage}
          title={copy.previousPage}
          style={pageTurnHotzone}
          onPointerDown={(event) => {
            if (event.isPrimary && event.button === 0) {
              pageTurnTrackerRef.current.begin(event.pointerId, event.clientX, event.clientY);
            }
          }}
          onPointerUp={(event) => {
            const direction = pageTurnTrackerRef.current.end(
              event.pointerId,
              event.clientX,
              event.clientY,
            );
            if (direction) turnPage(direction);
          }}
          onPointerCancel={() => pageTurnTrackerRef.current.cancel()}
          onClick={(event) => {
            if (pageTurnTrackerRef.current.consumeClick()) {
              event.preventDefault();
              return;
            }
            turnPage("previous");
          }}
        />
        <button
          type="button"
          aria-label={copy.nextPage}
          title={copy.nextPage}
          style={{ ...pageTurnHotzone, left: "auto", right: 0 }}
          onPointerDown={(event) => {
            if (event.isPrimary && event.button === 0) {
              pageTurnTrackerRef.current.begin(event.pointerId, event.clientX, event.clientY);
            }
          }}
          onPointerUp={(event) => {
            const direction = pageTurnTrackerRef.current.end(
              event.pointerId,
              event.clientX,
              event.clientY,
            );
            if (direction) turnPage(direction);
          }}
          onPointerCancel={() => pageTurnTrackerRef.current.cancel()}
          onClick={(event) => {
            if (pageTurnTrackerRef.current.consumeClick()) {
              event.preventDefault();
              return;
            }
            turnPage("next");
          }}
        />
        <ReactReader
          url={epubUrl}
          location={location ?? null}
          locationChanged={(loc: string) => { stopKidsSpeech(); setLocation(loc); }}
          tocChanged={(t: NavItem[]) => {
            setToc(t);
            tocRef.current = t;
          }}
          epubInitOptions={{ openAs: "epub" }}
          epubOptions={{ allowScriptedContent: false }}
          isRTL={isRtl}
          // react-reader's public type omits the runtime KeyboardEvent argument.
          handleKeyPress={handlePageKey as unknown as () => void}
          readerStyles={kidsReaderStyles}
          getRendition={(rendition: Rendition) => {
            renditionRef.current = rendition;
            rendition.themes.fontSize("120%");
            // Fix: iOS/iPadOS WebKit mid-line CJK punctuation.
            // iOS WebKit can fall back to fonts whose punctuation glyphs
            // sit at the vertical center of the em-box instead of on the
            // baseline.  PingFang SC is the system CJK font on Apple devices
            // and renders punctuation correctly; forcing baseline alignment
            // ensures commas and periods stay at the text baseline.
            rendition.themes.register({
              "body, p, span, div": {
                "font-family":
                  "PingFang SC, Hiragino Sans GB, Microsoft YaHei, WenQuanYi Micro Hei, sans-serif",
              },
              "body *": {
                "vertical-align": "baseline",
              },
            });
            void rendition.book.ready
              .then(() => {
                const direction = rendition.book.package?.metadata?.direction;
                const rtl = direction === "rtl";
                isRtlRef.current = rtl;
                setIsRtl(rtl);
                return rendition.book.locations.generate(256);
              })
              .then(() => rendition.reportLocation());
            rendition.hooks.content.register((contents: any) => {
              const doc = contents?.document as Document | undefined;
              if (!doc) return;
              if (doc.body?.dataset.kidsPageTurnReady === "true") return;
              if (doc.body) doc.body.dataset.kidsPageTurnReady = "true";
              let gesture: { x: number; y: number } | null = null;
              const onTouchStart = (event: TouchEvent) => {
                gesture = null;
                if (event.touches.length !== 1) return;
                const touch = event.touches[0];
                if (!shouldAllowKidsPageTurnGesture(touch.target)) return;
                gesture = { x: touch.clientX, y: touch.clientY };
              };
              const onTouchEnd = (event: TouchEvent) => {
                if (!gesture || event.changedTouches.length !== 1) return;
                const touch = event.changedTouches[0];
                const startX = gesture.x;
                const startY = gesture.y;
                gesture = null;
                const selectedText = doc.getSelection?.()?.toString() || "";
                if (selectedText.length > 2) return;
                const direction = resolveKidsPageTurnSwipe(
                  startX,
                  startY,
                  touch.clientX,
                  touch.clientY,
                );
                if (!direction) return;
                event.preventDefault();
                turnPage(direction);
              };
              doc.addEventListener("touchstart", onTouchStart, { passive: true });
              doc.addEventListener("touchend", onTouchEnd, { passive: false });
              doc.addEventListener("keyup", handlePageKey);
            });
            rendition.on("rendered", (_section: unknown, view: any) => {
              decorateEpubWords(view?.document);
            });
            rendition.on("click", (event: MouseEvent, contents: any) => {
              const target = event.target as HTMLElement | null;
              const word = target?.dataset?.kidsWord || "";
              if (!target || !word) return;
              const activeSelection = contents?.window?.getSelection?.()?.toString();
              if (activeSelection && activeSelection.length > 2) return;
              const context = target.closest("p")?.textContent || "";
              void openWordHint(word, context);
            });
            rendition.on("selected", (cfiRange: string, contents: any) => {
              const text = contents.window.getSelection().toString();
              if (text && text.length > 2) {
                currentHrefRef.current = rendition.currentLocation()?.start?.href || "";
              }
            });
            rendition.on("relocated", (location: any) => {
              const href = location?.start?.href || "";
              const cfi = location?.start?.cfi || "";
              const cfiChanged = !!cfi && cfi !== lastRelocatedCfiRef.current;
              lastRelocatedCfiRef.current = cfi;
              const previousSectionId = currentSectionIdRef.current;
              const previousSectionKind = sectionsRef.current.find(
                (section) => section.id === previousSectionId,
              )?.checkpoint_kind;
              currentHrefRef.current = href;
              currentSectionIdRef.current = resolveKidsReadingSectionId(
                href,
                tocRef.current,
                sectionsRef.current,
              );
              const currentSectionKind = sectionsRef.current.find(
                (section) => section.id === currentSectionIdRef.current,
              )?.checkpoint_kind;
              if (cfiChanged && sawInitialSectionRef.current) {
                quizLoadTokenRef.current += 1;
                learningAbortRef.current?.abort();
                learningAbortRef.current = null;
                setShowLearn(false);
                setLearningMode("quiz");
                setLearnResult(null);
                setLearnLoading(false);
                setLearnError("");
                setQuizLoading(false);
                stopKidsSpeech();
                setSpeakingId(null);
              }
              saveProgress(location?.start?.cfi || "", href);
              const isFirstMount = !sawInitialSectionRef.current;
              sawInitialSectionRef.current = true;
              if (isFirstMount) {
                return;
              }
              const hasCrossedSection =
                Boolean(previousSectionId) && previousSectionId !== currentSectionIdRef.current;
              if (!hasCrossedSection && !cfiChanged) {
                return;
              }

              const target = shouldOpenChapterCheck({
                currentSectionId: currentSectionIdRef.current,
                previousSectionId:
                  previousSectionId !== currentSectionIdRef.current ? previousSectionId : undefined,
                previousSectionKind,
                sectionKind: currentSectionKind || "none",
                atEnd: Boolean(location?.atEnd),
                percentage: location?.atEnd ? 1 : Number(location?.start?.percentage ?? 0),
                completedSectionIds: completedSectionIdsRef.current,
                shownSectionIds: shownSectionIdsRef.current,
              });
              if (target) {
                const sectionId = target === "previous" ? previousSectionId : currentSectionIdRef.current;
                shownSectionIdsRef.current = [...new Set([...shownSectionIdsRef.current, sectionId])];
                void loadLearnQuestions(sectionId);
              }
            });
          }}
        />
      </div>

      <div className="kids-reader-actions" style={{
        display: "flex",
        gap: 10,
        background: "white",
        boxShadow: "0 -2px 6px rgba(0,0,0,0.06)",
        justifyContent: "center",
        alignItems: "center",
        flexShrink: 0,
        zIndex: 10,
      }}>
        <button
          style={{ ...bottomActionBtn, background: speakingId === "read-aloud" ? "#fed7d7" : "#e9d8fd" }}
          onClick={handleReadAloud}
        >
          {speakingId === "read-aloud" ? copy.stop : copy.readAloud}
        </button>
        <button style={{ ...bottomActionBtn, background: "#fed7aa" }} onClick={handleLearnClick}>
          {copy.learn}
        </button>
        <button style={{ ...bottomActionBtn, background: "#c7d2fe" }} onClick={() => loadLearnQuestions()}>
          {copy.quiz}
        </button>
      </div>

      {translateText && (
        <div style={popupOverlay} onClick={() => setTranslateText(null)}>
          <div style={popupBox} onClick={(e) => e.stopPropagation()}>
            <div style={{ fontSize: 18, color: "#4a5568", marginBottom: 12 }}>{translateText}</div>
            <div style={{ fontSize: 22, fontWeight: 700, color: "#2d3748" }}>
              {translating ? "..." : translateResult}
            </div>
            <button style={{ ...bigBtn, marginTop: 16, background: "#e2e8f0" }} onClick={() => setTranslateText(null)}>
              {copy.close}
            </button>
          </div>
        </div>
      )}

      {wordHintState && (
        <div style={popupOverlay} onClick={closeWordHint}>
          <div style={popupBox} onClick={(e) => e.stopPropagation()}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
              <h2 style={{ fontSize: 30, fontWeight: 800, color: kidsModalHeadingColor, margin: 0 }}>
                {wordHintState.word}
              </h2>
              {wordHintData?.phonetic && (
                <span style={{ fontSize: 15, color: kidsModalTextColor }}>/{wordHintData.phonetic}/</span>
              )}
              <button
                style={{ ...speechBtn, marginLeft: "auto" }}
                title={speakingId === "hint-word" ? "Stop word" : "Read word"}
                aria-label={speakingId === "hint-word" ? "Stop word" : "Read word"}
                onClick={() => narrate("hint-word", wordHintState.word)}
              >
                {speakingId === "hint-word" ? <VolumeX size={16} /> : <Volume2 size={16} />}
              </button>
            </div>

            {wordHintBusy ? (
              <p style={{ fontSize: 18, color: kidsModalAccentColor, textAlign: "center", padding: 24 }}>
                Thinking together...
              </p>
            ) : wordHintState.phase === "picker" ? (
              <div>
                <div style={{
                  display: "inline-block",
                  padding: "3px 8px",
                  background: "#e0e7ff",
                  color: "#4338ca",
                  borderRadius: 6,
                  fontSize: 12,
                  fontWeight: 700,
                  textTransform: "uppercase",
                  letterSpacing: 0.5,
                  marginBottom: 8,
                }}>
                  Explore Words
                </div>
                <p style={{ fontSize: 18, color: kidsModalHeadingColor, margin: "0 0 14px" }}>
                  Tap any word in the story, or pick a word below to start guessing:
                </p>
                {wordHintState.choices.length > 0 ? (
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 16 }}>
                    {wordHintState.choices.map((w) => (
                      <button
                        key={w}
                        style={{
                          padding: "10px 18px",
                          borderRadius: 14,
                          border: "2px solid #667eea",
                          background: "#f0f4ff",
                          color: "#4338ca",
                          fontSize: 18,
                          fontWeight: 700,
                          cursor: "pointer",
                        }}
                        onClick={() => void openWordHint(w, "")}
                      >
                        {w}
                      </button>
                    ))}
                  </div>
                ) : (
                  <p style={{ fontSize: 16, color: kidsModalTextColor, marginBottom: 16 }}>
                    Tap any word directly in the book to explore!
                  </p>
                )}
                <button
                  style={{ ...bigBtn, width: "100%", background: "#e2e8f0" }}
                  onClick={closeWordHint}
                >
                  Keep Reading
                </button>
              </div>
            ) : !wordHintData?.available ? (
              <div style={{ textAlign: "center" }}>
                <p style={{ fontSize: 20, color: kidsModalHeadingColor }}>{wordHintMessage}</p>
                <button style={{ ...bigBtn, background: "#e2e8f0" }} onClick={closeWordHint}>
                  Keep Reading
                </button>
              </div>
            ) : wordHintState.phase === "hint" ? (
              <div>
                <div style={{
                  display: "inline-block",
                  padding: "3px 8px",
                  background: "#e0e7ff",
                  color: "#4338ca",
                  borderRadius: 6,
                  fontSize: 12,
                  fontWeight: 700,
                  textTransform: "uppercase",
                  letterSpacing: 0.5,
                  marginBottom: 8,
                }}>
                  Thinking Clue
                </div>
                <div style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
                  <p style={{ fontSize: 20, lineHeight: 1.5, color: kidsModalHeadingColor, flex: 1, margin: 0 }}>
                    {wordHintData.english_hint}
                  </p>
                  <button
                    style={speechBtn}
                    title={
                      speakingId === "hint-clue" ? "Stop thinking clue" : "Read thinking clue"
                    }
                    aria-label={
                      speakingId === "hint-clue" ? "Stop thinking clue" : "Read thinking clue"
                    }
                    onClick={() =>
                      narrate("hint-clue", wordHintData.english_hint || wordHintState.word)
                    }
                  >
                    {speakingId === "hint-clue" ? (
                      <VolumeX size={16} />
                    ) : (
                      <Volume2 size={16} />
                    )}
                  </button>
                </div>
                <button
                  style={{ ...bigBtn, width: "100%", background: "#667eea", color: "white" }}
                  onClick={() => void showWordHintChoices()}
                  disabled={wordHintBusy}
                >
                  I need choices
                </button>
              </div>
            ) : wordHintState.phase === "choices" ? (
              <div>
                  <p style={{ fontSize: 17, color: kidsModalTextColor, marginBottom: 10 }}>
                  Guess first. You can listen and think.
                </p>
                <div style={{ display: "grid", gap: 8 }}>
                  {wordHintState.choices.map((choice) => (
                    <div key={choice} style={{ display: "flex", alignItems: "stretch", gap: 6 }}>
                      <button
                        type="button"
                        style={{
                          flex: 1,
                          padding: "12px 14px",
                          borderRadius: 12,
                          border: "2px solid #cbd5e1",
                          background: "#ffffff",
                          color: "#0f172a",
                          fontSize: 16,
                          fontWeight: 600,
                          textAlign: "left",
                          cursor: "pointer",
                          boxShadow: "0 1px 3px rgba(0, 0, 0, 0.05)",
                        }}
                        onClick={() => void checkWordHintChoice(choice)}
                      >
                        {choice}
                      </button>
                      <button
                        style={speechBtn}
                        title={`Read ${choice}`}
                        aria-label={`Read ${choice}`}
                        onClick={() => narrate(`hint-choice-${choice}`, choice)}
                      >
                        {speakingId === `hint-choice-${choice}` ? (
                          <VolumeX size={15} />
                        ) : (
                          <Volume2 size={15} />
                        )}
                      </button>
                    </div>
                  ))}
                </div>
                {wordHintState.feedback && (
                  <p style={{ fontSize: 19, fontWeight: 800, color: kidsModalHeadingColor, marginTop: 12 }}>
                    {wordHintState.feedback}
                  </p>
                )}
                {wordHintState.wrongAttempts >= 1 && (
                  <button
                    style={{ ...bigBtn, width: "100%", marginTop: 12, background: "#e2e8f0" }}
                    onClick={() => void revealWordHint()}
                    disabled={wordHintBusy}
                  >
                    Show me gently
                  </button>
                )}
              </div>
            ) : wordHintState.phase === "correct" ? (
              <div style={{ textAlign: "center" }}>
                <div style={{ fontSize: 48 }}>🌟</div>
                <p style={{ fontSize: 20, color: kidsModalHeadingColor }}>{wordHintState.feedback}</p>
                {wordHintState.correctChoice && (
                  <p style={{ fontSize: 16, color: kidsModalTextColor, margin: "0 0 16px" }}>
                    &ldquo;{wordHintState.word}&rdquo; means {wordHintState.correctChoice}.
                  </p>
                )}
                <button
                  style={{ ...bigBtn, background: "#667eea", color: "white" }}
                  onClick={closeWordHint}
                >
                  Keep Reading
                </button>
              </div>
            ) : (
              <div>
                <p style={{ fontSize: 18, fontWeight: 700, color: kidsModalHeadingColor, margin: "0 0 6px", lineHeight: 1.4 }}>
                  {wordHintState.correctChoice}
                </p>
                {wordHintState.chinese && (
                  <p style={{ fontSize: 20, fontWeight: 800, color: kidsModalHeadingColor, margin: "0 0 10px", lineHeight: 1.4 }}>
                    {wordHintState.chinese.replace(/\\n|\n/g, " ")}
                  </p>
                )}
                {wordHintState.explanation && (
                  <div style={{ padding: "10px 14px", background: "#f8fafc", borderRadius: 12, border: "1px solid #e2e8f0", marginBottom: 16 }}>
                    <p style={{ fontSize: 15, color: kidsModalTextColor, margin: 0, lineHeight: 1.5 }}>
                      {wordHintState.explanation}
                    </p>
                  </div>
                )}
                <button
                  style={{ ...bigBtn, width: "100%", background: "#667eea", color: "white" }}
                  onClick={closeWordHint}
                >
                  Got it
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {showLearn && (
        <div style={popupOverlay} onClick={closeLearnQuestions}>
          <div style={popupBox} onClick={(e) => e.stopPropagation()}>
            {learningMode === "learn" ? (
              <>
                <GuidedLearnModal
                  result={learnResult}
                  loading={learnLoading}
                  error={learnError}
                  copy={copy}
                  speakingId={speakingId}
                  onSpeak={speakQuizText}
                  onClose={closeLearnQuestions}
                  onRetry={loadConceptLearn}
                />
                <button
                  style={{ ...bigBtn, width: "100%", background: "#e2e8f0" }}
                  onClick={closeLearnQuestions}
                >
                  {copy.close}
                </button>
              </>
            ) : grade && grade.score === grade.total ? (
              <div style={{ textAlign: "center" }}>
                <div style={{ fontSize: 64 }}>
                  {grade.score === grade.total ? copy.great : grade.score > 0 ? copy.keepThinking : copy.tryAgainHeading}
                </div>
                <div style={{ fontSize: 28, fontWeight: 800, color: kidsModalHeadingColor, marginTop: 8 }}>
                  {copy.correctCount.replace("{score}", String(grade.score)).replace("{total}", String(grade.total))}
                </div>
                <div style={{ marginTop: 12 }}>
                  <RewardSnapshotView reward={grade.reward} />
                </div>
                {grade.per_question.map((q, i) => (
                  <div key={i} style={{
                    marginTop: 12,
                    padding: 12,
                    borderRadius: 12,
                    background: q.correct ? "#f0fff4" : "#fff5f5",
                    textAlign: "left",
                  }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <span style={{ fontSize: 20 }}>{q.correct ? copy.correct : copy.thinkAgain}</span>
                      <button
                        style={speechBtn}
                        title={speakingId === `answer-${i}` ? copy.stopAnswer : copy.readAnswer}
                        aria-label={speakingId === `answer-${i}` ? copy.stopAnswer : copy.readAnswer}
                        onClick={() => speakQuizText(`answer-${i}`, `${q.correct ? copy.correct : copy.thinkAgain}. ${q.explanation}`)}
                      >
                        {speakingId === `answer-${i}` ? <VolumeX size={15} /> : <Volume2 size={15} />}
                      </button>
                    </div>
                    <div style={{ fontSize: 14, color: kidsModalTextColor, marginTop: 6 }}>{q.explanation}</div>
                  </div>
                ))}
                <button
                  style={{ ...bigBtn, marginTop: 16, background: "#667eea", color: "white" }}
                  onClick={closeLearnQuestions}
                >
                  {copy.close}
                </button>
              </div>
            ) : quizLoading ? (
              <div style={{ textAlign: "center", padding: 40 }}>
                <div style={{ fontSize: 48 }}>?</div>
                <p style={{ fontSize: 18, color: kidsModalAccentColor }}>{copy.quizLoading}</p>
                <button style={{ ...bigBtn, marginTop: 16, background: "#e2e8f0" }} onClick={closeLearnQuestions}>
                  {copy.close}
                </button>
              </div>
            ) : questions.length === 0 ? (
              <div style={{ textAlign: "center", padding: 40 }}>
                <p style={{ fontSize: 18, color: "#e53e3e" }}>{copy.quizEmpty}</p>
                <button style={{ ...bigBtn, marginTop: 16, background: "#e2e8f0" }} onClick={closeLearnQuestions}>
                  {copy.close}
                </button>
              </div>
            ) : (
              <div>
                <h2 style={{ fontSize: 24, fontWeight: 800, color: kidsModalHeadingColor, marginBottom: 16 }}>
                  {copy.lookAndThink}
                </h2>
                <p style={{ fontSize: 15, color: kidsModalTextColor, marginBottom: 16 }}>
                  {copy.quizIntro}
                </p>
                {questions.map((q, qi) => (
                  <div key={qi} style={{ marginBottom: 20 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
                      <div style={{ fontSize: 13, fontWeight: 700, color: kidsModalTextColor }}>
                        {copy.question} {qi + 1}
                      </div>
                      <button
                        style={speechBtn}
                        title={speakingId === `question-${qi}` ? copy.stopQuestion : copy.readQuestion}
                        aria-label={speakingId === `question-${qi}` ? copy.stopQuestion : copy.readQuestion}
                        onClick={() => speakQuizText(`question-${qi}`, q.question)}
                      >
                        {speakingId === `question-${qi}` ? <VolumeX size={15} /> : <Volume2 size={15} />}
                      </button>
                    </div>
                    <div style={{ fontSize: 18, fontWeight: 600, color: kidsModalHeadingColor, marginBottom: 8, textAlign: "left" }}>
                      {q.question}
                    </div>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                      {q.choices.map((c, ci) => {
                        const feedback = grade?.per_question?.[qi];
                        const isCorrectChoice = !!feedback?.correct && answers[qi] === ci;
                        return (
                          <div key={ci} style={{ display: "flex", alignItems: "stretch", gap: 6 }}>
                            <button
                              type="button"
                              onClick={() => setAnswers({ ...answers, [qi]: ci })}
                              disabled={isCorrectChoice}
                              style={{
                                flex: 1,
                                padding: "12px 14px",
                                borderRadius: 12,
                                border: answers[qi] === ci ? "3px solid #667eea" : "2px solid #cbd5e1",
                                background: answers[qi] === ci ? "#ede9fe" : "#ffffff",
                                color: answers[qi] === ci ? "#3730a3" : "#0f172a",
                                fontSize: 16,
                                fontWeight: answers[qi] === ci ? 700 : 600,
                                cursor: isCorrectChoice ? "default" : "pointer",
                                textAlign: "left",
                                boxShadow: answers[qi] === ci ? "0 2px 8px rgba(102, 126, 234, 0.2)" : "0 1px 3px rgba(0, 0, 0, 0.05)",
                              }}
                            >
                              {c}
                            </button>
                            <button
                              style={speechBtn}
                              title={speakingId === `choice-${qi}-${ci}` ? `${copy.stopChoice}: ${c}` : `${copy.readChoice}: ${c}`}
                              aria-label={speakingId === `choice-${qi}-${ci}` ? `${copy.stopChoice}: ${c}` : `${copy.readChoice}: ${c}`}
                              onClick={() => speakQuizText(`choice-${qi}-${ci}`, c)}
                            >
                              {speakingId === `choice-${qi}-${ci}` ? (
                                <VolumeX size={15} />
                              ) : (
                                <Volume2 size={15} />
                              )}
                            </button>
                          </div>
                        );
                      })}
                    </div>
                    {grade?.per_question?.[qi] && !grade.per_question[qi].correct && (
                      <div style={{ marginTop: 8, padding: 10, borderRadius: 12, background: "#fff5f5", color: "#c53030", fontWeight: 700 }}>
                        {copy.thinkAgain}
                      </div>
                    )}
                  </div>
                ))}
                <button
                  style={{ ...bigBtn, width: "100%", background: "#667eea", color: "white" }}
                  onClick={submitLearnAnswers}
                  disabled={submitting || questions.some((_, i) => answers[i] === undefined)}
                >
                  {submitting ? copy.checking : grade && grade.score < grade.total ? copy.tryAgain : copy.submit}
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

const toolbarBtn: React.CSSProperties = {
  background: "#f7fafc",
  border: "none",
  borderRadius: 10,
  padding: "8px 14px",
  fontSize: 16,
  fontWeight: 600,
  cursor: "pointer",
  color: "#4a5568",
};

const kidsModalHeadingColor = "#111827";
const kidsModalTextColor = "#1e293b";
const kidsModalAccentColor = "#4338ca";

const bigBtn: React.CSSProperties = {
  border: "none",
  borderRadius: 16,
  padding: "14px 28px",
  fontSize: 18,
  fontWeight: 700,
  cursor: "pointer",
  color: "#2d3748",
};

const bottomActionBtn: React.CSSProperties = {
  border: "none",
  borderRadius: 16,
  padding: "12px 18px",
  fontSize: 17,
  fontWeight: 700,
  cursor: "pointer",
  color: "#2d3748",
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  minWidth: 100,
  flex: "1 1 auto",
  maxWidth: 160,
};

const secondaryToolBtn: React.CSSProperties = {
  ...toolbarBtn,
  width: 36,
  height: 36,
  padding: 0,
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  borderRadius: 12,
};

const pageTurnHotzone: React.CSSProperties = {
  position: "absolute",
  top: 56,
  bottom: 16,
  left: 0,
  width: "min(18vw, 96px)",
  zIndex: 30,
  border: "none",
  padding: 0,
  background: "transparent",
  cursor: "pointer",
  touchAction: "pan-y",
  WebkitTapHighlightColor: "transparent",
};

const speechBtn: React.CSSProperties = {
  width: 38,
  height: 38,
  flexShrink: 0,
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  border: "2px solid #e2e8f0",
  borderRadius: 12,
  background: "#f7fafc",
  color: kidsModalAccentColor,
  cursor: "pointer",
};

const popupOverlay: React.CSSProperties = {
  position: "fixed",
  top: 0, left: 0, right: 0, bottom: 0,
  background: "rgba(0,0,0,0.4)",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  zIndex: 100,
};

const popupBox: React.CSSProperties = {
  background: "white",
  borderRadius: 24,
  padding: 24,
  maxWidth: 500,
  width: "90%",
  maxHeight: "88vh",
  overflowY: "auto",
  boxSizing: "border-box",
  WebkitOverflowScrolling: "touch",
  boxShadow: "0 8px 32px rgba(0,0,0,0.2)",
};
