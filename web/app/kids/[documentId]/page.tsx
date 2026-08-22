"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import { Languages, Volume2, VolumeX } from "lucide-react";
import {
  kidsApi,
  resolveKidsReadingSectionId,
  type KidsWordHint,
  type KidsReadingSection,
  type KidsSafeQuestion,
  type KidsQuizGrade,
} from "@/lib/kids-api";
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

const ReactReader = dynamic(
  () => import("react-reader").then((m) => m.ReactReader),
  { ssr: false, loading: () => <div style={{ textAlign: "center", padding: 40 }}>Opening book...</div> },
);

type Rendition = any;
type NavItem = any;

const ENGLISH_WORD_RE = /([A-Za-z][A-Za-z'-]*)/g;
const ENGLISH_WORD_TEST_RE = /[A-Za-z][A-Za-z'-]*/;

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
  const [questions, setQuestions] = useState<KidsSafeQuestion[]>([]);
  const [quizLoading, setQuizLoading] = useState(false);
  const [answers, setAnswers] = useState<Record<number, number>>({});
  const [grade, setGrade] = useState<KidsQuizGrade | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [speakingId, setSpeakingId] = useState<string | null>(null);
  const [translateText, setTranslateText] = useState<string | null>(null);
  const [translateResult, setTranslateResult] = useState("");
  const [translating, setTranslating] = useState(false);
  const [stars, setStars] = useState(0);
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
  const renditionRef = useRef<Rendition | null>(null);
  const currentHrefRef = useRef<string>("");
  const currentSectionIdRef = useRef<string>("");
  const quizSectionIdRef = useRef<string>("");
  const completedSectionIdsRef = useRef<string[]>([]);
  const shownSectionIdsRef = useRef<string[]>([]);
  const quizLoadTokenRef = useRef(0);
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
        setStars(data.progress?.total_stars || 0);
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
          setLoadError("This book could not be opened. Please go back to Books and try again.");
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
      if (p) setProfileHasPin(!!p.has_pin);
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

  const narrate = useCallback((id: string, text: string) => {
    if (speakingId === id) {
      stopSpeaking();
      return;
    }
    const started = speakKidsText(id, text, {
      onError: () => {
        setSpeakingId(null);
      },
    });
    if (!started) setSpeakingId(null);
  }, [speakingId, stopSpeaking]);

  const speakSelection = useCallback(() => {
    if (!renditionRef.current) return;
    const selection = renditionRef.current.getRange?.();
    if (!selection) return;
    const text = selection.toString();
    if (!text.trim()) return;
    narrate("read-aloud", text);
  }, [narrate]);

  const speakQuizText = useCallback((id: string, text: string) => {
    narrate(id, text);
  }, [narrate]);

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

  const handleLearnClick = useCallback(() => {
    if (renditionRef.current) {
      const selection = renditionRef.current.getRange?.();
      const text = selection?.toString()?.trim();
      if (text) {
        const word = text.split(/\s+/)[0];
        void openWordHint(word, text);
        return;
      }
    }
    stopSpeaking();
    setShowLearn(false);
    setWordHintBusy(false);
    setWordHintData(null);
    setWordHintMessage("Tap any word in the story to explore its meaning!");
    setWordHintState(createInitialWordHintState("Explore"));
  }, [openWordHint, stopSpeaking]);

  const closeLearnQuestions = useCallback(() => {
    quizLoadTokenRef.current += 1;
    setShowLearn(false);
    setQuizLoading(false);
    stopSpeaking();
  }, [stopSpeaking]);

  const loadLearnQuestions = useCallback(async (sectionIdOverride?: string) => {
    const token = ++quizLoadTokenRef.current;
    setWordHintState(null);
    setWordHintData(null);
    setWordHintMessage("");
    setShowLearn(true);
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
      const { questions: qs } = await kidsApi.getQuiz(documentId, sectionId);
      if (token !== quizLoadTokenRef.current) return;
      setQuestions(qs);
    } catch {
      if (token !== quizLoadTokenRef.current) return;
      setQuestions([]);
    } finally {
      if (token === quizLoadTokenRef.current) setQuizLoading(false);
    }
  }, [documentId, stopSpeaking]);

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
      setStars(result.total_stars);
      completedSectionIdsRef.current = result.completed_section_ids || completedSectionIdsRef.current;
    } catch {
      // ignore
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

  if (loadError || !epubUrl) {
    return (
      <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "#e0f2ff" }}>
        <div style={{ textAlign: "center", maxWidth: 360, padding: 24 }}>
          <div style={{ fontSize: 48, marginBottom: 12 }}>Book</div>
          <p style={{ fontSize: 18, color: "#4a3f6b", marginBottom: 20 }}>
            {loadError || "Opening book..."}
          </p>
          <button style={toolbarBtn} onClick={() => router.push("/kids")}>Books</button>
        </div>
      </div>
    );
  }

 return (
   <div style={{ height: "100vh", display: "flex", flexDirection: "column", background: "#fef9f0" }}>
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
       <div style={{ flex: 1, textAlign: "center", fontWeight: 700, fontSize: 18, color: "#4a3f6b", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
         {bookTitle}
       </div>
        <div style={{ fontSize: 22 }}>Stars: {stars}</div>
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
        <ReactReader
          url={epubUrl}
          location={location ?? null}
          locationChanged={(loc: string) => setLocation(loc)}
          tocChanged={(t: NavItem[]) => {
            setToc(t);
            tocRef.current = t;
          }}
          epubInitOptions={{ openAs: "epub" }}
          epubOptions={{ allowScriptedContent: false }}
          getRendition={(rendition: Rendition) => {
            renditionRef.current = rendition;
            rendition.themes.fontSize("120%");
            void rendition.book.ready
              .then(() => rendition.book.locations.generate(256))
              .then(() => rendition.reportLocation());
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
              saveProgress(location?.start?.cfi || "", href);
              const isInitialRelocation = !sawInitialSectionRef.current;
              sawInitialSectionRef.current = true;

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
              if (target && !(isInitialRelocation && target === "current")) {
                const sectionId = target === "previous" ? previousSectionId : currentSectionIdRef.current;
                shownSectionIdsRef.current = [...new Set([...shownSectionIdsRef.current, sectionId])];
                void loadLearnQuestions(sectionId);
              }
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
          style={{ ...bigBtn, background: speakingId === "read-aloud" ? "#fed7d7" : "#e9d8fd" }}
          onClick={speakingId === "read-aloud" ? stopSpeaking : speakSelection}
        >
          {speakingId === "read-aloud" ? "Stop" : "Read Aloud"}
        </button>
        <button style={learnBtn} onClick={handleLearnClick}>
          Learn
        </button>
        <button style={quizBtn} onClick={() => loadLearnQuestions()}>
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

      {wordHintState && (
        <div style={popupOverlay} onClick={closeWordHint}>
          <div style={popupBox} onClick={(e) => e.stopPropagation()}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
              <h2 style={{ fontSize: 30, fontWeight: 800, color: "#4a3f6b", margin: 0 }}>
                {wordHintState.word}
              </h2>
              {wordHintData?.phonetic && (
                <span style={{ fontSize: 15, color: "#7c6f9b" }}>/{wordHintData.phonetic}/</span>
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
              <p style={{ fontSize: 18, color: "#667eea", textAlign: "center", padding: 24 }}>
                Thinking together...
              </p>
            ) : !wordHintData?.available ? (
              <div style={{ textAlign: "center" }}>
                <p style={{ fontSize: 20, color: "#4a3f6b" }}>{wordHintMessage}</p>
                <button style={{ ...bigBtn, background: "#e2e8f0" }} onClick={closeWordHint}>
                  Keep Reading
                </button>
              </div>
            ) : wordHintState.phase === "hint" ? (
              <div>
                <p style={{ fontSize: 20, lineHeight: 1.5, color: "#2d3748" }}>
                  {wordHintData.english_hint}
                </p>
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
                <p style={{ fontSize: 17, color: "#7c6f9b", marginBottom: 10 }}>
                  Guess first. You can listen and think.
                </p>
                <div style={{ display: "grid", gap: 8 }}>
                  {wordHintState.choices.map((choice) => (
                    <div key={choice} style={{ display: "flex", alignItems: "stretch", gap: 6 }}>
                      <button
                        style={{
                          flex: 1,
                          padding: "12px 14px",
                          borderRadius: 12,
                          border: "3px solid #e2e8f0",
                          background: "white",
                          fontSize: 16,
                          textAlign: "left",
                          cursor: "pointer",
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
                  <p style={{ fontSize: 19, fontWeight: 800, color: "#4a3f6b", marginTop: 12 }}>
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
                <div style={{ fontSize: 56 }}>Yes!</div>
                <p style={{ fontSize: 20, color: "#2d3748" }}>{wordHintState.feedback}</p>
                <button
                  style={{ ...bigBtn, background: "#667eea", color: "white" }}
                  onClick={closeWordHint}
                >
                  Keep Reading
                </button>
              </div>
            ) : (
              <div>
                <p style={{ fontSize: 21, fontWeight: 800, color: "#2d3748" }}>
                  {wordHintState.correctChoice}
                </p>
                <p style={{ fontSize: 18, color: "#4a3f6b" }}>{wordHintState.chinese}</p>
                {wordHintState.explanation && (
                  <p style={{ fontSize: 15, color: "#7c6f9b", marginTop: 8 }}>
                    {wordHintState.explanation}
                  </p>
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
            {grade && grade.score === grade.total ? (
              <div style={{ textAlign: "center" }}>
                <div style={{ fontSize: 64 }}>
                  {grade.score === grade.total ? "Great!" : grade.score > 0 ? "Keep thinking!" : "Try again!"}
                </div>
                <div style={{ fontSize: 28, fontWeight: 800, color: "#4a3f6b", marginTop: 8 }}>
                  {grade.score} / {grade.total} correct!
                </div>
                <div style={{ fontSize: 32, marginTop: 8 }}>
                  {"*".repeat(grade.stars)}{".".repeat(3 - grade.stars)}
                </div>
                {grade.new_stars_awarded > 0 && (
                  <div style={{ fontSize: 18, color: "#667eea", marginTop: 8 }}>
                    {grade.encouragements[0]}
                  </div>
                )}
                {grade.per_question.map((q, i) => (
                  <div key={i} style={{
                    marginTop: 12,
                    padding: 12,
                    borderRadius: 12,
                    background: q.correct ? "#f0fff4" : "#fff5f5",
                    textAlign: "left",
                  }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <span style={{ fontSize: 20 }}>{q.correct ? "Yes" : "No"}</span>
                      <button
                        style={speechBtn}
                        title={speakingId === `answer-${i}` ? "Stop answer" : "Read answer"}
                        aria-label={speakingId === `answer-${i}` ? "Stop answer" : "Read answer"}
                        onClick={() => speakQuizText(`answer-${i}`, `${q.correct ? "Yes" : "No"}. ${q.explanation}`)}
                      >
                        {speakingId === `answer-${i}` ? <VolumeX size={15} /> : <Volume2 size={15} />}
                      </button>
                    </div>
                    <div style={{ fontSize: 14, color: "#4a5568", marginTop: 6 }}>{q.explanation}</div>
                  </div>
                ))}
                <button
                  style={{ ...bigBtn, marginTop: 16, background: "#667eea", color: "white" }}
                  onClick={closeLearnQuestions}
                >
                  Done!
                </button>
              </div>
            ) : quizLoading ? (
              <div style={{ textAlign: "center", padding: 40 }}>
                <div style={{ fontSize: 48 }}>?</div>
                <p style={{ fontSize: 18, color: "#667eea" }}>Getting 3 questions...</p>
                <button style={{ ...bigBtn, marginTop: 16, background: "#e2e8f0" }} onClick={closeLearnQuestions}>
                  Close
                </button>
              </div>
            ) : questions.length === 0 ? (
              <div style={{ textAlign: "center", padding: 40 }}>
                <p style={{ fontSize: 18, color: "#e53e3e" }}>Read a little more first!</p>
                <button style={{ ...bigBtn, marginTop: 16, background: "#e2e8f0" }} onClick={closeLearnQuestions}>
                  Close
                </button>
              </div>
            ) : (
              <div>
                <h2 style={{ fontSize: 24, fontWeight: 800, color: "#4a3f6b", marginBottom: 16 }}>
                  Look and Think
                </h2>
                <p style={{ fontSize: 15, color: "#7c6f9b", marginBottom: 16 }}>
                  Look closely, then choose what you think.
                </p>
                {questions.map((q, qi) => (
                  <div key={qi} style={{ marginBottom: 20 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
                      <div style={{ fontSize: 13, fontWeight: 700, color: "#7c6f9b" }}>
                        Question {qi + 1}
                      </div>
                      <button
                        style={speechBtn}
                        title={speakingId === `question-${qi}` ? "Stop question" : "Read question"}
                        aria-label={speakingId === `question-${qi}` ? "Stop question" : "Read question"}
                        onClick={() => speakQuizText(`question-${qi}`, q.question)}
                      >
                        {speakingId === `question-${qi}` ? <VolumeX size={15} /> : <Volume2 size={15} />}
                      </button>
                    </div>
                    <div style={{ fontSize: 18, fontWeight: 600, color: "#2d3748", marginBottom: 8, textAlign: "left" }}>
                      {q.question}
                    </div>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                      {q.choices.map((c, ci) => {
                        const feedback = grade?.per_question?.[qi];
                        const isCorrectChoice = !!feedback?.correct && answers[qi] === ci;
                        return (
                          <div key={ci} style={{ display: "flex", alignItems: "stretch", gap: 6 }}>
                            <button
                              onClick={() => setAnswers({ ...answers, [qi]: ci })}
                              disabled={isCorrectChoice}
                              style={{
                                flex: 1,
                                padding: "12px 14px",
                                borderRadius: 12,
                                border: answers[qi] === ci ? "3px solid #667eea" : "3px solid #e2e8f0",
                                background: answers[qi] === ci ? "#e9d8fd" : "white",
                                fontSize: 16,
                                cursor: isCorrectChoice ? "default" : "pointer",
                                textAlign: "left",
                              }}
                            >
                              {c}
                            </button>
                            <button
                              style={speechBtn}
                              title={speakingId === `choice-${qi}-${ci}` ? `Stop ${c}` : `Read ${c}`}
                              aria-label={speakingId === `choice-${qi}-${ci}` ? `Stop ${c}` : `Read ${c}`}
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
                        Think again
                      </div>
                    )}
                  </div>
                ))}
                <button
                  style={{ ...bigBtn, width: "100%", background: "#667eea", color: "white" }}
                  onClick={submitLearnAnswers}
                  disabled={submitting || questions.some((_, i) => answers[i] === undefined)}
                >
                  {submitting ? "Checking..." : grade && grade.score < grade.total ? "Try Again" : "Check My Thinking"}
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

const bigBtn: React.CSSProperties = {
  border: "none",
  borderRadius: 16,
  padding: "14px 28px",
  fontSize: 18,
  fontWeight: 700,
  cursor: "pointer",
  color: "#2d3748",
};

const learnBtn: React.CSSProperties = {
  ...bigBtn,
  background: "#fed7aa",
  minWidth: 130,
};

const quizBtn: React.CSSProperties = {
  ...bigBtn,
  background: "#c7d2fe",
  minWidth: 130,
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
  color: "#667eea",
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
  padding: 28,
  maxWidth: 500,
  width: "90%",
  maxHeight: "80vh",
  overflowY: "auto",
  boxShadow: "0 8px 32px rgba(0,0,0,0.2)",
};
