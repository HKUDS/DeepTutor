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
import SimpleMarkdownRenderer from "@/components/common/SimpleMarkdownRenderer";
import { Mermaid } from "@/components/Mermaid";
import {
  speakKidsText,
  stopKidsSpeech,
  subscribeKidsSpeechState,
} from "@/lib/kids-learning/pronunciation";

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

  useEffect(() => {
    return subscribeKidsSpeechState((state) => {
      if (!state.isPlaying) {
        setSpeakingBlockId(null);
      }
    });
  }, []);

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
    stopKidsSpeech();
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
    if (speakingBlockId === blockId) {
      stopKidsSpeech();
      setSpeakingBlockId(null);
      return;
    }
    setSpeakingBlockId(blockId);
    speakKidsText(blockId, text, {
      onError: () => setSpeakingBlockId(null),
      onEnd: () => setSpeakingBlockId(null),
    });
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

  // 1. Callout Block (Distinct highlighted tip / key idea card)
  if (block.type === "callout") {
    const title = block.title || (payload.label as string) || "核心要点";
    const body = (payload.body as string) || (payload.text as string) || "";
    const isSpeaking = speakingId === block.id;
    return (
      <div style={S.calloutBlock}>
        <div style={S.textHeader}>
          <div style={S.mediaHeader}>
            <Sparkles size={20} color="#d97706" />
            <span style={{ ...S.mediaBadge, background: "#fef3c7", color: "#92400e" }}>
              {title}
            </span>
          </div>
          <button
            style={S.speakBtn}
            onClick={() => speakText(block.id, body)}
            title={isSpeaking ? "停止朗读" : "语音朗读"}
          >
            {isSpeaking ? <VolumeX size={20} color="#e53e3e" /> : <Volume2 size={20} color="#667eea" />}
            <span style={{ fontSize: 13, marginLeft: 4 }}>{isSpeaking ? "停止" : "读给我听"}</span>
          </button>
        </div>
        <div style={S.calloutContent}>
          <SimpleMarkdownRenderer content={body} className="text-[17px] leading-8 text-[#78350f]" />
        </div>
      </div>
    );
  }

  // 2. Text & Section Block
  if (block.type === "text" || block.type === "section") {
    const text = readableBlockText(payload);
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
        <div style={S.textContent}>
          <SimpleMarkdownRenderer content={text} className="text-[17px] leading-8" />
        </div>
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
    const chartCode =
      payload.render_type === "mermaid"
        ? typeof payload.code === "string"
          ? payload.code
          : ((payload.code as { content?: string })?.content || "")
        : "";
    // Safe image source: if SVG string is provided, encode as data URI for <img> tag (non-executable)
    const safeSrc = imgUrl || (svgContent ? `data:image/svg+xml;utf8,${encodeURIComponent(svgContent)}` : "");

    return (
      <div style={S.figureBlock}>
        {chartCode ? (
          <Mermaid chart={chartCode} className="bg-white" />
        ) : safeSrc ? (
          <img src={safeSrc} alt={caption || "数学图示"} style={S.figureImg} />
        ) : (
          <div style={S.placeholderMedia}>数学图示</div>
        )}
        {caption && <p style={S.captionText}>{caption}</p>}
      </div>
    );
  }

  if (block.type === "code") {
    const code = (payload.code as string) || "";
    const explanation = (payload.explanation as string) || "";
    return (
      <QuantumCodeRunnerWidget
        code={code}
        explanation={explanation}
        title={block.title}
      />
    );
  }

  // 4. Interactive Manipulative Widget (Safe native React controls)
  if (block.type === "interactive") {
    const title = (payload.title as string) || "动手探索：双缝干涉量子实验室";
    const description = (payload.description as string) || (payload.prompt as string) || "";
    return (
      <div style={S.interactiveBlock}>
        <div style={S.mediaHeader}>
          <HelpCircle size={20} color="#318795" />
          <span style={{ ...S.mediaBadge, background: "#e6fffa", color: "#234e52" }}>
            {title}
          </span>
        </div>
        {description && <p style={{ color: "#2d3748", marginBottom: 12 }}>{description}</p>}
        <DoubleSlitLabWidget payload={payload} />
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

function readableBlockText(payload: Record<string, unknown>): string {
  const directText =
    (payload.text as string) ||
    (payload.content as string) ||
    (payload.markdown as string);
  if (directText) return directText;

  const intro = (payload.intro as string) || "";
  const subsections = (payload.subsections as Record<string, unknown>[]) || [];
  const subsectionText = subsections
    .map((subsection) => {
      const heading = (subsection.heading as string) || "";
      const body = (subsection.body as string) || "";
      if (!heading) return body;
      if (body.startsWith("### ") || body.startsWith("## ") || body.startsWith("# ")) {
        return body;
      }
      return `### ${heading}\n\n${body}`;
    })
    .filter(Boolean);
  const takeaway = (payload.key_takeaway as string) || "";
  const takeawayFormatted = takeaway ? `> 💡 **小结**：${takeaway}` : "";

  return [intro, ...subsectionText, takeawayFormatted].filter(Boolean).join("\n\n");
}

function DoubleSlitLabWidget({ payload }: { payload: Record<string, unknown> }) {
  const [photonCount, setPhotonCount] = useState(0);
  const [color, setColor] = useState<"red" | "green" | "blue">("green");
  const [slitGap, setSlitGap] = useState<"narrow" | "wide">("narrow");
  const [hits, setHits] = useState<number[]>([]);
  const [isFiring, setIsFiring] = useState(false);

  const colorHex = color === "red" ? "#ef4444" : color === "green" ? "#10b981" : "#3b82f6";

  const firePhotons = (amount = 10) => {
    const newHits: number[] = [];
    const fringeFreq = slitGap === "narrow" ? 0.08 : 0.14;

    for (let i = 0; i < amount; i++) {
      let x = 0;
      for (let attempt = 0; attempt < 40; attempt++) {
        const candidateX = (Math.random() - 0.5) * 160;
        const env = Math.exp(-(candidateX * candidateX) / (2 * 45 * 45));
        const wave = Math.cos(candidateX * fringeFreq);
        const prob = env * wave * wave;
        if (Math.random() < prob) {
          x = candidateX;
          break;
        }
      }
      newHits.push(x);
    }

    setHits((prev) => [...prev.slice(-300), ...newHits]);
    setPhotonCount((prev) => prev + amount);
  };

  useEffect(() => {
    if (!isFiring) return;
    const interval = window.setInterval(() => {
      firePhotons(6);
    }, 100);
    return () => window.clearInterval(interval);
  }, [isFiring, slitGap, color]);

  const clearScreen = () => {
    setHits([]);
    setPhotonCount(0);
    setIsFiring(false);
  };

  return (
    <div style={S.widgetCard}>
      <div style={S.widgetToolbar}>
        <div style={S.toolbarGroup}>
          <span style={S.controlLabel}>光源:</span>
          {(["red", "green", "blue"] as const).map((c) => (
            <button
              key={c}
              style={{
                ...S.colorBtn,
                background: c === "red" ? "#fee2e2" : c === "green" ? "#d1fae5" : "#dbeafe",
                borderColor: color === c ? (c === "red" ? "#dc2626" : c === "green" ? "#059669" : "#2563eb") : "#e2e8f0",
                color: c === "red" ? "#991b1b" : c === "green" ? "#065f46" : "#1e40af",
                fontWeight: color === c ? 800 : 500,
              }}
              onClick={() => setColor(c)}
            >
              {c === "red" ? "红光" : c === "green" ? "绿光" : "蓝光"}
            </button>
          ))}
        </div>

        <div style={S.toolbarGroup}>
          <span style={S.controlLabel}>间距:</span>
          <button
            style={{
              ...S.pillBtn,
              background: slitGap === "narrow" ? "#667eea" : "#edf2f7",
              color: slitGap === "narrow" ? "white" : "#4a5568",
            }}
            onClick={() => { setSlitGap("narrow"); setHits([]); setPhotonCount(0); }}
          >
            窄缝
          </button>
          <button
            style={{
              ...S.pillBtn,
              background: slitGap === "wide" ? "#667eea" : "#edf2f7",
              color: slitGap === "wide" ? "white" : "#4a5568",
            }}
            onClick={() => { setSlitGap("wide"); setHits([]); setPhotonCount(0); }}
          >
            宽缝
          </button>
        </div>

        <div style={S.toolbarGroup}>
          <button
            style={{
              ...S.actionBtn,
              background: isFiring ? "#ef4444" : "#10b981",
              color: "white",
            }}
            onClick={() => setIsFiring(!isFiring)}
          >
            {isFiring ? "⏹ 暂停" : "🚀 持续发射"}
          </button>
          <button style={S.pillBtn} onClick={() => firePhotons(20)}>
            +20 颗
          </button>
          <button style={{ ...S.pillBtn, color: "#718096" }} onClick={clearScreen}>
            清空
          </button>
        </div>
      </div>

      <div style={S.labCanvasContainer}>
        <div style={S.laserEmitter}>
          <div style={{ ...S.laserNozzle, background: colorHex }} />
          <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 4 }}>单光子源</div>
        </div>

        <div style={S.slitsBarrier}>
          <div style={S.barrierWall} />
          <div style={{ ...S.slitHole, height: slitGap === "narrow" ? 8 : 14 }} />
          <div style={{ ...S.barrierCenterBlock, height: slitGap === "narrow" ? 14 : 26 }} />
          <div style={{ ...S.slitHole, height: slitGap === "narrow" ? 8 : 14 }} />
          <div style={S.barrierWall} />
          <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 4 }}>双缝</div>
        </div>

        <div style={S.screenArea}>
          <div style={S.screenDetector}>
            {hits.map((x, idx) => (
              <div
                key={idx}
                style={{
                  position: "absolute",
                  left: "50%",
                  top: `calc(50% + ${x}px)`,
                  width: 3.5,
                  height: 3.5,
                  borderRadius: "50%",
                  background: colorHex,
                  boxShadow: `0 0 3px ${colorHex}`,
                  opacity: 0.85,
                  transform: "translate(-50%, -50%)",
                }}
              />
            ))}
          </div>
          <div style={{ fontSize: 11, fontWeight: 700, color: "#94a3b8", marginTop: 4 }}>
            探测屏（{photonCount} 颗）
          </div>
        </div>
      </div>

      <div style={S.labInsightBox}>
        <div style={{ fontWeight: 700, color: "#115e59", marginBottom: 2 }}>
          💡 实验观察结论：
        </div>
        <div style={{ fontSize: 14, color: "#134e4a", lineHeight: 1.6 }}>
          即便每次只发射<b>单个光子</b>，只要光子数量累加，探测屏上依然会慢慢显现出<b>明暗相间的波干涉条纹</b>！这生动证明了微观粒子的波粒二象性。
        </div>
      </div>
    </div>
  );
}

function QuantumCodeRunnerWidget({
  code,
  explanation,
  title,
}: {
  code: string;
  explanation: string;
  title?: string;
}) {
  const [isRunning, setIsRunning] = useState(false);
  const [runsCount, setRunsCount] = useState<number>(1);
  const [history, setHistory] = useState<{ heads: number; tails: number; logs: string[] } | null>(null);

  const handleRun = () => {
    setIsRunning(true);
    setTimeout(() => {
      let heads = 0;
      let tails = 0;
      const logs: string[] = [];
      for (let i = 0; i < runsCount; i++) {
        const isHead = Math.random() < 0.5;
        if (isHead) heads++;
        else tails++;
        if (runsCount <= 10) {
          logs.push(`观测测量 #${i + 1}：硬币塌缩为【${isHead ? "正面 🪙" : "反面 🌕"}】`);
        }
      }
      if (runsCount > 10) {
        logs.push(`完成 ${runsCount} 次连续量子测量：正面 ${heads} 次 (${Math.round((heads / runsCount) * 100)}%)，反面 ${tails} 次 (${Math.round((tails / runsCount) * 100)}%)`);
      }
      setHistory({ heads, tails, logs });
      setIsRunning(false);
    }, 350);
  };

  const total = history ? history.heads + history.tails : 0;
  const headPct = total > 0 ? Math.round((history!.heads / total) * 100) : 50;

  return (
    <div style={S.codeBlock}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12, flexWrap: "wrap", gap: 8 }}>
        <div style={S.mediaHeader}>
          <HelpCircle size={20} color="#0d9488" />
          <span style={{ ...S.mediaBadge, background: "#ccfbf1", color: "#115e59" }}>
            {title || "可运行代码实验"}
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ fontSize: 13, color: "#64748b" }}>模拟:</span>
          {[1, 10, 100].map((n) => (
            <button
              key={n}
              style={{
                padding: "3px 8px",
                borderRadius: 8,
                border: "1px solid",
                borderColor: runsCount === n ? "#0d9488" : "#cbd5e1",
                background: runsCount === n ? "#f0fdfa" : "white",
                color: runsCount === n ? "#0f766e" : "#64748b",
                fontSize: 12,
                fontWeight: runsCount === n ? 700 : 500,
                cursor: "pointer",
              }}
              onClick={() => setRunsCount(n)}
            >
              {n}次
            </button>
          ))}
          <button
            style={{
              padding: "5px 12px",
              borderRadius: 8,
              border: "none",
              background: isRunning ? "#94a3b8" : "#0d9488",
              color: "white",
              fontSize: 13,
              fontWeight: 700,
              cursor: isRunning ? "not-allowed" : "pointer",
            }}
            disabled={isRunning}
            onClick={handleRun}
          >
            {isRunning ? "运行中..." : "▶ 运行模拟"}
          </button>
        </div>
      </div>

      <pre style={S.codePre}>
        <code>{code}</code>
      </pre>

      {history && (
        <div style={S.terminalBox}>
          <div style={S.terminalHeader}>🖥️ 模拟运行结果输出：</div>
          {history.logs.map((log, idx) => (
            <div key={idx} style={S.terminalLine}>
              {log}
            </div>
          ))}

          {total > 1 && (
            <div style={{ marginTop: 10, background: "#082f49", padding: 8, borderRadius: 8 }}>
              <div style={{ fontSize: 12, color: "#38bdf8", marginBottom: 4, display: "flex", justifyContent: "space-between" }}>
                <span>正面: {history.heads} ({headPct}%)</span>
                <span>反面: {history.tails} ({100 - headPct}%)</span>
              </div>
              <div style={{ height: 8, background: "#1e293b", borderRadius: 4, overflow: "hidden", display: "flex" }}>
                <div style={{ width: `${headPct}%`, background: "#38bdf8", transition: "width 0.3s" }} />
                <div style={{ width: `${100 - headPct}%`, background: "#f59e0b", transition: "width 0.3s" }} />
              </div>
            </div>
          )}
        </div>
      )}

      {explanation && <p style={S.captionText}>{explanation}</p>}
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
    height: "100vh",
    overflowY: "auto",
    background: "linear-gradient(180deg, #f0fdf4 0%, #fef3e7 50%, #eff6ff 100%)",
    display: "flex",
    flexDirection: "column",
    WebkitOverflowScrolling: "touch",
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
    padding: "24px 16px 140px 16px",
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
  codeBlock: {
    background: "#f0fdfa",
    borderRadius: 18,
    padding: 16,
    border: "1px solid #ccfbf1",
  },
  codePre: {
    margin: 0,
    padding: 16,
    borderRadius: 12,
    background: "#12343b",
    color: "#d9f8f2",
    overflowX: "auto",
    fontSize: 14,
    lineHeight: 1.6,
  },
  calloutBlock: {
    background: "#fffdf0",
    borderRadius: 18,
    padding: "20px 22px",
    border: "1px solid #fef08a",
    boxShadow: "0 2px 10px rgba(234, 179, 8, 0.05)",
  },
  calloutContent: { marginTop: 8 },
  interactiveBlock: {
    background: "#f0fdfa",
    borderRadius: 18,
    padding: 16,
    border: "1px solid #ccfbf1",
  },
  widgetCard: {
    background: "white",
    borderRadius: 16,
    padding: 18,
  },
  widgetToolbar: {
    display: "flex",
    flexWrap: "wrap",
    gap: 12,
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 14,
    background: "#f8fafc",
    padding: 10,
    borderRadius: 12,
  },
  toolbarGroup: { display: "flex", alignItems: "center", gap: 6 },
  controlLabel: { fontSize: 12, fontWeight: 700, color: "#475569" },
  colorBtn: { padding: "3px 8px", borderRadius: 6, border: "1.5px solid", fontSize: 12, cursor: "pointer" },
  pillBtn: { padding: "4px 9px", borderRadius: 6, border: "1px solid #cbd5e1", fontSize: 12, fontWeight: 600, cursor: "pointer" },
  actionBtn: { padding: "5px 12px", borderRadius: 8, border: "none", fontSize: 12, fontWeight: 700, cursor: "pointer" },
  labCanvasContainer: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    background: "#091428",
    borderRadius: 14,
    height: 220,
    padding: "0 20px",
    position: "relative",
    overflow: "hidden",
  },
  laserEmitter: { display: "flex", flexDirection: "column", alignItems: "center" },
  laserNozzle: { width: 24, height: 14, borderRadius: "4px 0 0 4px", boxShadow: "0 0 10px currentColor" },
  slitsBarrier: { display: "flex", flexDirection: "column", alignItems: "center", height: "100%", justifyContent: "center" },
  barrierWall: { width: 8, height: 60, background: "#475569", borderRadius: 2 },
  slitHole: { width: 8, background: "transparent" },
  barrierCenterBlock: { width: 8, background: "#475569", borderRadius: 2 },
  screenArea: { display: "flex", flexDirection: "column", alignItems: "center", height: "100%", justifyContent: "center" },
  screenDetector: {
    width: 120,
    height: 170,
    background: "rgba(15, 23, 42, 0.8)",
    border: "2px solid #334155",
    borderRadius: 8,
    position: "relative",
    overflow: "hidden",
  },
  labInsightBox: {
    marginTop: 12,
    background: "#e6fffa",
    borderRadius: 10,
    padding: "10px 14px",
    border: "1px solid #b2f5ea",
  },
  terminalBox: {
    marginTop: 12,
    background: "#0c1322",
    borderRadius: 12,
    padding: 14,
    fontFamily: "ui-monospace, monospace",
    border: "1px solid #1e293b",
  },
  terminalHeader: { fontSize: 13, fontWeight: 700, color: "#38bdf8", marginBottom: 6 },
  terminalLine: { fontSize: 13, color: "#a5f3fc", lineHeight: 1.6 },
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
