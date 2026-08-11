"use client";

import dynamic from "next/dynamic";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
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
  RotateCcw,
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
type SpeechState = { speaking: boolean; sentenceIndex: number };

interface Props {
  document: ReadingDocument;
  onBack: () => void;
  onError: (message: string) => void;
}

const EPUB_URL = (documentId: string) =>
  `/api/v1/immersive-reading/documents/${encodeURIComponent(documentId)}/original`;

export default function KidsEpubReader({ document: doc, onBack, onError }: Props) {
  const { t } = useTranslation();
  const [location, setLocation] = useState<string | null>(null);
  const [toc, setToc] = useState<NavItem[]>([]);
  const [panel, setPanel] = useState<Panel>("none");
  const [currentHref, setCurrentHref] = useState<string>("");
  const renditionRef = useRef<Rendition | null>(null);

  // TTS state
  const [speaking, setSpeaking] = useState(false);
  const sentencesRef = useRef<string[]>([]);
  const sentenceIdxRef = useRef(0);
  const [highlightedSentence, setHighlightedSentence] = useState(-1);

  // Translation state
  const [translateResult, setTranslateResult] = useState<{ text: string; result: string } | null>(null);
  const [translating, setTranslating] = useState(false);

  // Quiz state
  const [quiz, setQuiz] = useState<KidsQuizResult | null>(null);
  const [quizLoading, setQuizLoading] = useState(false);
  const [quizAnswers, setQuizAnswers] = useState<Record<string, number>>({});
  const [quizSubmitted, setQuizSubmitted] = useState(false);

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

  const handleGetRendition = useCallback((rendition: Rendition) => {
    renditionRef.current = rendition;
    rendition.themes.register("kids", {
      p: { fontSize: "130%", lineHeight: "2.0", fontFamily: "'Comic Sans MS', 'Marker Felt', sans-serif", margin: "0.8em 0" },
      h1: { fontSize: "180%", textAlign: "center" },
      h2: { fontSize: "160%", textAlign: "center" },
      img: { maxWidth: "100%", height: "auto" },
      body: { padding: "0 1em", color: "#333" },
    });
    rendition.themes.select("kids");
    rendition.themes.fontSize("130%");

    // Track which chapter is visible
    rendition.on("relocated", (location: { start: { href: string } }) => {
      const href = location?.start?.href ?? "";
      setCurrentHref(href);
    });

    // Selection for translation
    rendition.on("selected", (cfiRange: string, contents: { window: { getSelection: () => Selection | null } }) => {
      const selection = contents.window.getSelection();
      const selectedText = selection?.toString().trim() ?? "";
      if (selectedText.length > 0 && selectedText.length < 500) {
        void handleTranslate(selectedText);
      }
    });
  }, []);

  const handleTranslate = useCallback(
    async (text: string) => {
      setTranslating(true);
      try {
        const { translation } = await immersiveReadingApi.translate(text, "Chinese");
        setTranslateResult({ text, result: translation });
      } catch {
        onError(t("Translation failed. Please try again."));
      } finally {
        setTranslating(false);
      }
    },
    [onError, t],
  );

  // ── TTS ──────────────────────────────────────────────────────────────────

  const stopSpeaking = useCallback(() => {
    window.speechSynthesis?.cancel();
    setSpeaking(false);
    setHighlightedSentence(-1);
    renditionRef.current?.annotations.remove("tts-highlight", "highlight");
  }, []);

  const speakFromSelection = useCallback(() => {
    if (!renditionRef.current) return;
    const rendition = renditionRef.current;
    const sel = (rendition.getContents() as unknown as Array<{ window: { getSelection: () => Selection | null } }>)?.[0]?.window?.getSelection?.();
    const selectedText = sel?.toString().trim();
    if (!selectedText) {
      onError(t("Tap a sentence first, then press the speaker button."));
      return;
    }
    stopSpeaking();

    // Split into sentences for sequential highlighting
    const sentences = selectedText.match(/[^.!?]+[.!?]*/g)?.map((s: string) => s.trim()).filter(Boolean) ?? [selectedText];
    sentencesRef.current = sentences;
    sentenceIdxRef.current = 0;
    setSpeaking(true);

    const speakNext = () => {
      if (sentenceIdxRef.current >= sentences.length) {
        setSpeaking(false);
        setHighlightedSentence(-1);
        return;
      }
      const idx = sentenceIdxRef.current;
      setHighlightedSentence(idx);
      const utter = new SpeechSynthesisUtterance(sentences[idx]);
      utter.lang = "en-US";
      utter.rate = 0.85;
      utter.onend = () => {
        sentenceIdxRef.current++;
        speakNext();
      };
      utter.onerror = () => {
        setSpeaking(false);
        setHighlightedSentence(-1);
      };
      window.speechSynthesis?.speak(utter);
    };
    speakNext();
  }, [onError, stopSpeaking, t]);

  useEffect(() => {
    return () => {
      window.speechSynthesis?.cancel();
    };
  }, []);

  // ── Quiz ─────────────────────────────────────────────────────────────────

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
        onError(t("Quiz generation failed. Please try again later."));
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

  const handleNextPage = useCallback(() => {
    renditionRef.current?.next();
  }, []);
  const handlePrevPage = useCallback(() => {
    renditionRef.current?.prev();
  }, []);

  // ── Render ───────────────────────────────────────────────────────────────

  return (
    <div className="flex h-full flex-col bg-[var(--background)]">
      {/* Kids toolbar */}
      <header className="flex items-center justify-between border-b border-[var(--border)] bg-[var(--card)] px-4 py-3">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onBack}
            className="flex h-11 w-11 items-center justify-center rounded-xl bg-[var(--muted)] transition hover:brightness-95"
            aria-label={t("Back to library")}
          >
            <ArrowLeft size={22} />
          </button>
          <button
            type="button"
            onClick={() => setPanel(panel === "toc" ? "none" : "toc")}
            className={`flex h-11 w-11 items-center justify-center rounded-xl transition ${panel === "toc" ? "bg-[var(--primary)] text-[var(--primary-foreground)]" : "bg-[var(--muted)]"}`}
            aria-label={t("Contents")}
          >
            <List size={22} />
          </button>
        </div>
        <h1 className="flex-1 truncate px-3 text-center text-base font-semibold">
          {doc.title}
        </h1>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={speaking ? stopSpeaking : speakFromSelection}
            className={`flex h-11 w-11 items-center justify-center rounded-xl transition ${speaking ? "bg-amber-500 text-white" : "bg-[var(--muted)]"}`}
            aria-label={speaking ? t("Stop reading") : t("Read aloud")}
            title={t("Select text then tap to read aloud")}
          >
            {speaking ? <VolumeX size={22} /> : <Volume2 size={22} />}
          </button>
          <button
            type="button"
            onClick={() => loadQuiz(false)}
            disabled={quizLoading || !currentSection}
            className="flex h-11 w-11 items-center justify-center rounded-xl bg-[var(--muted)] transition hover:brightness-95 disabled:opacity-40"
            aria-label={t("Quiz")}
          >
            {quizLoading ? <Loader2 size={22} className="animate-spin" /> : <Award size={22} />}
          </button>
        </div>
      </header>

      {/* EPUB rendering area */}
      <div className="relative min-h-0 flex-1" style={{ "--tts-hl": "rgba(255, 215, 0, 0.4)" } as CSSProperties}>
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

        {/* Page turn buttons for children */}
        <button
          type="button"
          onClick={handlePrevPage}
          className="absolute bottom-5 left-4 z-10 flex h-14 w-14 items-center justify-center rounded-full bg-[var(--foreground)] text-[var(--background)] shadow-lg transition hover:scale-105 active:scale-95"
          aria-label={t("Previous page")}
        >
          <ChevronLeft size={28} />
        </button>
        <button
          type="button"
          onClick={handleNextPage}
          className="absolute bottom-5 right-4 z-10 flex h-14 w-14 items-center justify-center rounded-full bg-[var(--primary)] text-[var(--primary-foreground)] shadow-lg transition hover:scale-105 active:scale-95"
          aria-label={t("Next page")}
        >
          <ChevronRight size={28} />
        </button>
      </div>

      {/* TOC drawer */}
      {panel === "toc" && (
        <aside className="absolute left-0 top-[64px] z-30 flex h-[calc(100%-64px)] w-72 flex-col border-r border-[var(--border)] bg-[var(--card)] shadow-xl">
          <header className="flex items-center justify-between border-b border-[var(--border)] px-4 py-3">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <BookOpen size={16} /> {t("Stories")}
            </div>
            <button type="button" onClick={() => setPanel("none")} className="rounded-lg p-1.5 hover:bg-[var(--muted)]">
              <X size={16} />
            </button>
          </header>
          <div className="min-h-0 flex-1 overflow-y-auto p-2">
            {toc.map((item, i) => (
              <button
                key={item.href}
                type="button"
                onClick={() => {
                  renditionRef.current?.display(item.href);
                  setPanel("none");
                }}
                className={`block w-full rounded-xl px-4 py-3 text-left text-sm transition ${currentHref === item.href ? "bg-[var(--primary)] text-[var(--primary-foreground)]" : "hover:bg-[var(--muted)]"}`}
              >
                <span className="mr-2 text-xs opacity-50">{i + 1}.</span>
                {item.label.trim() || `${t("Story")} ${i + 1}`}
              </button>
            ))}
          </div>
        </aside>
      )}

      {/* Quiz panel */}
      {panel === "quiz" && (
        <aside className="absolute right-0 top-[64px] z-30 flex h-[calc(100%-64px)] w-full max-w-md flex-col border-l border-[var(--border)] bg-[var(--card)] shadow-xl">
          <header className="flex items-center justify-between border-b border-[var(--border)] px-4 py-3">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <Award size={16} className="text-[var(--primary)]" /> {t("Story Quiz")}
            </div>
            <button type="button" onClick={() => setPanel("none")} className="rounded-lg p-1.5 hover:bg-[var(--muted)]">
              <X size={16} />
            </button>
          </header>
          <div className="min-h-0 flex-1 overflow-y-auto p-5">
            {!quiz || quizLoading ? (
              <div className="flex items-center justify-center py-12 text-[var(--muted-foreground)]">
                <Loader2 className="animate-spin" />
              </div>
            ) : quiz.questions.length === 0 ? (
              <p className="text-center text-sm text-[var(--muted-foreground)]">{t("No quiz available for this story.")}</p>
            ) : (
              <div className="space-y-6">
                {quiz.questions.map((q, qi) => (
                  <div key={q.id} className="rounded-2xl border border-[var(--border)] p-4">
                    <div className="mb-1 flex items-center gap-2">
                      <span className="flex h-6 w-6 items-center justify-center rounded-full bg-[var(--primary)] text-xs font-bold text-[var(--primary-foreground)]">{qi + 1}</span>
                      <span className="text-[10px] uppercase tracking-wide text-[var(--muted-foreground)]">
                        {q.kind === "comprehension" ? t("Comprehension") : q.kind === "sight_word" ? t("Sight Word") : t("Sequence")}
                      </span>
                    </div>
                    <p className="mb-3 text-sm font-medium">{q.question}</p>
                    <div className="grid grid-cols-1 gap-2">
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
                            className={`flex items-center gap-2 rounded-xl border px-3 py-2.5 text-left text-sm transition ${
                              showResult && correct
                                ? "border-emerald-500 bg-emerald-500/10"
                                : showResult && selected && !correct
                                  ? "border-red-500 bg-red-500/10"
                                  : selected
                                    ? "border-[var(--primary)] bg-[var(--primary)]/8"
                                    : "border-[var(--border)] hover:bg-[var(--muted)]"
                            }`}
                          >
                            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-current text-[10px] font-bold opacity-60">
                              {String.fromCharCode(65 + ci)}
                            </span>
                            {choice}
                          </button>
                        );
                      })}
                    </div>
                    {quizSubmitted && q.explanation && (
                      <p className="mt-2 rounded-lg bg-[var(--muted)] px-3 py-2 text-xs leading-5 text-[var(--muted-foreground)]">{q.explanation}</p>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
          {quiz && !quizLoading && (
            <footer className="border-t border-[var(--border)] px-5 py-4">
              {quizSubmitted && quizScore ? (
                <div className="flex flex-col items-center gap-3">
                  <div className={`flex items-center gap-2 rounded-2xl px-5 py-3 ${quizScore.correct === quizScore.total ? "bg-emerald-500/15" : "bg-amber-500/15"}`}>
                    <Award size={24} className={quizScore.correct === quizScore.total ? "text-emerald-500" : "text-amber-500"} />
                    <span className="text-lg font-bold">{quizScore.correct}/{quizScore.total}</span>
                  </div>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => loadQuiz(true)}
                      className="inline-flex items-center gap-2 rounded-xl bg-[var(--muted)] px-4 py-2 text-sm font-medium"
                    >
                      <RotateCcw size={15} /> {t("New quiz")}
                    </button>
                    <button
                      type="button"
                      onClick={() => setPanel("none")}
                      className="inline-flex items-center gap-2 rounded-xl bg-[var(--primary)] px-4 py-2 text-sm font-medium text-[var(--primary-foreground)]"
                    >
                      {t("Keep reading")}
                    </button>
                  </div>
                </div>
              ) : (
                <button
                  type="button"
                  disabled={Object.keys(quizAnswers).length < quiz.questions.length}
                  onClick={() => setQuizSubmitted(true)}
                  className="w-full rounded-xl bg-[var(--primary)] py-3 text-base font-bold text-[var(--primary-foreground)] disabled:opacity-40"
                >
                  {t("Check answers")}
                </button>
              )}
            </footer>
          )}
        </aside>
      )}

      {/* Translation modal */}
      {translateResult && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/55 p-5 backdrop-blur-sm"
          role="dialog"
          aria-modal="true"
          onMouseDown={(e) => { if (e.currentTarget === e.target) setTranslateResult(null); }}
        >
          <div className="w-full max-w-lg rounded-2xl border border-[var(--border)] bg-[var(--card)] p-6 shadow-2xl">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-lg font-semibold">
                <Languages size={20} /> {t("Translation")}
              </div>
              <button type="button" onClick={() => setTranslateResult(null)} className="rounded-lg p-2 hover:bg-[var(--muted)]">
                <X size={18} />
              </button>
            </div>
            {translating ? (
              <div className="flex items-center justify-center gap-2 py-8 text-[var(--muted-foreground)]">
                <Loader2 size={18} className="animate-spin" /> {t("Translating…")}
              </div>
            ) : (
              <div className="mt-4 space-y-4">
                <div>
                  <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">{t("English")}</p>
                  <p className="font-serif text-base leading-7">{translateResult.text}</p>
                </div>
                <div className="border-t border-[var(--border)] pt-3">
                  <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">{t("Chinese")}</p>
                  <p className="text-base leading-7">{translateResult.result}</p>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
