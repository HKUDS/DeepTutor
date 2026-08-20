"use client";

import dynamic from "next/dynamic";
import { Trophy } from "lucide-react";
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
  { ssr: false, loading: () => <div style={{ textAlign: "center", padding: 40 }}>Opening book...</div> },
);

type Rendition = any;
type NavItem = any;

export default function KidsReaderPage() {
  const router = useRouter();
  const params = useParams();
  const documentId = params.documentId as string;

  const [loading, setLoading] = useState(true);
  const [bookTitle, setBookTitle] = useState("");
  const [location, setLocation] = useState<string | null>(null);
  const [toc, setToc] = useState<NavItem[]>([]);
  const [showQuiz, setShowQuiz] = useState(false);
  const [quizSectionId, setQuizSectionId] = useState("");
  const [quizSectionTitle, setQuizSectionTitle] = useState("");
  const [quizError, setQuizError] = useState("");
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
  const [usage, setUsage] = useState<KidsUsage | null>(null);
  const [progressPercent, setProgressPercent] = useState(0);
  const [bookComplete, setBookComplete] = useState(false);
  const [showAchievement, setShowAchievement] = useState(false);
  const utteranceRef = useRef<SpeechSynthesisUtterance | null>(null);
  const renditionRef = useRef<Rendition | null>(null);
  const currentHrefRef = useRef<string>("");
  const currentSectionIdRef = useRef<string>("");
  const sectionIdByHrefRef = useRef<Map<string, string>>(new Map());
  const sectionsByIdRef = useRef<Map<string, {
    id: string;
    index: number;
    title: string;
    checkpointKind: string;
  }>>(new Map());
  const completedSectionIdsRef = useRef<Set<string>>(new Set());
  const bookCompleteRef = useRef(false);
  const handleRelocatedRef = useRef<(location: any) => void>(() => {});
  const narrationRateRef = useRef(0.8);

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
        const sections = Array.isArray(doc.sections) ? doc.sections : [];
        sectionsByIdRef.current = new Map(
          sections.map((section: any) => [
            String(section.id),
            {
              id: String(section.id),
              index: Number(section.index || 0),
              title: String(section.title || `Chapter ${Number(section.index || 0) + 1}`),
              checkpointKind: String(section.checkpoint_kind || "chapter"),
            },
          ]),
        );
        sectionIdByHrefRef.current = new Map(
          sections
            .flatMap((section: any) => [
              [String(section.source_href || ""), String(section.id)],
              [`chapter-${Number(section.index) + 1}.xhtml`, String(section.id)],
            ] as const)
            .filter(([href, id]) => href && id),
        );
        if (!sections.length) {
          sectionIdByHrefRef.current.set("", String((sections[0] as any)?.id || ""));
        }
        completedSectionIdsRef.current = new Set(
          (data.progress?.completed_section_ids || []).filter(
            (sectionId: string) =>
              sectionsByIdRef.current.get(sectionId)?.checkpointKind !== "none",
          ),
        );
        currentSectionIdRef.current =
          data.progress?.current_section_id || String((sections[0] as any)?.id || "");
        if (data.progress?.epub_cfi) {
          setLocation(data.progress.epub_cfi);
        }
      } catch {
        if (!cancelled) setBookTitle("Book");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [documentId]);

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

  // Check if the current profile has a PIN (for exit protection)
  useEffect(() => {
    const pid = localStorage.getItem("dt_kids_profile_id") || "";
    setProfileId(pid);
    if (!pid) return;
    kidsApi.bootstrap().then(({ profiles }) => {
      const p = profiles.find((x) => x.id === pid);
      if (p) setProfileHasPin(!!p.has_pin);
    }).catch(() => {});
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

  const openQuiz = useCallback(
    async (sectionId: string) => {
      const section = sectionsByIdRef.current.get(sectionId);
      setShowQuiz(true);
      setQuizSectionId(sectionId);
      setQuizSectionTitle(section?.title || "Chapter");
      setGrade(null);
      setAnswers({});
      setQuizError("");
      setQuizLoading(true);
      try {
        const { questions: qs } = await kidsApi.getQuiz(documentId, sectionId);
        setQuestions(qs);
      } catch (error) {
        setQuestions([]);
        setQuizError(
          error instanceof KidsApiError && error.status === 403
            ? "Finish this chapter to unlock the quiz."
            : "Quiz unavailable. Try again.",
        );
      } finally {
        setQuizLoading(false);
      }
    },
    [documentId],
  );

  const syncSection = useCallback(
    (loc: string, rawHref: string, rawPercent: number) => {
      const href = rawHref.split(/[?#]/)[0];
      const sectionId = sectionIdByHrefRef.current.get(href);
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
      currentHrefRef.current = href;

      const save = (id: string, scrollPercent: number, completed = false) =>
        kidsApi.updateProgress(documentId, {
          section_id: id,
          section_index: sectionsByIdRef.current.get(id)?.index || 0,
          scroll_percent: scrollPercent,
          epub_cfi: loc,
          section_href: sectionsByIdRef.current.get(id)?.index === section?.index ? href : "",
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
            const complete =
              completedSectionIdsRef.current.size === totalCheckpoints;
            setBookComplete(complete);
            bookCompleteRef.current = complete;
            await openQuiz(sectionId);
          } else {
            await save(sectionId, percent);
          }
        } catch {
          // Position sync is best-effort; the server remains authoritative for completion.
        }
      })();
    },
    [documentId, openQuiz],
  );

  useEffect(() => {
    handleRelocatedRef.current = (location: any) => {
      const href = String(location?.start?.href || "");
      const percent = location?.atEnd
        ? 100
        : Number(location?.start?.percentage ?? 0);
      const cfi = String(location?.start?.cfi || "");
      if (href && cfi) syncSection(cfi, href, percent);
    };
  }, [syncSection]);

  const stopSpeaking = useCallback(() => {
    if (utteranceRef.current) {
      window.speechSynthesis.cancel();
      utteranceRef.current = null;
    }
    setSpeaking(false);
  }, []);

  const speakSelection = useCallback(async () => {
    if (!renditionRef.current) return;
    stopSpeaking();
    const selection = renditionRef.current.getRange?.();
    if (!selection) return;
    const text = selection.toString();
    if (!text.trim()) return;
    const u = new SpeechSynthesisUtterance(text);
    u.rate = narrationRateRef.current;
    u.onend = () => setSpeaking(false);
    u.onerror = () => setSpeaking(false);
    utteranceRef.current = u;
    window.speechSynthesis.speak(u);
    setSpeaking(true);
  }, [stopSpeaking]);

  const handleTranslate = useCallback(async (text: string) => {
    setTranslateText(text);
    setTranslating(true);
    setTranslateResult("");
    try {
      const { translation } = await kidsApi.translate(text);
      setTranslateResult(translation);
    } catch {
      setTranslateResult("Translation unavailable");
    } finally {
      setTranslating(false);
    }
  }, []);

  const submitQuiz = async () => {
    setSubmitting(true);
    setQuizError("");
    try {
      const answerArr = questions.map((_, i) => answers[i] ?? -1);
      const result = await kidsApi.submitQuiz(
        documentId,
        quizSectionId,
        answerArr,
      );
      setGrade(result);
      setStars((s) => s + (result.earned_stars ?? result.stars));
    } catch {
      setQuizError("Quiz unavailable. Try again.");
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "#e0f2ff" }}>
        <div style={{ fontSize: 60 }}>Book</div>
      </div>
    );
  }

 return (
   <div style={{ height: "100vh", display: "flex", flexDirection: "column", background: "#fef9f0" }}>
      {usage?.limit_reached && (
        <div style={popupOverlay}>
          <div style={popupBox}>
            <div style={{ fontSize: 48 }}>Time is up!</div>
            <p style={{ fontSize: 20, color: "#4a3f6b", marginTop: 12 }}>
              Ask a grown-up if you can read more today.
            </p>
          </div>
        </div>
      )}
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
       <button onClick={handleExitClick} style={toolbarBtn}>Books</button>
       <div style={{ flex: 1, minWidth: 0 }}>
         <div style={{ textAlign: "center", fontWeight: 700, fontSize: 18, color: "#4a3f6b", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
           {bookTitle}
         </div>
         <div style={{ height: 6, background: "#e9e4f5", borderRadius: 999, marginTop: 4 }}>
           <div style={{ width: `${progressPercent}%`, height: "100%", background: "#667eea", borderRadius: 999 }} />
         </div>
       </div>
        <div style={{ fontSize: 22 }}>Stars: {stars}</div>
      </div>

      <div style={{ flex: 1, position: "relative", overflow: "hidden" }}>
        <ReactReader
          url={kidsApi.getEpubUrl(documentId)}
          location={location ?? null}
          locationChanged={(loc: string) => {
            setLocation(loc);
          }}
          tocChanged={(t: NavItem[]) => setToc(t)}
          epubInitOptions={{ openAs: "epub" }}
          epubOptions={{ allowScriptedContent: false }}
          getRendition={(rendition: Rendition) => {
            renditionRef.current = rendition;
            rendition.themes.fontSize("120%");
            void rendition.book.ready
              .then(() => rendition.book.locations.generate(1024))
              .then(() => rendition.reportLocation());
            rendition.on("selected", (cfiRange: string, contents: any) => {
              const text = contents.window.getSelection().toString();
              if (text && text.length > 2) {
                currentHrefRef.current = rendition.currentLocation()?.start?.href || "";
              }
            });
            rendition.on("relocated", (location: any) => {
              handleRelocatedRef.current(location);
            });
          }}
        />
      </div>

      <div style={{
        display: "flex",
        gap: 8,
        padding: "10px 16px",
        background: "white",
        boxShadow: "0 -2px 6px rgba(0,0,0,0.06)",
        justifyContent: "center",
        flexShrink: 0,
      }}>
        <button
          style={{ ...bigBtn, background: speaking ? "#fed7d7" : "#e9d8fd" }}
          onClick={speaking ? stopSpeaking : speakSelection}
        >
          {speaking ? "Stop" : "Read Aloud"}
        </button>
        <button
          style={{ ...bigBtn, background: "#bee3f8" }}
          onClick={async () => {
            if (!renditionRef.current) return;
            const sel = renditionRef.current.getRange?.();
            const text = sel?.toString() || "";
            if (text) handleTranslate(text);
          }}
        >
          Translate
        </button>
        <button
          style={{ ...bigBtn, background: "#fed7aa" }}
          onClick={() => void openQuiz(currentSectionIdRef.current)}
        >
          Quiz
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
              Close
            </button>
          </div>
        </div>
      )}

      {showQuiz && (
        <div style={popupOverlay} onClick={() => setShowQuiz(false)}>
          <div style={popupBox} onClick={(e) => e.stopPropagation()}>
            {grade ? (
              <div style={{ textAlign: "center" }}>
                <div style={{ fontSize: 64 }}>
                  {grade.stars >= 3 ? "Great!" : grade.stars >= 2 ? "Good!" : grade.stars >= 1 ? "Nice!" : "Try again!"}
                </div>
                <div style={{ fontSize: 28, fontWeight: 800, color: "#4a3f6b", marginTop: 8 }}>
                  {grade.score} / {grade.total} correct!
                </div>
                <div style={{ fontSize: 32, marginTop: 8 }}>
                  {"*".repeat(grade.stars)}{".".repeat(3 - grade.stars)}
                </div>
                <div style={{ fontSize: 18, color: "#667eea", marginTop: 8 }}>
                  {grade.encouragements[0]}
                </div>
                {grade.per_question.map((q, i) => (
                  <div key={i} style={{
                    marginTop: 12,
                    padding: 12,
                    borderRadius: 12,
                    background: q.correct ? "#f0fff4" : "#fff5f5",
                    textAlign: "left",
                  }}>
                    <span style={{ fontSize: 20 }}>{q.correct ? "Yes" : "No"}</span>
                    <span style={{ fontSize: 14, color: "#4a5568", marginLeft: 8 }}>{q.explanation}</span>
                  </div>
                ))}
                <button
                  style={{ ...bigBtn, marginTop: 16, background: "#667eea", color: "white" }}
                  onClick={() => {
                    setShowQuiz(false);
                    if (bookCompleteRef.current) setShowAchievement(true);
                  }}
                >
                  Done!
                </button>
              </div>
            ) : quizLoading ? (
              <div style={{ textAlign: "center", padding: 40 }}>
                <div style={{ fontSize: 48 }}>?</div>
                <p style={{ fontSize: 18, color: "#667eea" }}>Making your quiz...</p>
              </div>
            ) : quizError ? (
              <div style={{ textAlign: "center", padding: 40 }}>
                <p style={{ fontSize: 18, color: "#4a3f6b" }}>{quizError}</p>
                <button style={{ ...bigBtn, marginTop: 16, background: "#e2e8f0" }} onClick={() => setShowQuiz(false)}>
                  Keep Reading
                </button>
              </div>
            ) : questions.length === 0 ? (
              <div style={{ textAlign: "center", padding: 40 }}>
                <p style={{ fontSize: 18, color: "#e53e3e" }}>Quiz unavailable. Try reading first!</p>
                <button style={{ ...bigBtn, marginTop: 16, background: "#e2e8f0" }} onClick={() => setShowQuiz(false)}>
                  Close
                </button>
              </div>
            ) : (
              <div>
                <h2 style={{ fontSize: 24, fontWeight: 800, color: "#4a3f6b", marginBottom: 16 }}>
                  {quizSectionTitle} Quiz
                </h2>
                {quizError && <p style={{ fontSize: 16, color: "#e53e3e", marginBottom: 12 }}>{quizError}</p>}
                {questions.map((q, qi) => (
                  <div key={qi} style={{ marginBottom: 20 }}>
                    <div style={{ fontSize: 18, fontWeight: 600, color: "#2d3748", marginBottom: 8 }}>
                      {q.question}
                    </div>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                      {q.choices.map((c, ci) => (
                        <button
                          key={ci}
                          onClick={() => setAnswers({ ...answers, [qi]: ci })}
                          style={{
                            padding: "12px 16px",
                            borderRadius: 12,
                            border: answers[qi] === ci ? "3px solid #667eea" : "3px solid #e2e8f0",
                            background: answers[qi] === ci ? "#e9d8fd" : "white",
                            fontSize: 16,
                            cursor: "pointer",
                            textAlign: "left",
                          }}
                        >
                          {c}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
                <button
                  style={{ ...bigBtn, width: "100%", background: "#667eea", color: "white" }}
                  onClick={submitQuiz}
                  disabled={submitting}
                >
                  {submitting ? "Checking..." : "Check Answers!"}
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {bookComplete && showAchievement && (
        <div style={popupOverlay}>
          <div style={popupBox}>
            <div style={{ textAlign: "center" }}>
              <Trophy size={56} color="#d69e2e" style={{ marginBottom: 8 }} />
              <h2 style={{ fontSize: 28, fontWeight: 800, color: "#4a3f6b", margin: 0 }}>
                Book Complete!
              </h2>
              <p style={{ fontSize: 18, color: "#4a5568", marginTop: 12 }}>
                You finished every chapter and earned {stars} stars.
              </p>
              <button
                style={{ ...bigBtn, background: "#667eea", color: "white", marginTop: 12 }}
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

const bigBtn: React.CSSProperties = {
  border: "none",
  borderRadius: 16,
  padding: "14px 28px",
  fontSize: 18,
  fontWeight: 700,
  cursor: "pointer",
  color: "#2d3748",
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
  padding: 28,
  maxWidth: 500,
  width: "90%",
  maxHeight: "80vh",
  overflowY: "auto",
  boxShadow: "0 8px 32px rgba(0,0,0,0.2)",
};
