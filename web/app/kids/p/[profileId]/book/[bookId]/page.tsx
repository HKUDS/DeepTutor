"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import {
  kidsApi,
  type KidsInteractiveBookProgress,
  type KidsInteractivePage,
  type KidsInteractiveBlock,
  type KidsInteractiveQuizGrade,
} from "@/lib/kids-api";
import {
  Volume2,
  VolumeX,
  Sparkles,
  ChevronLeft,
  ChevronRight,
  CheckCircle2,
  HelpCircle,
  Trophy,
} from "lucide-react";

export default function KidsInteractiveBookReader() {
  const router = useRouter();
  const params = useParams();
  const profileId = params.profileId as string;
  const bookId = params.bookId as string;

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [bookTitle, setBookTitle] = useState("");
  const [allPages, setAllPages] = useState<{ id: string; title: string; chapterTitle: string }[]>([]);
  const [currentPageIndex, setCurrentPageIndex] = useState(0);
  const [currentPage, setCurrentPage] = useState<KidsInteractivePage | null>(null);
  const [progress, setProgress] = useState<KidsInteractiveBookProgress | null>(null);

  // Quiz state: blockId -> answers / grade / loading
  const [quizAnswers, setQuizAnswers] = useState<Record<string, number[]>>({});
  const [quizGrades, setQuizGrades] = useState<Record<string, KidsInteractiveQuizGrade>>({});
  const [submittingQuiz, setSubmittingQuiz] = useState<Record<string, boolean>>({});

  // Audio / TTS state
  const [speakingBlockId, setSpeakingBlockId] = useState<string | null>(null);

  // Celebration state
  const [celebrateStars, setCelebrateStars] = useState<number | null>(null);

  const loadPageContent = useCallback(async (pageId: string) => {
    try {
      const res = await kidsApi.getInteractivePage(bookId, pageId);
      setCurrentPage(res.page);
      setProgress(res.progress);
      const answersMap: Record<string, number[]> = {};
      for (const blk of res.page.blocks) {
        if (blk.type === "quiz") {
          const qs = (blk.payload.questions as unknown[]) || [];
          answersMap[blk.id] = new Array(qs.length).fill(-1);
        }
      }
      setQuizAnswers((prev) => ({ ...prev, ...answersMap }));
    } catch (err: unknown) {
      console.error("Failed to load page:", err);
    }
  }, [bookId]);

  // Load book manifest and determine initial page
  const loadBook = useCallback(async () => {
    try {
      setLoading(true);
      const data = await kidsApi.getInteractiveBook(bookId);
      setBookTitle(data.book.title || "Interactive Book");
      setProgress(data.progress);

      const pagesList: { id: string; title: string; chapterTitle: string }[] = [];
      if (data.spine && data.spine.chapters) {
        for (const ch of data.spine.chapters) {
          if (ch.page_ids && ch.page_ids.length > 0) {
            for (const pid of ch.page_ids) {
              pagesList.push({
                id: pid,
                title: pid,
                chapterTitle: ch.title || "Chapter",
              });
            }
          }
        }
      }
      setAllPages(pagesList);

      if (pagesList.length > 0) {
        let initialIdx = 0;
        if (data.progress.current_page_id) {
          const foundIdx = pagesList.findIndex((p) => p.id === data.progress.current_page_id);
          if (foundIdx >= 0) initialIdx = foundIdx;
        }
        setCurrentPageIndex(initialIdx);
        await loadPageContent(pagesList[initialIdx].id);
      } else {
        setError("This book has no pages available yet.");
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to load book";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [bookId, loadPageContent]);

  useEffect(() => {
    loadBook();
  }, [loadBook]);

  // Navigate pages
  const goToPage = async (newIdx: number) => {
    if (newIdx < 0 || newIdx >= allPages.length) return;
    if (typeof window !== "undefined" && window.speechSynthesis) {
      window.speechSynthesis.cancel();
    }
    setSpeakingBlockId(null);
    setCurrentPageIndex(newIdx);
    const targetPage = allPages[newIdx];
    await loadPageContent(targetPage.id);
    try {
      const updated = await kidsApi.updateInteractiveProgress(bookId, {
        page_id: targetPage.id,
        page_order: newIdx,
      });
      setProgress(updated.progress);
    } catch {}
  };

  // TTS Read Aloud
  const speakText = (blockId: string, text: string) => {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) return;
    if (speakingBlockId === blockId) {
      window.speechSynthesis.cancel();
      setSpeakingBlockId(null);
      return;
    }
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = 0.85;
    utterance.onend = () => setSpeakingBlockId(null);
    utterance.onerror = () => setSpeakingBlockId(null);
    setSpeakingBlockId(blockId);
    window.speechSynthesis.speak(utterance);
  };

  // Submit Quiz Block
  const handleQuizSubmit = async (blockId: string) => {
    if (!currentPage) return;
    const answers = quizAnswers[blockId] || [];
    setSubmittingQuiz((prev) => ({ ...prev, [blockId]: true }));
    try {
      const grade = await kidsApi.submitInteractiveQuiz(bookId, {
        page_id: currentPage.id,
        block_id: blockId,
        answers,
      });
      setQuizGrades((prev) => ({ ...prev, [blockId]: grade }));
      setProgress(grade.progress);
      if (grade.new_stars_awarded > 0) {
        setCelebrateStars(grade.new_stars_awarded);
        setTimeout(() => setCelebrateStars(null), 3000);
      }
    } catch (err) {
      console.error("Quiz submission failed:", err);
    } finally {
      setSubmittingQuiz((prev) => ({ ...prev, [blockId]: false }));
    }
  };

  if (loading) {
    return (
      <div style={S.center}>
        <div style={S.spinner}>✨ 正在打开数学探险书...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div style={S.container}>
        <div style={S.errorCard}>
          <h2 style={{ fontSize: 24, color: "#c53030" }}>哎呀，遇到了一点问题</h2>
          <p style={{ color: "#4a5568", marginTop: 8 }}>{error}</p>
          <button style={S.btnPrimary} onClick={() => router.push(`/kids/p/${profileId}`)}>
            返回书架 👈
          </button>
        </div>
      </div>
    );
  }

  const isCompleted = currentPage && progress?.completed_page_ids.includes(currentPage.id);

  return (
    <div style={S.container}>
      {/* Floating Star Celebration Banner */}
      {celebrateStars !== null && (
        <div style={S.celebrationOverlay}>
          <div style={S.celebrationBox}>
            <Trophy size={48} color="#d69e2e" />
            <h2 style={{ margin: "12px 0 4px 0", color: "#744210" }}>太棒啦！</h2>
            <p style={{ margin: 0, fontSize: 18, color: "#b7791f" }}>
              获得 +{celebrateStars} 颗新星星 ⭐！
            </p>
          </div>
        </div>
      )}

      {/* Top Navigation Bar */}
      <header style={S.header}>
        <button style={S.backBtn} onClick={() => router.push(`/kids/p/${profileId}`)} title="返回书架">
          <ChevronLeft size={28} color="#4a3f6b" />
        </button>
        <div style={S.headerCenter}>
          <div style={S.bookTitle}>{bookTitle}</div>
          <div style={S.pageProgressText}>
            第 {currentPageIndex + 1} / {allPages.length} 页
          </div>
        </div>
        <div style={S.starBadge}>
          ⭐ <span style={{ fontWeight: 800 }}>{progress?.total_stars || 0}</span>
        </div>
      </header>

      {/* Main Content Area */}
      <main style={S.mainContent}>
        {currentPage && (
          <div style={S.pageCard}>
            <div style={S.pageTitleRow}>
              <h1 style={S.pageHeading}>{currentPage.title || `第 ${currentPageIndex + 1} 节`}</h1>
              {isCompleted && (
                <span style={S.completedBadge}>
                  <CheckCircle2 size={16} color="#38a169" /> 已完成
                </span>
              )}
            </div>

            {/* Block List */}
            <div style={S.blockList}>
              {currentPage.blocks.map((block) => (
                <div key={block.id} style={S.blockWrapper}>
                  {renderBlock(
                    block,
                    speakText,
                    speakingBlockId,
                    quizAnswers[block.id] || [],
                    (qIdx, choiceIdx) => {
                      setQuizAnswers((prev) => {
                        const current = [...(prev[block.id] || [])];
                        current[qIdx] = choiceIdx;
                        return { ...prev, [block.id]: current };
                      });
                    },
                    quizGrades[block.id],
                    submittingQuiz[block.id] || false,
                    () => handleQuizSubmit(block.id)
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </main>

      {/* Bottom Sticky Page Switcher */}
      <footer style={S.footer}>
        <button
          style={{ ...S.navBtn, opacity: currentPageIndex <= 0 ? 0.4 : 1 }}
          disabled={currentPageIndex <= 0}
          onClick={() => goToPage(currentPageIndex - 1)}
        >
          <ChevronLeft size={22} /> 上一页
        </button>

        <div style={S.pageDots}>
          {allPages.map((_, idx) => (
            <button
              key={idx}
              style={{
                ...S.dot,
                background: idx === currentPageIndex ? "#667eea" : "#cbd5e0",
                transform: idx === currentPageIndex ? "scale(1.3)" : "scale(1)",
              }}
              onClick={() => goToPage(idx)}
              aria-label={`跳转到第 ${idx + 1} 页`}
            />
          ))}
        </div>

        <button
          style={{
            ...S.navBtn,
            ...S.btnPrimary,
            opacity: currentPageIndex >= allPages.length - 1 ? 0.5 : 1,
          }}
          disabled={currentPageIndex >= allPages.length - 1}
          onClick={() => goToPage(currentPageIndex + 1)}
        >
          下一页 <ChevronRight size={22} />
        </button>
      </footer>
    </div>
  );
}

// ── Secure Block Rendering ──────────────────────────────────────────────────

function renderBlock(
  block: KidsInteractiveBlock,
  speakText: (id: string, text: string) => void,
  speakingId: string | null,
  answers: number[],
  onSelectChoice: (qIdx: number, choiceIdx: number) => void,
  grade: KidsInteractiveQuizGrade | undefined,
  submitting: boolean,
  onSubmitQuiz: () => void
) {
  const payload = block.payload || {};

  // 1. Text Block
  if (block.type === "text" || block.type === "section" || block.type === "callout") {
    const text = (payload.text as string) || (payload.content as string) || (payload.markdown as string) || "";
    const isSpeaking = speakingId === block.id;
    return (
      <div style={S.textBlock}>
        <div style={S.textHeader}>
          {block.title && <h3 style={S.blockHeading}>{block.title}</h3>}
          <button
            style={S.speakBtn}
            onClick={() => speakText(block.id, text)}
            title={isSpeaking ? "停止朗读" : "语音朗读"}
          >
            {isSpeaking ? <VolumeX size={20} color="#e53e3e" /> : <Volume2 size={20} color="#667eea" />}
            <span style={{ fontSize: 13, marginLeft: 4 }}>{isSpeaking ? "停止" : "读给我听"}</span>
          </button>
        </div>
        <div style={S.textContent}>{text}</div>
      </div>
    );
  }

  // 2. Animation Block
  if (block.type === "animation") {
    const videoUrl = (payload.video_url as string) || (payload.url as string) || "";
    const caption = (payload.caption as string) || (payload.description as string) || "";
    return (
      <div style={S.animationBlock}>
        <div style={S.mediaHeader}>
          <Sparkles size={20} color="#805ad5" />
          <span style={S.mediaBadge}>数学动画演示</span>
        </div>
        {videoUrl ? (
          <video
            src={videoUrl}
            controls
            playsInline
            preload="metadata"
            style={S.videoPlayer}
          />
        ) : (
          <div style={S.placeholderMedia}>动画准备中...</div>
        )}
        {caption && <p style={S.captionText}>{caption}</p>}
      </div>
    );
  }

  // 3. Figure Block (Strictly rendered as image, never dangerouslySetInnerHTML)
  if (block.type === "figure") {
    const svgContent = payload.svg as string;
    const imgUrl = payload.image_url as string;
    const caption = (payload.caption as string) || "";
    // Safe image source: if SVG string is provided, encode as data URI for <img> tag (non-executable)
    const safeSrc = imgUrl || (svgContent ? `data:image/svg+xml;utf8,${encodeURIComponent(svgContent)}` : "");

    return (
      <div style={S.figureBlock}>
        {safeSrc ? (
          <img src={safeSrc} alt={caption || "数学图示"} style={S.figureImg} />
        ) : (
          <div style={S.placeholderMedia}>数学图示</div>
        )}
        {caption && <p style={S.captionText}>{caption}</p>}
      </div>
    );
  }

  // 4. Interactive Manipulative Widget (Safe native React controls)
  if (block.type === "interactive") {
    const title = (payload.title as string) || "动手探索";
    const description = (payload.description as string) || (payload.prompt as string) || "";
    return (
      <div style={S.interactiveBlock}>
        <div style={S.mediaHeader}>
          <HelpCircle size={20} color="#319795" />
          <span style={{ ...S.mediaBadge, background: "#e6fffa", color: "#234e52" }}>
            {title}
          </span>
        </div>
        {description && <p style={{ color: "#2d3748", marginBottom: 12 }}>{description}</p>}
        <InteractiveCounterWidget />
      </div>
    );
  }

  // 5. Quiz Block (Gamified Questions)
  if (block.type === "quiz") {
    const questions = (payload.questions as { id?: string; question: string; choices: string[] }[]) || [];
    const allAnswered = questions.length > 0 && answers.length >= questions.length && answers.every((a) => a >= 0);

    return (
      <div style={S.quizBlock}>
        <div style={S.quizHeader}>
          <Trophy size={24} color="#d69e2e" />
          <h3 style={S.quizTitle}>闯关挑战小测验</h3>
        </div>

        {questions.map((q, qIdx) => {
          const qGrade = grade?.per_question ? grade.per_question[qIdx] : undefined;
          return (
            <div key={q.id || qIdx} style={S.questionCard}>
              <div style={S.questionText}>
                <span style={S.questionNum}>{qIdx + 1}.</span> {q.question}
              </div>
              <div style={S.choicesGrid}>
                {q.choices.map((choice, cIdx) => {
                  const isSelected = answers[qIdx] === cIdx;
                  return (
                    <button
                      key={cIdx}
                      style={{
                        ...S.choiceBtn,
                        borderColor: isSelected ? "#667eea" : "#e2e8f0",
                        background: isSelected ? "#edf2f7" : "white",
                        fontWeight: isSelected ? 700 : 500,
                      }}
                      onClick={() => onSelectChoice(qIdx, cIdx)}
                    >
                      <span style={S.choicePrefix}>{String.fromCharCode(65 + cIdx)}.</span>
                      {choice}
                    </button>
                  );
                })}
              </div>

              {/* Feedback after grading */}
              {qGrade && (
                <div
                  style={{
                    ...S.feedbackBox,
                    background: qGrade.correct ? "#f0fdf4" : "#fff5f5",
                    borderColor: qGrade.correct ? "#bbf7d0" : "#fed7d7",
                  }}
                >
                  <div style={{ fontWeight: 700, color: qGrade.correct ? "#15803d" : "#c53030" }}>
                    {qGrade.correct ? "🎉 回答正确！" : "💡 再想一想："}
                  </div>
                  {qGrade.explanation && (
                    <div style={{ fontSize: 14, color: "#4a5568", marginTop: 4 }}>
                      {qGrade.explanation}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}

        {/* Submit Quiz Action */}
        <div style={S.quizFooter}>
          <button
            style={{
              ...S.btnPrimary,
              padding: "12px 32px",
              fontSize: 16,
              opacity: !allAnswered || submitting ? 0.6 : 1,
            }}
            disabled={!allAnswered || submitting}
            onClick={onSubmitQuiz}
          >
            {submitting ? "正在批改..." : grade ? "重新提交 🔄" : "提交答案 ⭐"}
          </button>
          {grade && (
            <div style={S.gradeSummary}>
              得分: {grade.score} / {grade.total} (获得 {grade.stars} 颗星 ⭐)
            </div>
          )}
        </div>
      </div>
    );
  }

  // 6. Flash Cards Block
  if (block.type === "flash_cards") {
    const cards = (payload.cards as { front: string; back: string }[]) || [];
    return (
      <div style={S.flashCardsContainer}>
        {cards.map((card, cIdx) => (
          <FlashCardItem key={cIdx} front={card.front} back={card.back} />
        ))}
      </div>
    );
  }

  return null;
}

// Sub-component for safe interactive manipulatives (Number/Counter widget)
function InteractiveCounterWidget() {
  const [count, setCount] = useState(3);
  return (
    <div style={S.counterContainer}>
      <div style={{ fontSize: 15, fontWeight: 700, color: "#2d3748", marginBottom: 8 }}>
        点击按钮数一数，观察数量变化：
      </div>
      <div style={S.counterRow}>
        <button
          style={S.counterBtn}
          onClick={() => setCount(Math.max(0, count - 1))}
          disabled={count <= 0}
        >
          - 减 1
        </button>
        <span style={S.counterVal}>{count}</span>
        <button
          style={S.counterBtn}
          onClick={() => setCount(Math.min(20, count + 1))}
          disabled={count >= 20}
        >
          + 加 1
        </button>
      </div>
      <div style={S.dotGrid}>
        {Array.from({ length: count }).map((_, i) => (
          <span key={i} style={S.visualDot}>
            🍎
          </span>
        ))}
      </div>
    </div>
  );
}

// Sub-component for interactive flash cards
function FlashCardItem({ front, back }: { front: string; back: string }) {
  const [flipped, setFlipped] = useState(false);
  return (
    <button
      style={{
        ...S.flashCard,
        background: flipped ? "#fef3c7" : "#ebf8ff",
        borderColor: flipped ? "#f6e05e" : "#bee3f8",
      }}
      onClick={() => setFlipped(!flipped)}
    >
      <div style={{ fontSize: 13, color: "#718096", marginBottom: 4 }}>
        {flipped ? "💡 概念解释 (点击翻转)" : "❓ 考考你 (点击翻转)"}
      </div>
      <div style={{ fontSize: 16, fontWeight: 700, color: "#2d3748" }}>
        {flipped ? back : front}
      </div>
    </button>
  );
}

// ── Styles ─────────────────────────────────────────────────────────────────

const S: Record<string, React.CSSProperties> = {
  center: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    minHeight: "100vh",
    background: "linear-gradient(135deg, #e0f2fe 0%, #fef3c7 100%)",
  },
  spinner: { fontSize: 24, fontWeight: 700, color: "#4338ca" },
  container: {
    minHeight: "100vh",
    background: "linear-gradient(180deg, #f0fdf4 0%, #fef3e7 50%, #eff6ff 100%)",
    display: "flex",
    flexDirection: "column",
  },
  header: {
    position: "sticky",
    top: 0,
    zIndex: 100,
    background: "rgba(255, 255, 255, 0.95)",
    backdropFilter: "blur(8px)",
    padding: "12px 20px",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    boxShadow: "0 2px 8px rgba(0,0,0,0.06)",
  },
  backBtn: {
    background: "#f7fafc",
    border: "1px solid #e2e8f0",
    borderRadius: "50%",
    width: 44,
    height: 44,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    cursor: "pointer",
  },
  headerCenter: { textAlign: "center", flex: 1, margin: "0 12px" },
  bookTitle: { fontSize: 18, fontWeight: 800, color: "#2d3748" },
  pageProgressText: { fontSize: 13, color: "#718096", marginTop: 2 },
  starBadge: {
    background: "#fef3c7",
    borderRadius: 20,
    padding: "6px 14px",
    fontSize: 16,
    color: "#92400e",
    fontWeight: 700,
  },
  mainContent: {
    flex: 1,
    padding: "24px 16px 80px 16px",
    display: "flex",
    justifyContent: "center",
  },
  pageCard: {
    background: "white",
    borderRadius: 24,
    padding: "32px 28px",
    maxWidth: 800,
    width: "100%",
    boxShadow: "0 8px 30px rgba(0,0,0,0.06)",
  },
  pageTitleRow: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 24,
    borderBottom: "2px solid #edf2f7",
    paddingBottom: 16,
  },
  pageHeading: { fontSize: 26, fontWeight: 800, color: "#2d3748", margin: 0 },
  completedBadge: {
    display: "flex",
    alignItems: "center",
    gap: 4,
    fontSize: 14,
    fontWeight: 700,
    color: "#38a169",
    background: "#f0fdf4",
    padding: "4px 12px",
    borderRadius: 16,
  },
  blockList: { display: "flex", flexDirection: "column", gap: 28 },
  blockWrapper: { width: "100%" },
  textBlock: { lineHeight: 1.8, fontSize: 18, color: "#2d3748" },
  textHeader: { display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 },
  blockHeading: { fontSize: 20, fontWeight: 700, color: "#4a5568", margin: 0 },
  speakBtn: {
    display: "flex",
    alignItems: "center",
    background: "#edf2f7",
    border: "none",
    borderRadius: 16,
    padding: "4px 10px",
    cursor: "pointer",
  },
  textContent: { whiteSpace: "pre-wrap" },
  animationBlock: {
    background: "#faf5ff",
    borderRadius: 18,
    padding: 16,
    border: "1px solid #e9d8fd",
  },
  mediaHeader: { display: "flex", alignItems: "center", gap: 6, marginBottom: 10 },
  mediaBadge: {
    background: "#f3e8ff",
    color: "#6b21a8",
    padding: "2px 10px",
    borderRadius: 12,
    fontSize: 13,
    fontWeight: 700,
  },
  videoPlayer: { width: "100%", borderRadius: 12, maxHeight: 420, background: "black" },
  captionText: { fontSize: 14, color: "#718096", textAlign: "center", marginTop: 8 },
  placeholderMedia: {
    height: 180,
    background: "#edf2f7",
    borderRadius: 12,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    color: "#a0aec0",
  },
  figureBlock: {
    background: "#f7fafc",
    borderRadius: 18,
    padding: 16,
    border: "1px solid #e2e8f0",
    textAlign: "center",
  },
  figureImg: { maxWidth: "100%", maxHeight: 350, objectFit: "contain", borderRadius: 8 },
  interactiveBlock: {
    background: "#f0fdfa",
    borderRadius: 18,
    padding: 16,
    border: "1px solid #ccfbf1",
  },
  counterContainer: {
    background: "white",
    borderRadius: 12,
    padding: 16,
    textAlign: "center",
  },
  counterRow: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: 16,
    margin: "12px 0",
  },
  counterBtn: {
    padding: "8px 16px",
    borderRadius: 10,
    border: "1px solid #cbd5e0",
    background: "#f7fafc",
    fontWeight: 700,
    cursor: "pointer",
  },
  counterVal: { fontSize: 28, fontWeight: 800, color: "#2b6cb0" },
  dotGrid: {
    display: "flex",
    flexWrap: "wrap",
    gap: 8,
    justifyContent: "center",
    minHeight: 40,
    padding: 8,
  },
  visualDot: { fontSize: 24 },
  quizBlock: {
    background: "#fffbeb",
    borderRadius: 20,
    padding: 24,
    border: "2px solid #fef3c7",
  },
  quizHeader: { display: "flex", alignItems: "center", gap: 8, marginBottom: 16 },
  quizTitle: { fontSize: 20, fontWeight: 800, color: "#92400e", margin: 0 },
  questionCard: {
    background: "white",
    borderRadius: 16,
    padding: 18,
    marginBottom: 16,
    boxShadow: "0 2px 6px rgba(0,0,0,0.03)",
  },
  questionText: { fontSize: 17, fontWeight: 700, color: "#2d3748", marginBottom: 12 },
  questionNum: { color: "#d69e2e", marginRight: 4 },
  choicesGrid: { display: "flex", flexDirection: "column", gap: 8 },
  choiceBtn: {
    display: "flex",
    alignItems: "center",
    padding: "10px 14px",
    borderRadius: 12,
    border: "2px solid",
    fontSize: 16,
    cursor: "pointer",
    textAlign: "left",
  },
  choicePrefix: { fontWeight: 800, marginRight: 8, color: "#718096" },
  feedbackBox: {
    marginTop: 12,
    padding: 12,
    borderRadius: 10,
    border: "1px solid",
  },
  quizFooter: { display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 16 },
  gradeSummary: { fontSize: 16, fontWeight: 700, color: "#92400e" },
  flashCardsContainer: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 14 },
  flashCard: {
    padding: 20,
    borderRadius: 16,
    border: "2px solid",
    cursor: "pointer",
    textAlign: "center",
  },
  footer: {
    position: "fixed",
    bottom: 0,
    left: 0,
    right: 0,
    background: "rgba(255, 255, 255, 0.95)",
    backdropFilter: "blur(8px)",
    padding: "12px 24px",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    boxShadow: "0 -2px 10px rgba(0,0,0,0.05)",
  },
  navBtn: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    padding: "10px 20px",
    borderRadius: 14,
    border: "1px solid #e2e8f0",
    background: "white",
    fontSize: 16,
    fontWeight: 700,
    color: "#4a5568",
    cursor: "pointer",
  },
  btnPrimary: {
    background: "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
    color: "white",
    border: "none",
    cursor: "pointer",
    borderRadius: 12,
    padding: "10px 20px",
    fontWeight: 700,
  },
  pageDots: { display: "flex", gap: 6, alignItems: "center" },
  dot: { width: 10, height: 10, borderRadius: "50%", border: "none", cursor: "pointer" },
  celebrationOverlay: {
    position: "fixed",
    inset: 0,
    background: "rgba(0,0,0,0.3)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    zIndex: 999,
  },
  celebrationBox: {
    background: "white",
    borderRadius: 24,
    padding: "28px 48px",
    textAlign: "center",
    boxShadow: "0 10px 30px rgba(0,0,0,0.2)",
  },
  errorCard: {
    background: "white",
    borderRadius: 20,
    padding: 32,
    textAlign: "center",
    maxWidth: 400,
    marginTop: 80,
  },
};
