"use client";

import dynamic from "next/dynamic";
import {
  ArrowLeft,
  Award,
  BookOpen,
  ChevronLeft,
  ChevronRight,
  Languages,
  Loader2,
  Lock,
  PartyPopper,
  RotateCcw,
  Star,
  Trophy,
  Volume2,
  VolumeX,
  X,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import {
  KidsApiError,
  kidsApi,
  type KidsUsage,
  type KidsSafeQuestion,
  type KidsQuizGrade,
} from "@/lib/kids-api";

const ReactReader = dynamic(
  () => import("react-reader").then((m) => m.ReactReader),
  {
    ssr: false,
    loading: () => (
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", gap: 16 }}>
        <Loader2 size={40} className="animate-spin text-indigo-500" />
        <div style={{ fontSize: 20, fontWeight: 700, color: "#4a3f6b" }}>Opening book...</div>
      </div>
    ),
  },
);

type Rendition = any;
type NavItem = any;

interface SectionItem {
  id: string;
  index: number;
  title: string;
  checkpointKind: string;
}

export default function KidsReaderPage() {
  const router = useRouter();
  const params = useParams();
  const documentId = params.documentId as string;

  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [bookTitle, setBookTitle] = useState("");
  const [location, setLocation] = useState<string | null>(null);
  const [toc, setToc] = useState<NavItem[]>([]);
  const [showTocDrawer, setShowTocDrawer] = useState(false);
  const [showQuiz, setShowQuiz] = useState(false);
  const [quizSectionId, setQuizSectionId] = useState("");
  const [quizSectionTitle, setQuizSectionTitle] = useState("");
  const [quizError, setQuizError] = useState("");
  const [quizExempt, setQuizExempt] = useState(false);
  const [questions, setQuestions] = useState<KidsSafeQuestion[]>([]);
  const [quizLoading, setQuizLoading] = useState(false);
  const [answers, setAnswers] = useState<Record<number, number>>({});
  const [grade, setGrade] = useState<KidsQuizGrade | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [translateText, setTranslateText] = useState<string | null>(null);
  const [translateResult, setTranslateResult] = useState("");
  const [translating, setTranslating] = useState(false);
  const [stars, setStars] = useState(0);

  // Exit-protection state
  const [showExitPin, setShowExitPin] = useState(false);
  const [exitPin, setExitPin] = useState("");
  const [exitPinError, setExitPinError] = useState("");
  const [profileHasPin, setProfileHasPin] = useState(false);
  const [profileId, setProfileId] = useState("");
  const [helpLanguage, setHelpLanguage] = useState<"en" | "zh">("en");
  const [usage, setUsage] = useState<KidsUsage | null>(null);
  const [progressPercent, setProgressPercent] = useState(0);
  const [bookComplete, setBookComplete] = useState(false);
  const [showAchievement, setShowAchievement] = useState(false);

  const utteranceRef = useRef<SpeechSynthesisUtterance | null>(null);
  const renditionRef = useRef<Rendition | null>(null);
  const currentHrefRef = useRef<string>("");
  const currentSectionIdRef = useRef<string>("");
  const lastTappedTextRef = useRef<string>("");
  const sectionIdByHrefRef = useRef<Map<string, string>>(new Map());
  const sectionsListRef = useRef<SectionItem[]>([]);
  const sectionsByIdRef = useRef<Map<string, SectionItem>>(new Map());
  const completedSectionIdsRef = useRef<Set<string>>(new Set());
  const bookCompleteRef = useRef(false);
  const handleRelocatedRef = useRef<(location: any) => void>(() => {});
  const narrationRateRef = useRef(0.8);
  const lastClickTimeRef = useRef(0);
  const pendingTranslateRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── Load Book Data ───────────────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await kidsApi.getBook(documentId);
        if (cancelled) return;
        const doc = data.document as Record<string, any>;
        setBookTitle(doc.title || "Book");
        setStars(data.progress?.total_stars || 0);
        setUsage(data.usage);
        setProgressPercent(Number(doc.progress_percent || 0));
        setBookComplete(Boolean(doc.is_complete));
        bookCompleteRef.current = Boolean(doc.is_complete);
        narrationRateRef.current = data.profile?.narration_rate || 0.8;
        if (data.profile?.help_language) {
          setHelpLanguage(data.profile.help_language);
        }

        const rawSections: any[] = Array.isArray(doc.sections) ? doc.sections : [];
        const parsedSections: SectionItem[] = rawSections.map((section: any, i: number) => ({
          id: String(section.id),
          index: Number(section.index ?? i),
          title: String(section.title || `Story ${i + 1}`),
          checkpointKind: String(section.checkpoint_kind || "chapter"),
        }));

        sectionsListRef.current = parsedSections;
        sectionsByIdRef.current = new Map(parsedSections.map((s) => [s.id, s]));

        const hrefMap = new Map<string, string>();
        parsedSections.forEach((section, i) => {
          const rawHref = String(rawSections[i]?.source_href || "");
          if (rawHref) hrefMap.set(rawHref, section.id);
          hrefMap.set(`chapter-${i + 1}.xhtml`, section.id);
          hrefMap.set(`OEBPS/chapter-${i + 1}.xhtml`, section.id);
          hrefMap.set(`chapter-${section.index + 1}.xhtml`, section.id);
          hrefMap.set(`OEBPS/chapter-${section.index + 1}.xhtml`, section.id);
        });
        sectionIdByHrefRef.current = hrefMap;

        completedSectionIdsRef.current = new Set(
          (data.progress?.completed_section_ids || []).filter(
            (sectionId: string) => sectionsByIdRef.current.get(sectionId)?.checkpointKind !== "none",
          ),
        );

        const initialSectionId =
          data.progress?.current_section_id && sectionsByIdRef.current.has(data.progress.current_section_id)
            ? data.progress.current_section_id
            : parsedSections[0]?.id || "";
        currentSectionIdRef.current = initialSectionId;

        if (data.progress?.epub_cfi) {
          setLocation(data.progress.epub_cfi);
        }
      } catch (err: any) {
        if (cancelled) return;
        if (err instanceof KidsApiError && err.status === 401) {
          // No session: redirect to profile picker
          router.push("/kids");
          return;
        }
        setLoadError(err?.message || "Could not load book.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [documentId, router]);

  // ── Heartbeat ────────────────────────────────────────────────────────────
  useEffect(() => {
    let stopped = false;
    const beat = async () => {
      if (document.visibilityState !== "visible") return;
      try {
        const result = await kidsApi.heartbeat(documentId);
        if (!stopped) setUsage(result);
      } catch (error) {
        if (
          error instanceof KidsApiError &&
          typeof error.detail === "object" &&
          error.detail !== null &&
          (error.detail as { code?: string }).code === "daily_limit_reached"
        ) {
          setUsage(error.detail as KidsUsage);
        }
      }
    };
    beat();
    const timer = window.setInterval(beat, 30_000);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [documentId]);

  // ── Profile PIN Check ────────────────────────────────────────────────────
  useEffect(() => {
    const pid = localStorage.getItem("dt_kids_profile_id") || "";
    setProfileId(pid);
    if (!pid) return;
    kidsApi
      .getProfilePublicInfo(pid)
      .then(({ profile }) => {
        if (profile) setProfileHasPin(Boolean(profile.has_pin));
      })
      .catch(() => {});
  }, []);

  const handleExitClick = () => {
    if (profileHasPin) {
      setShowExitPin(true);
      setExitPin("");
      setExitPinError("");
    } else {
      void doExit();
    }
  };

  const doExit = async () => {
    await kidsApi.logout().catch(() => {});
    localStorage.removeItem("dt_kids_profile_id");
    router.push("/kids");
  };

  const handleExitPinSubmit = async () => {
    try {
      await kidsApi.exitVerify(profileId, exitPin);
      await doExit();
    } catch {
      setExitPinError("Wrong PIN. Try again!");
      setExitPin("");
    }
  };

  // ── TTS & Speech Synthesis ───────────────────────────────────────────────
  const stopSpeaking = useCallback(() => {
    if (typeof window !== "undefined" && window.speechSynthesis) {
      window.speechSynthesis.cancel();
      utteranceRef.current = null;
    }
    setSpeaking(false);
  }, []);

  const speakText = useCallback(
    (text: string) => {
      if (!text || !text.trim() || typeof window === "undefined" || !window.speechSynthesis) return;
      stopSpeaking();
      setSpeaking(true);

      const utter = new SpeechSynthesisUtterance(text.trim());
      utter.lang = "en-US";
      utter.rate = narrationRateRef.current;
      utter.onend = () => setSpeaking(false);
      utter.onerror = () => setSpeaking(false);
      utteranceRef.current = utter;
      window.speechSynthesis.speak(utter);
    },
    [stopSpeaking],
  );

  const speakSelectionOrFallback = useCallback(() => {
    if (speaking) {
      stopSpeaking();
      return;
    }
    const selection = renditionRef.current?.getRange?.();
    const selText = selection?.toString()?.trim();
    if (selText) {
      speakText(selText);
      return;
    }
    if (lastTappedTextRef.current) {
      speakText(lastTappedTextRef.current);
      return;
    }
    const currentSection = sectionsByIdRef.current.get(currentSectionIdRef.current);
    if (currentSection?.title) {
      speakText(currentSection.title);
    }
  }, [speaking, stopSpeaking, speakText]);

  // ── Translation ──────────────────────────────────────────────────────────
  const handleTranslate = useCallback(async (text: string) => {
    const clean = text.trim();
    if (!clean) return;
    setTranslateText(clean);
    setTranslating(true);
    setTranslateResult("");
    try {
      const { translation } = await kidsApi.translate(clean, "Chinese");
      setTranslateResult(translation);
    } catch {
      setTranslateResult("Translation unavailable");
    } finally {
      setTranslating(false);
    }
  }, []);

  const translateSelectionOrFallback = useCallback(() => {
    const selection = renditionRef.current?.getRange?.();
    const selText = selection?.toString()?.trim();
    if (selText) {
      handleTranslate(selText);
      return;
    }
    if (lastTappedTextRef.current) {
      handleTranslate(lastTappedTextRef.current);
      return;
    }
    const currentSection = sectionsByIdRef.current.get(currentSectionIdRef.current);
    if (currentSection?.title) {
      handleTranslate(currentSection.title);
    }
  }, [handleTranslate]);

  // ── Quiz Flow ────────────────────────────────────────────────────────────
  const openQuiz = useCallback(
    async (sectionId: string) => {
      const section = sectionsByIdRef.current.get(sectionId);
      setShowQuiz(true);
      setQuizSectionId(sectionId);
      setQuizSectionTitle(section?.title || "Story");
      setGrade(null);
      setAnswers({});
      setQuizError("");
      setQuizExempt(false);
      setQuizLoading(true);
      try {
        const quiz = await kidsApi.getQuiz(documentId, sectionId);
        setQuizExempt(quiz.status === "exempt");
        setQuestions(quiz.questions);
      } catch (error) {
        setQuestions([]);
        setQuizError(
          error instanceof KidsApiError && error.status === 403
            ? "Finish reading this story to unlock the quiz!"
            : "Quiz unavailable. Keep reading!",
        );
      } finally {
        setQuizLoading(false);
      }
    },
    [documentId],
  );

  const submitQuiz = async () => {
    setSubmitting(true);
    setQuizError("");
    try {
      const answerArr = questions.map((_, i) => answers[i] ?? -1);
      const result = await kidsApi.submitQuiz(documentId, quizSectionId, answerArr);
      setGrade(result);
      setBookComplete(Boolean(result.is_complete));
      bookCompleteRef.current = Boolean(result.is_complete);
      setStars((s) => s + (result.earned_stars ?? result.stars));
    } catch {
      setQuizError("Quiz unavailable. Try again!");
    } finally {
      setSubmitting(false);
    }
  };

  // ── Section & Progress Synchronization ───────────────────────────────────
  const syncSection = useCallback(
    (loc: string, rawHref: string, rawPercent: number) => {
      const raw = rawHref.split(/[?#]/)[0].trim();
      const cleaned = raw.replace(/^(\.\/|\/|OEBPS\/)+/, "");
      const sectionId =
        sectionIdByHrefRef.current.get(raw) ||
        sectionIdByHrefRef.current.get(cleaned) ||
        sectionIdByHrefRef.current.get(`OEBPS/${cleaned}`) ||
        sectionIdByHrefRef.current.get(`/${cleaned}`);
      if (!sectionId) return;

      const section = sectionsByIdRef.current.get(sectionId);
      const previous = currentSectionIdRef.current
        ? sectionsByIdRef.current.get(currentSectionIdRef.current)
        : undefined;
      const percent = Math.max(0, Math.min(100, rawPercent * 100));
      const totalCheckpoints = Array.from(sectionsByIdRef.current.values()).filter(
        (item) => item.checkpointKind !== "none",
      ).length;

      currentSectionIdRef.current = sectionId;
      currentHrefRef.current = raw;

      const save = (id: string, scrollPercent: number, completed = false) =>
        kidsApi.updateProgress(documentId, {
          section_id: id,
          section_index: sectionsByIdRef.current.get(id)?.index || 0,
          scroll_percent: scrollPercent,
          epub_cfi: loc,
          section_href: sectionsByIdRef.current.get(id)?.index === section?.index ? raw : "",
          completed,
        });

      void (async () => {
        try {
          if (
            previous &&
            section &&
            previous.checkpointKind !== "none" &&
            section.index === previous.index + 1 &&
            !completedSectionIdsRef.current.has(previous.id)
          ) {
            const result = await save(previous.id, 100, true);
            completedSectionIdsRef.current.add(previous.id);
            setStars(result.progress.total_stars);
            setProgressPercent(
              Math.round((completedSectionIdsRef.current.size / Math.max(1, totalCheckpoints)) * 100),
            );
            await openQuiz(previous.id);
          }

          if (
            section &&
            section.checkpointKind !== "none" &&
            percent >= 98 &&
            !completedSectionIdsRef.current.has(sectionId)
          ) {
            const result = await save(sectionId, 100, true);
            completedSectionIdsRef.current.add(sectionId);
            setStars(result.progress.total_stars);
            setProgressPercent(
              Math.round((completedSectionIdsRef.current.size / Math.max(1, totalCheckpoints)) * 100),
            );
            await openQuiz(sectionId);
          } else {
            await save(sectionId, percent);
          }
        } catch (error) {
          if (
            error instanceof KidsApiError &&
            typeof error.detail === "object" &&
            error.detail !== null &&
            (error.detail as { code?: string }).code === "chapter_quiz_required"
          ) {
            const detail = error.detail as { section_id?: string };
            if (detail.section_id) await openQuiz(detail.section_id);
          }
        }
      })();
    },
    [documentId, openQuiz],
  );

  useEffect(() => {
    handleRelocatedRef.current = (loc: any) => {
      const href = String(loc?.start?.href || "");
      const percent = loc?.atEnd ? 100 : Number(loc?.start?.percentage ?? 0);
      const cfi = String(loc?.start?.cfi || "");
      if (href) syncSection(cfi, href, percent);
    };
  }, [syncSection]);

  // ── Rendition Setup (Styling, Tap, Double-Tap) ───────────────────────────
  const handleGetRendition = useCallback(
    (rendition: Rendition) => {
      renditionRef.current = rendition;

      rendition.themes.register("kids", {
        p: {
          fontSize: "140%",
          lineHeight: "2.3",
          fontFamily: "'Comic Sans MS', 'Chalkboard SE', system-ui, sans-serif",
          margin: "1.2em 0",
          cursor: "pointer",
          color: "#2d3748",
        },
        h1: {
          fontSize: "200%",
          textAlign: "center",
          fontFamily: "'Comic Sans MS', 'Chalkboard SE', system-ui, sans-serif",
          color: "#4a3f6b",
          margin: "0.8em 0",
        },
        h2: {
          fontSize: "160%",
          textAlign: "center",
          fontFamily: "'Comic Sans MS', 'Chalkboard SE', system-ui, sans-serif",
          color: "#4a3f6b",
        },
        body: {
          padding: "0 2em",
          background: "#fffdfa",
        },
      });
      rendition.themes.select("kids");
      rendition.themes.fontSize("140%");

      void rendition.book.ready
        .then(() => rendition.book.locations.generate(1024))
        .then(() => rendition.reportLocation());

      rendition.on("relocated", (loc: any) => {
        handleRelocatedRef.current(loc);
      });

      // Tap paragraph to read aloud, double-tap to translate
      rendition.on("click", (event: MouseEvent) => {
        const target = event.target as HTMLElement;
        let el: HTMLElement | null = target;
        while (
          el &&
          el.tagName !== "P" &&
          el.tagName !== "H1" &&
          el.tagName !== "H2" &&
          el.tagName !== "H3" &&
          el.parentElement
        ) {
          el = el.parentElement;
        }
        if (!el) return;

        const text = el.textContent?.trim() ?? "";
        if (!text) return;
        lastTappedTextRef.current = text;

        const now = Date.now();
        const isDouble = now - lastClickTimeRef.current < 400;
        lastClickTimeRef.current = now;

        if (pendingTranslateRef.current) {
          clearTimeout(pendingTranslateRef.current);
          pendingTranslateRef.current = null;
        }

        if (isDouble) {
          stopSpeaking();
          void handleTranslate(text);
        } else {
          pendingTranslateRef.current = setTimeout(() => {
            speakText(text);
          }, 250);
        }
      });
    },
    [handleTranslate, speakText, stopSpeaking],
  );

  const handlePrevPage = () => {
    renditionRef.current?.prev();
  };

  const handleNextPage = () => {
    renditionRef.current?.next();
  };

  const handleSelectStory = (storyIndex: number) => {
    setShowTocDrawer(false);
    const filename = `chapter-${storyIndex + 1}.xhtml`;
    renditionRef.current?.display(filename);
  };

  useEffect(() => {
    return () => {
      stopSpeaking();
      if (pendingTranslateRef.current) clearTimeout(pendingTranslateRef.current);
    };
  }, [stopSpeaking]);

  // ── Render: Loading & Error States ───────────────────────────────────────
  if (loading) {
    return (
      <div style={styles.centerContainer}>
        <Loader2 size={48} className="animate-spin text-indigo-600" />
        <p style={{ fontSize: 22, fontWeight: 700, color: "#4a3f6b", marginTop: 16 }}>
          Loading your story world...
        </p>
      </div>
    );
  }

  if (loadError) {
    return (
      <div style={styles.centerContainer}>
        <div style={{ fontSize: 64 }}>📖</div>
        <p style={{ fontSize: 20, fontWeight: 700, color: "#e53e3e", marginTop: 16 }}>{loadError}</p>
        <button style={{ ...bigBtn, background: "#667eea", color: "white", marginTop: 20 }} onClick={() => router.push("/kids")}>
          Back to Books
        </button>
      </div>
    );
  }

  return (
    <div style={{ height: "100vh", display: "flex", flexDirection: "column", background: "#fef9f0", position: "relative" }}>
      {/* Daily limit reached overlay */}
      {usage?.limit_reached && (
        <div style={popupOverlay}>
          <div style={popupBox}>
            <div style={{ fontSize: 56 }}>⏰</div>
            <div style={{ fontSize: 32, fontWeight: 800, color: "#4a3f6b", marginTop: 8 }}>Time is up!</div>
            <p style={{ fontSize: 18, color: "#7c6f9b", marginTop: 8 }}>
              You reached your reading goal for today. Great job!
            </p>
            <button style={{ ...bigBtn, background: "#667eea", color: "white", marginTop: 16 }} onClick={handleExitClick}>
              Close Book
            </button>
          </div>
        </div>
      )}

      {/* Exit PIN modal */}
      {showExitPin && (
        <div style={popupOverlay}>
          <div style={{ ...popupBox, maxWidth: 360 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, color: "#7c6f9b", fontSize: 18, fontWeight: 700 }}>
              <Lock size={20} /> Enter PIN to exit
            </div>
            <input
              type="password"
              value={exitPin}
              onChange={(e) => setExitPin(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && exitPin.length >= 4 && handleExitPinSubmit()}
              maxLength={8}
              style={{
                fontSize: 32,
                textAlign: "center",
                letterSpacing: 12,
                border: "3px solid #667eea",
                borderRadius: 16,
                padding: "12px 16px",
                width: "100%",
                outline: "none",
                marginTop: 16,
              }}
              placeholder="• • • •"
              autoFocus
            />
            {exitPinError && <p style={{ fontSize: 15, color: "#e53e3e", marginTop: 8 }}>{exitPinError}</p>}
            <div style={{ display: "flex", gap: 12, marginTop: 20 }}>
              <button
                style={{ ...bigBtn, padding: "10px 20px", background: "#e2e8f0", color: "#4a5568", fontSize: 16 }}
                onClick={() => {
                  setShowExitPin(false);
                  setExitPin("");
                  setExitPinError("");
                }}
              >
                Cancel
              </button>
              <button
                style={{ ...bigBtn, padding: "10px 20px", background: "#667eea", color: "white", fontSize: 16, opacity: exitPin.length < 4 ? 0.5 : 1 }}
                onClick={handleExitPinSubmit}
                disabled={exitPin.length < 4}
              >
                Exit
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Top Toolbar */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          padding: "10px 16px",
          background: "white",
          boxShadow: "0 2px 8px rgba(0,0,0,0.06)",
          zIndex: 20,
          flexShrink: 0,
        }}
      >
        <button onClick={handleExitClick} style={toolbarBtn} aria-label="Back to Bookshelf">
          <ArrowLeft size={18} style={{ marginRight: 4, display: "inline" }} />
          Books
        </button>

        <button
          onClick={() => setShowTocDrawer(true)}
          style={{ ...toolbarBtn, background: "#edf2f7", color: "#4a5568" }}
          aria-label="Story List"
        >
          <BookOpen size={18} style={{ marginRight: 4, display: "inline" }} />
          Stories
        </button>

        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{
              textAlign: "center",
              fontWeight: 800,
              fontSize: 18,
              color: "#4a3f6b",
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {bookTitle}
          </div>
          <div style={{ height: 6, background: "#e9e4f5", borderRadius: 999, marginTop: 4 }}>
            <div
              style={{
                width: `${progressPercent}%`,
                height: "100%",
                background: "linear-gradient(90deg, #667eea, #764ba2)",
                borderRadius: 999,
                transition: "width 0.3s ease",
              }}
            />
          </div>
        </div>

        <div style={starsChip}>
          <Star size={18} fill="#d69e2e" color="#d69e2e" />
          <span>{stars}</span>
        </div>
      </div>

      {/* Hint / Helper Bar */}
      <div
        style={{
          background: "#fffbeb",
          borderBottom: "1px solid #fef3c7",
          padding: "6px 16px",
          textAlign: "center",
          fontSize: 13,
          fontWeight: 600,
          color: "#92400e",
          flexShrink: 0,
        }}
      >
        {speaking
          ? "🔊 Listening... tap text or 'Stop' to end"
          : helpLanguage === "zh"
            ? "🔊 点击句子朗读 · 双击查看翻译 · 点击左右按钮翻页"
            : "🔊 Tap any sentence to listen · Double-tap to translate · Click ◀ ▶ to turn pages"}
      </div>

      {/* EPUB Reader Area */}
      <div style={{ flex: 1, position: "relative", overflow: "hidden", background: "#fef9f0" }}>
        <ReactReader
          url={kidsApi.getEpubUrl(documentId)}
          location={location ?? null}
          locationChanged={(loc: string) => {
            setLocation(loc);
          }}
          tocChanged={(t: NavItem[]) => setToc(t)}
          showToc={false}
          epubInitOptions={{ openAs: "epub" }}
          epubOptions={{
            allowPopups: false,
            allowScriptedContent: false,
            spread: "none",
          }}
          getRendition={handleGetRendition}
        />

        {/* Floating Prev / Next Page Turn Buttons */}
        <button
          onClick={handlePrevPage}
          style={{ ...pageNavBtn, left: 16 }}
          aria-label="Previous Page"
          title="Previous Page"
        >
          <ChevronLeft size={36} color="white" />
        </button>

        <button
          onClick={handleNextPage}
          style={{ ...pageNavBtn, right: 16 }}
          aria-label="Next Page"
          title="Next Page"
        >
          <ChevronRight size={36} color="white" />
        </button>
      </div>

      {/* Bottom Action Controls */}
      <div
        style={{
          display: "flex",
          gap: 12,
          padding: "10px 16px",
          background: "white",
          boxShadow: "0 -2px 8px rgba(0,0,0,0.06)",
          justifyContent: "center",
          alignItems: "center",
          flexShrink: 0,
          zIndex: 20,
        }}
      >
        <button
          style={{
            ...bigBtn,
            background: speaking ? "#fed7d7" : "#e9d8fd",
            color: speaking ? "#c53030" : "#553c9e",
          }}
          onClick={speakSelectionOrFallback}
        >
          {speaking ? (
            <>
              <VolumeX size={20} style={{ marginRight: 6, display: "inline" }} />
              Stop
            </>
          ) : (
            <>
              <Volume2 size={20} style={{ marginRight: 6, display: "inline" }} />
              Read Aloud
            </>
          )}
        </button>

        <button
          style={{ ...bigBtn, background: "#bee3f8", color: "#2b6cb0" }}
          onClick={translateSelectionOrFallback}
        >
          <Languages size={20} style={{ marginRight: 6, display: "inline" }} />
          Translate
        </button>

        <button
          style={{ ...bigBtn, background: "#feebc8", color: "#c05621" }}
          onClick={() => void openQuiz(currentSectionIdRef.current)}
        >
          <Award size={20} style={{ marginRight: 6, display: "inline" }} />
          Quiz
        </button>
      </div>

      {/* Story Drawer (TOC) */}
      {showTocDrawer && (
        <div style={popupOverlay} onClick={() => setShowTocDrawer(false)}>
          <div
            style={{
              position: "fixed",
              top: 0,
              bottom: 0,
              left: 0,
              width: 320,
              maxWidth: "85vw",
              background: "white",
              boxShadow: "4px 0 24px rgba(0,0,0,0.15)",
              display: "flex",
              flexDirection: "column",
              zIndex: 110,
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "16px 20px",
                background: "linear-gradient(135deg, #667eea, #764ba2)",
                color: "white",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 18, fontWeight: 800 }}>
                <BookOpen size={22} />
                Stories
              </div>
              <button
                onClick={() => setShowTocDrawer(false)}
                style={{ background: "rgba(255,255,255,0.2)", border: "none", borderRadius: 10, padding: 6, color: "white", cursor: "pointer" }}
              >
                <X size={20} />
              </button>
            </div>

            <div style={{ flex: 1, overflowY: "auto", padding: 12 }}>
              {sectionsListRef.current.map((section, idx) => {
                const isCompleted = completedSectionIdsRef.current.has(section.id);
                const isCurrent = currentSectionIdRef.current === section.id;
                return (
                  <button
                    key={section.id}
                    onClick={() => handleSelectStory(idx)}
                    style={{
                      width: "100%",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      padding: "12px 14px",
                      borderRadius: 14,
                      border: isCurrent ? "2px solid #667eea" : "1px solid #edf2f7",
                      background: isCurrent ? "#f0f4ff" : "#ffffff",
                      marginBottom: 8,
                      cursor: "pointer",
                      textAlign: "left",
                    }}
                  >
                    <div>
                      <div style={{ fontSize: 12, fontWeight: 700, color: isCurrent ? "#667eea" : "#a0aec0" }}>
                        Story {idx + 1}
                      </div>
                      <div style={{ fontSize: 15, fontWeight: 700, color: "#2d3748", marginTop: 2 }}>
                        {section.title}
                      </div>
                    </div>
                    {isCompleted ? (
                      <Star size={18} fill="#d69e2e" color="#d69e2e" />
                    ) : (
                      <span style={{ fontSize: 13, color: "#a0aec0" }}>➔</span>
                    )}
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* Translation Popup */}
      {translateText && (
        <div style={popupOverlay} onClick={() => setTranslateText(null)}>
          <div style={popupBox} onClick={(e) => e.stopPropagation()}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
              <span style={{ fontSize: 14, fontWeight: 700, color: "#667eea" }}>中文翻译 Translation</span>
              <button
                onClick={() => setTranslateText(null)}
                style={{ background: "#f7fafc", border: "none", borderRadius: 8, padding: 4, cursor: "pointer" }}
              >
                <X size={18} color="#718096" />
              </button>
            </div>
            <div style={{ fontSize: 16, color: "#4a5568", marginBottom: 12, fontStyle: "italic" }}>
              &ldquo;{translateText}&rdquo;
            </div>
            <div style={{ fontSize: 22, fontWeight: 800, color: "#2d3748", minHeight: 36 }}>
              {translating ? (
                <div style={{ display: "flex", alignItems: "center", gap: 8, color: "#a0aec0", fontSize: 16 }}>
                  <Loader2 size={18} className="animate-spin" /> Translating...
                </div>
              ) : (
                translateResult
              )}
            </div>
            <button
              style={{ ...bigBtn, marginTop: 20, width: "100%", background: "#e2e8f0", color: "#4a5568" }}
              onClick={() => setTranslateText(null)}
            >
              Close
            </button>
          </div>
        </div>
      )}

      {/* Quiz Modal */}
      {showQuiz && (
        <div style={popupOverlay} onClick={() => setShowQuiz(false)}>
          <div style={popupBox} onClick={(e) => e.stopPropagation()}>
            {grade ? (
              <div style={{ textAlign: "center" }}>
                <div style={{ display: "flex", justifyContent: "center", marginBottom: 8 }}>
                  <PartyPopper size={56} color="#667eea" />
                </div>
                <div style={{ fontSize: 26, fontWeight: 800, color: "#4a3f6b" }}>
                  {grade.stars >= 3
                    ? "🌟 Superstar!"
                    : grade.stars >= 2
                      ? "Great Job!"
                      : grade.stars >= 1
                        ? "Nice Try!"
                        : "Keep Reading!"}
                </div>
                <div style={{ fontSize: 20, fontWeight: 700, color: "#2d3748", marginTop: 8 }}>
                  {grade.score} / {grade.total} correct
                </div>
                <div style={{ display: "flex", justifyContent: "center", gap: 6, marginTop: 10 }}>
                  {Array.from({ length: 3 }).map((_, i) => (
                    <Star
                      key={i}
                      size={28}
                      fill={i < grade.stars ? "#d69e2e" : "transparent"}
                      color={i < grade.stars ? "#d69e2e" : "#cbd5e0"}
                    />
                  ))}
                </div>
                <p style={{ fontSize: 16, color: "#667eea", marginTop: 10, fontWeight: 600 }}>
                  {grade.encouragements[0]}
                </p>

                {grade.per_question.map((q, i) => (
                  <div
                    key={i}
                    style={{
                      marginTop: 10,
                      padding: 10,
                      borderRadius: 12,
                      background: q.correct ? "#f0fff4" : "#fff5f5",
                      border: q.correct ? "1px solid #c6f6d5" : "1px solid #fed7d7",
                      textAlign: "left",
                      fontSize: 14,
                    }}
                  >
                    <span style={{ fontWeight: 700, color: q.correct ? "#38a169" : "#e53e3e" }}>
                      {q.correct ? "✔ Correct" : "✖ Try Again"}:
                    </span>{" "}
                    <span style={{ color: "#4a5568" }}>{q.explanation}</span>
                  </div>
                ))}

                <button
                  style={{ ...bigBtn, marginTop: 20, width: "100%", background: "#667eea", color: "white" }}
                  onClick={() => {
                    setShowQuiz(false);
                    if (bookCompleteRef.current) {
                      setShowAchievement(true);
                    }
                  }}
                >
                  Done!
                </button>
              </div>
            ) : quizLoading ? (
              <div style={{ textAlign: "center", padding: 36 }}>
                <Loader2 size={40} className="animate-spin text-indigo-500" style={{ margin: "0 auto" }} />
                <p style={{ fontSize: 18, color: "#667eea", marginTop: 16, fontWeight: 700 }}>
                  Making your quiz...
                </p>
              </div>
            ) : quizError ? (
              <div style={{ textAlign: "center", padding: 24 }}>
                <p style={{ fontSize: 18, color: "#4a3f6b", fontWeight: 700 }}>{quizError}</p>
                <button
                  style={{ ...bigBtn, marginTop: 16, background: "#e2e8f0", color: "#4a5568" }}
                  onClick={() => setShowQuiz(false)}
                >
                  Keep Reading
                </button>
              </div>
            ) : quizExempt ? (
              <div style={{ textAlign: "center", padding: 24 }}>
                <p style={{ fontSize: 18, color: "#4a3f6b", fontWeight: 700 }}>
                  This chapter has no quiz. Keep reading!
                </p>
                <button
                  style={{ ...bigBtn, marginTop: 16, background: "#667eea", color: "white" }}
                  onClick={() => setShowQuiz(false)}
                >
                  Continue
                </button>
              </div>
            ) : questions.length === 0 ? (
              <div style={{ textAlign: "center", padding: 24 }}>
                <p style={{ fontSize: 18, color: "#e53e3e", fontWeight: 700 }}>
                  Quiz unavailable. Try reading first!
                </p>
                <button
                  style={{ ...bigBtn, marginTop: 16, background: "#e2e8f0", color: "#4a5568" }}
                  onClick={() => setShowQuiz(false)}
                >
                  Close
                </button>
              </div>
            ) : (
              <div>
                <h2 style={{ fontSize: 22, fontWeight: 800, color: "#4a3f6b", marginBottom: 16 }}>
                  {quizSectionTitle} Quiz
                </h2>
                {questions.map((q, qi) => (
                  <div key={qi} style={{ marginBottom: 18 }}>
                    <div style={{ fontSize: 17, fontWeight: 700, color: "#2d3748", marginBottom: 8 }}>
                      {qi + 1}. {q.question}
                    </div>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                      {q.choices.map((c, ci) => (
                        <button
                          key={ci}
                          onClick={() => setAnswers({ ...answers, [qi]: ci })}
                          style={{
                            padding: "10px 14px",
                            borderRadius: 12,
                            border: answers[qi] === ci ? "3px solid #667eea" : "2px solid #e2e8f0",
                            background: answers[qi] === ci ? "#e9d8fd" : "white",
                            fontSize: 15,
                            fontWeight: 600,
                            cursor: "pointer",
                            textAlign: "left",
                            color: "#2d3748",
                          }}
                        >
                          {c}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
                <button
                  style={{
                    ...bigBtn,
                    width: "100%",
                    background: "#667eea",
                    color: "white",
                    opacity: Object.keys(answers).length < questions.length ? 0.6 : 1,
                  }}
                  onClick={submitQuiz}
                  disabled={submitting || Object.keys(answers).length < questions.length}
                >
                  {submitting ? "Checking..." : "Check Answers!"}
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Book Complete Achievement */}
      {bookComplete && showAchievement && (
        <div style={popupOverlay}>
          <div style={popupBox}>
            <div style={{ textAlign: "center" }}>
              <Trophy size={64} color="#d69e2e" style={{ margin: "0 auto 12px auto" }} />
              <h2 style={{ fontSize: 28, fontWeight: 800, color: "#4a3f6b", margin: 0 }}>
                Book Complete!
              </h2>
              <p style={{ fontSize: 18, color: "#4a5568", marginTop: 12 }}>
                You finished every story and earned {stars} stars!
              </p>
              <button
                style={{ ...bigBtn, background: "#667eea", color: "white", marginTop: 16 }}
                onClick={() => setShowAchievement(false)}
              >
                Back to Book
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  centerContainer: {
    minHeight: "100vh",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    background: "linear-gradient(180deg, #e0f2ff 0%, #fef3e7 100%)",
    padding: 24,
  },
};

const toolbarBtn: React.CSSProperties = {
  background: "#f7fafc",
  border: "none",
  borderRadius: 12,
  padding: "8px 14px",
  fontSize: 15,
  fontWeight: 700,
  cursor: "pointer",
  color: "#4a5568",
  display: "flex",
  alignItems: "center",
};

const starsChip: React.CSSProperties = {
  background: "#fef3c7",
  borderRadius: 20,
  padding: "6px 14px",
  fontSize: 16,
  fontWeight: 800,
  color: "#92400e",
  display: "flex",
  alignItems: "center",
  gap: 6,
};

const bigBtn: React.CSSProperties = {
  border: "none",
  borderRadius: 16,
  padding: "12px 24px",
  fontSize: 16,
  fontWeight: 700,
  cursor: "pointer",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  transition: "transform 0.15s ease",
};

const pageNavBtn: React.CSSProperties = {
  position: "absolute",
  top: "50%",
  transform: "translateY(-50%)",
  width: 52,
  height: 52,
  borderRadius: "50%",
  background: "rgba(102, 126, 234, 0.85)",
  border: "none",
  boxShadow: "0 4px 16px rgba(0,0,0,0.2)",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  cursor: "pointer",
  zIndex: 15,
  transition: "all 0.2s ease",
};

const popupOverlay: React.CSSProperties = {
  position: "fixed",
  top: 0,
  left: 0,
  right: 0,
  bottom: 0,
  background: "rgba(0,0,0,0.45)",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  zIndex: 100,
  padding: 16,
};

const popupBox: React.CSSProperties = {
  background: "white",
  borderRadius: 24,
  padding: 28,
  maxWidth: 480,
  width: "100%",
  maxHeight: "85vh",
  overflowY: "auto",
  boxShadow: "0 12px 40px rgba(0,0,0,0.2)",
};
