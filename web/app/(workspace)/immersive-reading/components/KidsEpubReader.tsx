"use client";

import dynamic from "next/dynamic";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  ArrowLeft,
  Award,
  BookOpen,
  ChevronLeft,
  ChevronRight,
  Languages,
  List,
  Loader2,
  PartyPopper,
  RotateCcw,
  Star,
  Volume2,
  VolumeX,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import type { Rendition, NavItem } from "epubjs";
import {
  immersiveReadingApi,
  type KidsQuizResult,
  type ReadingDocument,
  type ReadingSection,
} from "@/lib/immersive-reading-api";

const ReactReader = dynamic(
  () => import("react-reader").then((m) => m.ReactReader),
  { ssr: false, loading: () => null },
);

type Panel = "toc" | "quiz" | "none";

interface Props {
  document: ReadingDocument;
  onBack: () => void;
  onError: (message: string) => void;
}

const EPUB_URL = (documentId: string) =>
  `/api/v1/immersive-reading/documents/${encodeURIComponent(documentId)}/original`;

const QUIZ_KIND_LABEL: Record<string, string> = {
  comprehension: "\U0001f4d6",  // open book
  sight_word: "\u2b50",          // star
  sequence: "\u27a1\ufe0f",     // arrow
};

export default function KidsEpubReader({ document: doc, onBack, onError }: Props) {
  const { t } = useTranslation();
  const [location, setLocation] = useState<string | null>(null);
  const [toc, setToc] = useState<NavItem[]>([]);
  const [panel, setPanel] = useState<Panel>("none");
  const [currentHref, setCurrentHref] = useState<string>("");
  const renditionRef = useRef<Rendition | null>(null);

  // TTS state
  const [speaking, setSpeaking] = useState(false);
  const utteranceRef = useRef<SpeechSynthesisUtterance | null>(null);

  // Translation state
  const [translateResult, setTranslateResult] = useState<{ text: string; result: string } | null>(null);
  const [translating, setTranslating] = useState(false);

  // Quiz state
  const [quiz, setQuiz] = useState<KidsQuizResult | null>(null);
  const [quizLoading, setQuizLoading] = useState(false);
  const [quizAnswers, setQuizAnswers] = useState<Record<string, number>>({});
  const [quizSubmitted, setQuizSubmitted] = useState(false);

  // Encouragement toast
  const [encourage, setEncourage] = useState<string | null>(null);

  const sections = doc.sections;

  const currentSection = useMemo<ReadingSection | null>(() => {
    if (!currentHref || sections.length === 0) return null;
    const idx = toc.findIndex((item) => item.href === currentHref);
    if (idx >= 0 && idx < sections.length) return sections[idx];
    return sections[0] ?? null;
  }, [currentHref, toc, sections]);

  useEffect(() => {
    void immersiveReadingApi.setExperienceMode(doc.id, "kids").catch(() => undefined);
  }, [doc.id]);

  // ── TTS: tap paragraph to read aloud ─────────────────────────────────

  const stopSpeaking = useCallback(() => {
    window.speechSynthesis?.cancel();
    setSpeaking(false);
    utteranceRef.current = null;
  }, []);

  const speakText = useCallback((text: string) => {
    if (!text.trim()) return;
    window.speechSynthesis?.cancel();
    setSpeaking(true);

    const utter = new SpeechSynthesisUtterance(text);
    utter.lang = "en-US";
    utter.rate = 0.8;
    utter.onend = () => setSpeaking(false);
    utter.onerror = () => setSpeaking(false);
    utteranceRef.current = utter;
    window.speechSynthesis?.speak(utter);
  }, []);

  const handleLocationChange = useCallback(
    (locStr: string) => {
      setLocation(locStr);
      void immersiveReadingApi
        .kidsProgress(doc.id, currentSection?.id ?? "section_0001", {
          scroll_percent: 0,
          epub_cfi: locStr,
          section_href: currentHref,
        })
        .catch(() => undefined);
    },
    [doc.id, currentSection, currentHref],
  );

  const handleTocChange = useCallback((items: NavItem[]) => {
    setToc(items);
  }, []);

  // ── Core interaction: click paragraph = read it, long-click = translate ──

  const lastClickTime = useRef(0);
  const pendingTranslate = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleGetRendition = useCallback((rendition: Rendition) => {
    renditionRef.current = rendition;
    rendition.themes.register("kids", {
      p: {
        fontSize: "160%",
        lineHeight: "2.4",
        fontFamily: "'Comic Sans MS', 'Marker Felt', 'Chalkboard SE', sans-serif",
        margin: "1em 0",
        cursor: "pointer",
      },
      h1: { fontSize: "200%", textAlign: "center", fontFamily: "'Comic Sans MS', sans-serif" },
      h2: { fontSize: "180%", textAlign: "center", fontFamily: "'Comic Sans MS', sans-serif" },
      img: { maxWidth: "100%", height: "auto", display: "block", margin: "1em auto" },
      body: { padding: "0 1.5em", color: "#2d2d2d" },
    });
    rendition.themes.select("kids");
    rendition.themes.fontSize("160%");

    rendition.on("relocated", (loc: { start: { href: string } }) => {
      const href = loc?.start?.href ?? "";
      setCurrentHref(href);
    });

    // Click paragraph = read aloud; double click = translate
    rendition.on("click", (event: MouseEvent, contents: { window: Window }) => {
      const target = event.target as HTMLElement;
      // Walk up to find the nearest paragraph or heading
      let el: HTMLElement | null = target;
      while (el && el.tagName !== "P" && el.tagName !== "H1" && el.tagName !== "H2" && el.tagName !== "H3" && el.parentElement) {
        el = el.parentElement;
      }
      if (!el) return;

      const text = el.textContent?.trim() ?? "";
      if (!text) return;

      const now = Date.now();
      const isDouble = now - lastClickTime.current < 400;
      lastClickTime.current = now;

      if (pendingTranslate.current) {
        clearTimeout(pendingTranslate.current);
        pendingTranslate.current = null;
      }

      if (isDouble) {
        // Double tap = translate
        stopSpeaking();
        void handleTranslate(text);
      } else {
        // Single tap = read (with small delay to detect double-tap)
        pendingTranslate.current = setTimeout(() => {
          speakText(text);
        }, 250);
      }
    });
  }, [speakText, stopSpeaking]);

  const handleTranslate = useCallback(
    async (text: string) => {
      setTranslating(true);
      setTranslateResult({ text, result: "" });
      try {
        const { translation } = await immersiveReadingApi.translate(text, "Chinese");
        setTranslateResult({ text, result: translation });
      } catch {
        onError(t("Translation failed."));
        setTranslateResult(null);
      } finally {
        setTranslating(false);
      }
    },
    [onError, t],
  );

  useEffect(() => {
    return () => {
      window.speechSynthesis?.cancel();
      if (pendingTranslate.current) clearTimeout(pendingTranslate.current);
    };
  }, []);

  // ── Quiz ─────────────────────────────────────────────────────────────

  const loadQuiz = useCallback(
    async (forceRefresh = false) => {
      if (!currentSection) return;
      setQuizLoading(true);
      setQuizSubmitted(false);
      setQuizAnswers({});
      try {
        const result = await immersiveReadingApi.kidsQuiz(doc.id, currentSection.id, forceRefresh);
        setQuiz(result);
        setPanel("quiz");
      } catch {
        onError(t("Quiz generation failed."));
      } finally {
        setQuizLoading(false);
      }
    },
    [currentSection, doc.id, onError, t],
  );

  const quizScore = useMemo(() => {
    if (!quiz || !quizSubmitted) return null;
    let correct = 0;
    for (const q of quiz.questions) {
      if (quizAnswers[q.id] === q.answer_index) correct++;
    }
    return { correct, total: quiz.questions.length };
  }, [quiz, quizAnswers, quizSubmitted]);

  // Show encouragement on quiz submit
  useEffect(() => {
    if (quizSubmitted && quizScore) {
      const msgs = quizScore.correct === quizScore.total
        ? ["\u2b50 Perfect! \u2b50", "\u2b50 Amazing! \u2b50", "\u2b50 You did it! \u2b50"]
        : quizScore.correct >= 2
          ? ["\u2b50 Great job! \u2b50", "\u2b50 Almost there! \u2b50"]
          : ["\u2b50 Keep trying! \u2b50"];
      setEncourage(msgs[Math.floor(Math.random() * msgs.length)]);
      const timer = setTimeout(() => setEncourage(null), 3000);
      return () => clearTimeout(timer);
    }
  }, [quizSubmitted, quizScore]);

  const handleNextPage = useCallback(() => {
    renditionRef.current?.next();
  }, []);
  const handlePrevPage = useCallback(() => {
    renditionRef.current?.prev();
  }, []);

  // ── Render ───────────────────────────────────────────────────────────

  return (
    <div className="flex h-full flex-col" style={{ background: "#faf9f6" }}>
      {/* Big colorful toolbar */}
      <header className="flex items-center justify-between gap-3 bg-gradient-to-r from-sky-400 to-indigo-400 px-4 py-3 shadow-md">
        <button
          type="button"
          onClick={onBack}
          className="flex h-12 w-12 items-center justify-center rounded-2xl bg-white/25 text-white transition hover:bg-white/40"
          aria-label={t("Back")}
        >
          <ArrowLeft size={26} />
        </button>

        <h1 className="flex-1 truncate text-center text-lg font-bold text-white drop-shadow-sm">
          {doc.title}
        </h1>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setPanel(panel === "toc" ? "none" : "toc")}
            className={`flex h-12 w-12 items-center justify-center rounded-2xl transition ${panel === "toc" ? "bg-white text-indigo-500" : "bg-white/25 text-white hover:bg-white/40"}`}
            aria-label={t("Stories")}
          >
            <List size={24} />
          </button>
          <button
            type="button"
            onClick={speaking ? stopSpeaking : undefined}
            className={`flex h-12 w-12 items-center justify-center rounded-2xl transition ${speaking ? "bg-amber-400 text-white animate-pulse" : "bg-white/25 text-white hover:bg-white/40"}`}
            aria-label={speaking ? t("Stop") : t("Reading")}
          >
            {speaking ? <VolumeX size={24} /> : <Volume2 size={24} />}
          </button>
          <button
            type="button"
            onClick={() => loadQuiz(false)}
            disabled={quizLoading || !currentSection}
            className="flex h-12 w-12 items-center justify-center rounded-2xl bg-white/25 text-white transition hover:bg-white/40 disabled:opacity-40"
            aria-label={t("Quiz")}
          >
            {quizLoading ? <Loader2 size={24} className="animate-spin" /> : <Award size={24} />}
          </button>
        </div>
      </header>

      {/* Hint bar */}
      <div className="bg-amber-50 px-4 py-2 text-center text-sm text-amber-700">
        {speaking ? "\u266a Listening... tap \u23f9 to stop" : "Tap a sentence to hear it \u266a  \u00b7  Double-tap to translate"}
      </div>

      {/* EPUB rendering area */}
      <div className="relative min-h-0 flex-1">
        <ReactReader
          url={EPUB_URL(doc.id)}
          location={location}
          locationChanged={handleLocationChange}
          tocChanged={handleTocChange}
          getRendition={handleGetRendition}
          showToc={false}
          epubInitOptions={{ openAs: "epub" }}
          epubOptions={{
            allowPopups: false,
            allowScriptedContent: false,
            spread: "none",
            flow: "scrolled-doc",
          }}
        />

        {/* Large page-turn buttons */}
        <button
          type="button"
          onClick={handlePrevPage}
          className="absolute bottom-6 left-3 z-10 flex h-16 w-16 items-center justify-center rounded-full bg-indigo-500 text-white shadow-xl transition hover:scale-110 active:scale-95"
          aria-label={t("Previous")}
        >
          <ChevronLeft size={32} />
        </button>
        <button
          type="button"
          onClick={handleNextPage}
          className="absolute bottom-6 right-3 z-10 flex h-16 w-16 items-center justify-center rounded-full bg-sky-500 text-white shadow-xl transition hover:scale-110 active:scale-95"
          aria-label={t("Next")}
        >
          <ChevronRight size={32} />
        </button>
      </div>

      {/* TOC drawer */}
      {panel === "toc" && (
        <div className="fixed inset-0 z-40 flex">
          <div className="w-80 max-w-[85vw] bg-white shadow-2xl">
            <header className="flex items-center justify-between bg-sky-100 px-4 py-3">
              <span className="flex items-center gap-2 font-bold text-sky-700">
                <BookOpen size={20} /> {t("Pick a Story")}
              </span>
              <button type="button" onClick={() => setPanel("none")} className="rounded-xl p-2 hover:bg-sky-200">
                <X size={20} />
              </button>
            </header>
            <div className="min-h-0 flex-1 overflow-y-auto p-3">
              {toc.map((item, i) => (
                <button
                  key={item.href}
                  type="button"
                  onClick={() => {
                    renditionRef.current?.display(item.href);
                    setPanel("none");
                  }}
                  className={`mb-2 block w-full rounded-2xl px-4 py-3 text-left text-base font-medium transition ${currentHref === item.href ? "bg-sky-500 text-white" : "bg-sky-50 text-sky-800 hover:bg-sky-100"}`}
                >
                  <span className="mr-2 text-sm opacity-60">{i + 1}</span>
                  {item.label.trim() || `${t("Story")} ${i + 1}`}
                </button>
              ))}
            </div>
          </div>
          <div className="flex-1 bg-black/30" onClick={() => setPanel("none")} />
        </div>
      )}

      {/* Quiz panel - full overlay */}
      {panel === "quiz" && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4">
          <div className="flex max-h-[90vh] w-full max-w-lg flex-col rounded-3xl bg-white shadow-2xl">
            <header className="flex items-center justify-between bg-gradient-to-r from-purple-400 to-pink-400 rounded-t-3xl px-5 py-4">
              <span className="flex items-center gap-2 text-lg font-bold text-white">
                <Award size={22} /> {t("Story Quiz")}
              </span>
              <button type="button" onClick={() => setPanel("none")} className="rounded-xl bg-white/25 p-2 text-white hover:bg-white/40">
                <X size={20} />
              </button>
            </header>

            <div className="min-h-0 flex-1 overflow-y-auto p-5">
              {!quiz || quizLoading ? (
                <div className="flex flex-col items-center justify-center py-12 gap-3">
                  <Loader2 size={32} className="animate-spin text-purple-400" />
                  <p className="text-sm text-gray-500">{t("Making your quiz...")}</p>
                </div>
              ) : quiz.questions.length === 0 ? (
                <p className="py-8 text-center text-gray-500">{t("No quiz for this story.")}</p>
              ) : (
                <div className="space-y-5">
                  {quiz.questions.map((q, qi) => (
                    <div key={q.id} className="rounded-2xl border-2 border-gray-100 bg-gray-50/50 p-4">
                      <div className="mb-2 flex items-center gap-2">
                        <span className="flex h-8 w-8 items-center justify-center rounded-full bg-purple-500 text-sm font-bold text-white">{qi + 1}</span>
                        <span className="text-lg">{QUIZ_KIND_LABEL[q.kind] || "\u2753"}</span>
                      </div>
                      <p className="mb-3 text-base font-semibold text-gray-800">{q.question}</p>
                      <div className="space-y-2">
                        {q.choices.map((choice, ci) => {
                          const selected = quizAnswers[q.id] === ci;
                          const correct = ci === q.answer_index;
                          const showResult = quizSubmitted;
                          return (
                            <button
                              key={ci}
                              type="button"
                              disabled={quizSubmitted}
                              onClick={() => setQuizAnswers((prev) => ({ ...prev, [q.id]: ci }))}
                              className={`flex w-full items-center gap-3 rounded-xl border-2 px-4 py-3 text-left text-base font-medium transition ${
                                showResult && correct
                                  ? "border-green-400 bg-green-50"
                                  : showResult && selected && !correct
                                    ? "border-red-400 bg-red-50"
                                    : selected
                                      ? "border-purple-400 bg-purple-50"
                                      : "border-gray-200 bg-white hover:border-purple-200"
                              }`}
                            >
                              <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-sm font-bold ${
                                showResult && correct ? "bg-green-500 text-white" : showResult && selected && !correct ? "bg-red-500 text-white" : selected ? "bg-purple-500 text-white" : "bg-gray-200 text-gray-600"
                              }`}>
                                {showResult && correct ? "\u2714" : showResult && selected && !correct ? "\u2718" : String.fromCharCode(65 + ci)}
                              </span>
                              {choice}
                            </button>
                          );
                        })}
                      </div>
                      {quizSubmitted && q.explanation && (
                        <p className="mt-2 rounded-xl bg-yellow-50 px-3 py-2 text-sm leading-6 text-yellow-800">\U0001f4a1 {q.explanation}</p>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>

            {quiz && !quizLoading && (
              <footer className="border-t border-gray-100 p-5">
                {quizSubmitted && quizScore ? (
                  <div className="flex flex-col items-center gap-3">
                    <div className={`flex items-center gap-3 rounded-2xl px-6 py-3 ${quizScore.correct === quizScore.total ? "bg-green-100" : "bg-amber-100"}`}>
                      <PartyPopper size={28} className={quizScore.correct === quizScore.total ? "text-green-600" : "text-amber-600"} />
                      <div>
                        <div className="text-2xl font-bold text-gray-800">
                          {quizScore.correct}/{quizScore.total}
                        </div>
                        <div className="flex gap-1">
                          {Array.from({ length: quizScore.total }).map((_, i) => (
                            <Star key={i} size={18} className={i < quizScore.correct ? "fill-yellow-400 text-yellow-400" : "text-gray-300"} />
                          ))}
                        </div>
                      </div>
                    </div>
                    <div className="flex gap-2">
                      <button
                        type="button"
                        onClick={() => loadQuiz(true)}
                        className="inline-flex items-center gap-2 rounded-2xl bg-gray-100 px-5 py-2.5 text-sm font-bold text-gray-700 hover:bg-gray-200"
                      >
                        <RotateCcw size={16} /> {t("Try Again")}
                      </button>
                      <button
                        type="button"
                        onClick={() => setPanel("none")}
                        className="inline-flex items-center gap-2 rounded-2xl bg-sky-500 px-5 py-2.5 text-sm font-bold text-white hover:bg-sky-600"
                      >
                        {t("Keep Reading")}
                      </button>
                    </div>
                  </div>
                ) : (
                  <button
                    type="button"
                    disabled={Object.keys(quizAnswers).length < quiz.questions.length}
                    onClick={() => setQuizSubmitted(true)}
                    className="w-full rounded-2xl bg-gradient-to-r from-purple-500 to-pink-500 py-3.5 text-lg font-bold text-white shadow-lg transition disabled:opacity-40 enabled:hover:scale-[1.02]"
                  >
                    {t("Check My Answers!")}
                  </button>
                )}
              </footer>
            )}
          </div>
        </div>
      )}

      {/* Translation popup - small, non-blocking */}
      {translateResult && (
        <div
          className="fixed inset-0 z-50 flex items-end justify-center bg-black/30 p-4 sm:items-center"
          onMouseDown={(e) => { if (e.currentTarget === e.target) setTranslateResult(null); }}
        >
          <div className="w-full max-w-sm rounded-2xl bg-white p-5 shadow-2xl">
            <div className="mb-3 flex items-center justify-between">
              <span className="flex items-center gap-2 font-bold text-indigo-600">
                <Languages size={18} /> \u4e2d\u6587
              </span>
              <button type="button" onClick={() => setTranslateResult(null)} className="rounded-lg p-1.5 hover:bg-gray-100">
                <X size={18} />
              </button>
            </div>
            {translating ? (
              <div className="flex items-center gap-2 py-4 text-gray-400">
                <Loader2 size={18} className="animate-spin" /> {t("Translating...")}
              </div>
            ) : (
              <p className="text-lg leading-7 text-gray-800">{translateResult.result}</p>
            )}
            {!translating && (
              <p className="mt-3 border-t border-gray-100 pt-2 text-sm text-gray-400">{translateResult.text}</p>
            )}
          </div>
        </div>
      )}

      {/* Encouragement toast */}
      {encourage && (
        <div className="fixed left-1/2 top-1/3 z-[60] -translate-x-1/2 rounded-3xl bg-gradient-to-r from-yellow-400 to-orange-400 px-8 py-4 text-2xl font-bold text-white shadow-2xl">
          {encourage}
        </div>
      )}
    </div>
  );
}
