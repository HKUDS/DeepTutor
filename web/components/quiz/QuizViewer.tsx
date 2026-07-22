"use client";

import {
  type ChangeEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  Bookmark,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Eye,
  FolderPlus,
  ImagePlus,
  Loader2,
  MessageSquarePlus,
  Plus,
  RotateCcw,
  Sparkles,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import {
  useAllFollowupThreads,
  useQuizFollowupController,
} from "@/context/QuizFollowupContext";
import {
  isChoiceQuizQuestion,
  isConceptQuizQuestion,
  isFillInBlankQuizQuestion,
  resolveChoiceAnswerKey,
  resolveConceptAnswer,
} from "@/lib/quiz-question-type";
import {
  readFileAsBase64,
  startQuizJudge,
  type QuizJudgeHandle,
} from "@/lib/quiz-judge";
import { type QuizQuestion } from "@/lib/quiz-types";
import {
  addEntryToCategory,
  createCategory,
  listCategories,
  lookupNotebookEntry,
  updateNotebookEntry,
  upsertNotebookEntry,
  type NotebookCategory,
} from "@/lib/notebook-api";
import { recordQuizResults } from "@/lib/session-api";
import { apiUrl } from "@/lib/api";

/** Resolve a possibly-relative AttachmentStore URL to an absolute one so
 *  ``<img src>`` works regardless of the API/frontend port pairing. */
function resolveImageSrc(url: string | null | undefined): string | undefined {
  if (!url) return undefined;
  if (/^(https?:|data:|blob:)/i.test(url)) return url;
  return apiUrl(url);
}

interface QuizViewerProps {
  questions: QuizQuestion[];
  sessionId?: string | null;
  /**
   * The ``turn_id`` of the assistant turn that produced this quiz. Scopes
   * notebook lookups/upserts so two quizzes generated in the same chat
   * session don't share answer state (see issue #487). When absent, the
   * component falls back to legacy session-wide scoping for backward
   * compatibility with already-persisted entries.
   */
  turnId?: string | null;
  language?: string;
}

type AnswerImage = {
  /**
   * Local-only identifier used to key React lists and to remove a
   * specific image. When the image has been persisted server-side the
   * field is replaced with the stable AttachmentStore id.
   */
  id: string;
  /** Base64 (no ``data:`` prefix) when freshly picked client-side. */
  base64: string | null;
  /** AttachmentStore URL once the upsert response confirms persistence. */
  url: string | null;
  filename: string;
  mime: string;
  /** Blob: URL for the local <img> preview when ``base64`` is present. */
  previewUrl: string | null;
};

type AnswerState = {
  selected: string | null;
  typed: string;
  submitted: boolean;
  images: AnswerImage[];
};

const EMPTY_ANSWER: AnswerState = {
  selected: null,
  typed: "",
  submitted: false,
  images: [],
};

function makeAnswerImageId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID().replaceAll("-", "").slice(0, 12);
  }
  return Math.random().toString(36).slice(2, 14);
}

type JudgmentState = {
  text: string;
  isStreaming: boolean;
  error: string | null;
};

const EMPTY_JUDGMENT: JudgmentState = {
  text: "",
  isStreaming: false,
  error: null,
};

type AnswerView = "reference" | "judgment";

function getQuestionKey(question: QuizQuestion, index: number): string {
  return question.question_id || `question_${index + 1}`;
}

function isMultipleChoice(question: QuizQuestion): boolean {
  return (
    isChoiceQuizQuestion(question.question_type) &&
    !!question.options &&
    Object.keys(question.options).length > 0
  );
}

/**
 * Auto-gradable question types: choice, concept (T/F), fill_in_blank.
 * Open-ended types (short_answer, written, coding) are excluded — their
 * answers are graded by the learner against the reference, not by exact
 * string match.
 */
function isAutoGradable(question: QuizQuestion): boolean {
  return (
    isMultipleChoice(question) ||
    isConceptQuizQuestion(question.question_type) ||
    isFillInBlankQuizQuestion(question.question_type)
  );
}

function getUserAnswer(question: QuizQuestion, answer: AnswerState): string {
  // Choice + concept use the ``selected`` field (option key / "true" / "false").
  if (
    isMultipleChoice(question) ||
    isConceptQuizQuestion(question.question_type)
  ) {
    return answer.selected ?? "";
  }
  // Fill-in-blank + free-text types use the typed string.
  return answer.typed.trim();
}

function isAnswerCorrect(question: QuizQuestion, answer: AnswerState): boolean {
  const userAnswer = getUserAnswer(question, answer);
  if (!userAnswer) return false;
  const correct = question.correct_answer.trim();
  if (isMultipleChoice(question)) {
    const correctChoiceKey = resolveChoiceAnswerKey(correct, question.options);
    return (
      userAnswer.toUpperCase() === correctChoiceKey ||
      userAnswer.toUpperCase() === correct.toUpperCase() ||
      userAnswer.toUpperCase() === correct.charAt(0).toUpperCase()
    );
  }
  if (isConceptQuizQuestion(question.question_type)) {
    const correctTF = resolveConceptAnswer(correct);
    return userAnswer.toLowerCase() === correctTF;
  }
  return userAnswer.toLowerCase() === correct.toLowerCase();
}

export default function QuizViewer({
  questions,
  sessionId,
  turnId,
  language = "en",
}: QuizViewerProps) {
  const { t } = useTranslation();
  const followupController = useQuizFollowupController();
  // Read all follow-up threads so we can light up the "N messages" badge
  // and the per-chip dot indicator. Owned by QuizFollowupProvider so
  // QuizFollowupTabBody and QuizViewer stay in sync.
  const followupThreads = useAllFollowupThreads();
  const [idx, setIdx] = useState(0);
  const [answers, setAnswers] = useState<Record<number, AnswerState>>({});
  const lastReportedSignatureRef = useRef("");

  const [entryIds, setEntryIds] = useState<Record<string, number>>({});
  const [bookmarked, setBookmarked] = useState<Record<string, boolean>>({});
  // Captured from the notebook entry on lookup so QuizFollowupTabBody
  // can hydrate prior chat history when the follow-up tab opens.
  const [followupSessionIds, setFollowupSessionIds] = useState<
    Record<string, string>
  >({});
  const [categories, setCategories] = useState<NotebookCategory[]>([]);
  const [categoryDropdownKey, setCategoryDropdownKey] = useState<string | null>(
    null,
  );
  const [newCategoryName, setNewCategoryName] = useState("");
  const [categoryBusy, setCategoryBusy] = useState(false);

  const [judgments, setJudgments] = useState<Record<number, JudgmentState>>({});
  const [answerViews, setAnswerViews] = useState<Record<number, AnswerView>>(
    {},
  );
  // Per-question collapsed state for the Reference / Judgment review
  // block. Default: expanded. Persists per question while the QuizViewer
  // instance is alive.
  const [reviewCollapsed, setReviewCollapsed] = useState<
    Record<number, boolean>
  >({});
  const judgeHandlesRef = useRef<Map<number, QuizJudgeHandle>>(new Map());
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(
    () => () => {
      judgeHandlesRef.current.forEach((handle) => handle.close());
      judgeHandlesRef.current.clear();
    },
    [],
  );

  const q = questions[idx];
  const ans = answers[idx] ?? EMPTY_ANSWER;
  const total = questions.length;
  const navigationProgress = total > 0 ? ((idx + 1) / total) * 100 : 0;
  const questionKey = q ? getQuestionKey(q, idx) : "";
  const completedCount = useMemo(
    () => Object.values(answers).filter((answer) => answer.submitted).length,
    [answers],
  );

  const updateAnswer = useCallback(
    (patch: Partial<AnswerState>) =>
      setAnswers((prev) => ({
        ...prev,
        [idx]: { ...(prev[idx] ?? EMPTY_ANSWER), ...patch },
      })),
    [idx],
  );

  // ── Notebook integration ──────────────────────────────────────

  const refreshEntryId = useCallback(
    async (qKey: string, sId: string, questionIndex?: number) => {
      try {
        const entry = await lookupNotebookEntry(sId, qKey, turnId);
        if (entry) {
          setEntryIds((prev) => ({ ...prev, [qKey]: entry.id }));
          setBookmarked((prev) => ({ ...prev, [qKey]: entry.bookmarked }));
          if (entry.followup_session_id) {
            setFollowupSessionIds((prev) => ({
              ...prev,
              [qKey]: entry.followup_session_id,
            }));
          }
          const persistedImages = (entry.user_answer_images ?? []).map(
            (image) => ({
              id: image.id || makeAnswerImageId(),
              base64: null,
              url: image.url || null,
              filename: image.filename || "answer.png",
              mime: image.mime_type || "image/png",
              previewUrl: null,
            }),
          );
          if (
            questionIndex !== undefined &&
            (entry.user_answer || persistedImages.length > 0)
          ) {
            setAnswers((prev) => {
              if (prev[questionIndex]?.submitted) return prev;
              return {
                ...prev,
                [questionIndex]: {
                  ...EMPTY_ANSWER,
                  selected: entry.user_answer || null,
                  typed: entry.user_answer || "",
                  images: persistedImages,
                  submitted: true,
                },
              };
            });
          }
          // Rehydrate the AI judgment so the learner can keep reading
          // it across page refreshes. We only overwrite when local state
          // is still empty so an in-flight judge run isn't clobbered.
          if (
            questionIndex !== undefined &&
            entry.ai_judgment &&
            entry.ai_judgment.length > 0
          ) {
            setJudgments((prev) => {
              const current = prev[questionIndex];
              if (current?.text || current?.isStreaming) return prev;
              return {
                ...prev,
                [questionIndex]: {
                  text: entry.ai_judgment ?? "",
                  isStreaming: false,
                  error: null,
                },
              };
            });
          }
        }
      } catch {
        /* entry may not exist yet */
      }
    },
    [turnId],
  );

  useEffect(() => {
    if (!sessionId) return;
    questions.forEach((question, i) => {
      const key = getQuestionKey(question, i);
      void refreshEntryId(key, sessionId, i);
    });
  }, [sessionId, questions, refreshEntryId]);

  const handleToggleBookmark = useCallback(async () => {
    if (!q || !sessionId) return;
    const key = getQuestionKey(q, idx);
    const eId = entryIds[key];
    if (!eId) return;
    const next = !bookmarked[key];
    setBookmarked((prev) => ({ ...prev, [key]: next }));
    try {
      await updateNotebookEntry(eId, { bookmarked: next });
    } catch {
      setBookmarked((prev) => ({ ...prev, [key]: !next }));
    }
  }, [bookmarked, entryIds, idx, q, sessionId]);

  const loadCategories = useCallback(async () => {
    try {
      setCategories(await listCategories());
    } catch {
      /* ignore */
    }
  }, []);

  const handleOpenCategoryDropdown = useCallback(() => {
    if (!q) return;
    const key = getQuestionKey(q, idx);
    if (categoryDropdownKey === key) {
      setCategoryDropdownKey(null);
      return;
    }
    setCategoryDropdownKey(key);
    void loadCategories();
  }, [categoryDropdownKey, idx, loadCategories, q]);

  const handleAddToCategory = useCallback(
    async (catId: number) => {
      if (!q) return;
      const key = getQuestionKey(q, idx);
      const eId = entryIds[key];
      if (!eId) return;
      setCategoryBusy(true);
      try {
        await addEntryToCategory(eId, catId);
        setCategoryDropdownKey(null);
      } catch {
        /* ignore */
      }
      setCategoryBusy(false);
    },
    [entryIds, idx, q],
  );

  const handleCreateAndAdd = useCallback(async () => {
    if (!q || !newCategoryName.trim()) return;
    const key = getQuestionKey(q, idx);
    const eId = entryIds[key];
    if (!eId) return;
    setCategoryBusy(true);
    try {
      const cat = await createCategory(newCategoryName.trim());
      await addEntryToCategory(eId, cat.id);
      setNewCategoryName("");
      setCategoryDropdownKey(null);
    } catch {
      /* ignore */
    }
    setCategoryBusy(false);
  }, [entryIds, idx, newCategoryName, q]);

  const isChoice = q ? isMultipleChoice(q) : false;
  const isConcept = q ? isConceptQuizQuestion(q.question_type) : false;
  const isFillBlank = q ? isFillInBlankQuizQuestion(q.question_type) : false;
  const isGradable = q ? isAutoGradable(q) : false;
  const currentUserAnswer = q ? getUserAnswer(q, ans) : "";

  const isCorrect = useMemo(() => {
    if (!q || !ans.submitted) return null;
    return isAnswerCorrect(q, ans);
  }, [ans, q]);

  const submittedResults = useMemo(
    () =>
      questions.flatMap((question, questionIdx) => {
        const answer = answers[questionIdx];
        if (!answer?.submitted) return [];
        return [
          {
            question_id: question.question_id,
            question: question.question,
            question_type: question.question_type,
            options: question.options ?? {},
            user_answer: getUserAnswer(question, answer),
            correct_answer: question.correct_answer,
            explanation: question.explanation ?? "",
            difficulty: question.difficulty ?? "",
            is_correct: isAnswerCorrect(question, answer),
          },
        ];
      }),
    [answers, questions],
  );

  useEffect(() => {
    if (!sessionId || total === 0 || completedCount !== total) return;
    const signature = JSON.stringify(submittedResults);
    if (!signature || signature === lastReportedSignatureRef.current) return;
    lastReportedSignatureRef.current = signature;
    void recordQuizResults(sessionId, submittedResults, turnId)
      .then(() => {
        questions.forEach((question, i) => {
          void refreshEntryId(getQuestionKey(question, i), sessionId);
        });
      })
      .catch((error) => {
        console.error("Failed to record quiz results:", error);
        if (lastReportedSignatureRef.current === signature) {
          lastReportedSignatureRef.current = "";
        }
      });
  }, [
    completedCount,
    questions,
    refreshEntryId,
    sessionId,
    submittedResults,
    total,
    turnId,
  ]);

  const upsertSingleQuestion = useCallback(
    async (
      question: QuizQuestion,
      answer: AnswerState,
      questionIndex: number,
    ) => {
      if (!sessionId) return;
      const key = getQuestionKey(question, questionIndex);
      try {
        const imagePayload = answer.images.map((image) => ({
          id: image.id,
          base64: image.base64 ?? undefined,
          url: image.url ?? undefined,
          filename: image.filename,
          mime_type: image.mime,
        }));
        const entry = await upsertNotebookEntry({
          session_id: sessionId,
          turn_id: turnId || "",
          question_id: question.question_id,
          question: question.question,
          question_type: question.question_type,
          options: question.options ?? {},
          correct_answer: question.correct_answer,
          explanation: question.explanation ?? "",
          difficulty: question.difficulty ?? "",
          user_answer: getUserAnswer(question, answer),
          user_answer_images: imagePayload,
          is_correct: isAnswerCorrect(question, answer),
        });
        setEntryIds((prev) => ({ ...prev, [key]: entry.id }));
        setBookmarked((prev) => ({ ...prev, [key]: entry.bookmarked }));
        // Replace freshly-uploaded ``base64`` images with the
        // AttachmentStore URLs the server hands back, so subsequent
        // upserts don't re-upload the same bytes and the previews can
        // survive a page reload by falling through to ``url``.
        const persisted = entry.user_answer_images ?? [];
        if (persisted.length > 0) {
          setAnswers((prev) => {
            const current = prev[questionIndex];
            if (!current) return prev;
            const byId = new Map(persisted.map((image) => [image.id, image]));
            const nextImages = current.images.map((image) => {
              const match = byId.get(image.id);
              if (!match) return image;
              return {
                ...image,
                url: match.url || image.url,
                // Drop base64 once the server has the bytes.
                base64: null,
              };
            });
            return {
              ...prev,
              [questionIndex]: { ...current, images: nextImages },
            };
          });
        }
      } catch {
        /* best-effort */
      }
    },
    [sessionId, turnId],
  );

  const handleSubmit = () => {
    if (ans.submitted || !q) return;
    const newAnswer = { ...(answers[idx] ?? EMPTY_ANSWER), submitted: true };
    updateAnswer({ submitted: true });
    void upsertSingleQuestion(q, newAnswer, idx);
  };

  const handleReset = () => {
    // Reset typed/selected state but keep an attached image so the learner
    // doesn't have to re-upload it when retrying.
    updateAnswer({ selected: null, typed: "", submitted: false });
    setJudgments((prev) => {
      const next = { ...prev };
      delete next[idx];
      return next;
    });
    setAnswerViews((prev) => {
      const next = { ...prev };
      delete next[idx];
      return next;
    });
    const existing = judgeHandlesRef.current.get(idx);
    if (existing) {
      existing.close();
      judgeHandlesRef.current.delete(idx);
    }
  };

  const handlePickImageClick = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  const handleImageChange = useCallback(
    async (event: ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(event.target.files ?? []);
      // Reset the input so re-selecting the same file fires onChange again.
      event.target.value = "";
      if (files.length === 0) return;

      const newImages: AnswerImage[] = [];
      for (const file of files) {
        if (!file.type.startsWith("image/")) continue;
        try {
          const { base64, mime, name } = await readFileAsBase64(file);
          newImages.push({
            id: makeAnswerImageId(),
            base64,
            url: null,
            filename: name,
            mime,
            previewUrl: URL.createObjectURL(file),
          });
        } catch {
          /* skip this file — user can retry */
        }
      }
      if (newImages.length === 0) return;

      const prev = answers[idx] ?? EMPTY_ANSWER;
      updateAnswer({ images: [...prev.images, ...newImages] });
    },
    [answers, idx, updateAnswer],
  );

  const handleRemoveImage = useCallback(
    (imageId: string) => {
      const prev = answers[idx] ?? EMPTY_ANSWER;
      const remaining: AnswerImage[] = [];
      for (const image of prev.images) {
        if (image.id === imageId) {
          if (image.previewUrl) {
            try {
              URL.revokeObjectURL(image.previewUrl);
            } catch {
              /* ignore */
            }
          }
          continue;
        }
        remaining.push(image);
      }
      updateAnswer({ images: remaining });
    },
    [answers, idx, updateAnswer],
  );

  const handleAiJudge = useCallback(() => {
    if (!q) return;
    const answer = answers[idx] ?? EMPTY_ANSWER;
    const userAnswer = getUserAnswer(q, answer);
    if (!userAnswer && answer.images.length === 0) return;

    // Cancel any in-flight judge for this question before starting a new run.
    const existing = judgeHandlesRef.current.get(idx);
    if (existing) {
      existing.close();
      judgeHandlesRef.current.delete(idx);
    }

    setJudgments((prev) => ({
      ...prev,
      [idx]: { text: "", isStreaming: true, error: null },
    }));
    setAnswerViews((prev) => ({ ...prev, [idx]: "judgment" }));

    const judgeLanguage: "zh" | "en" = language === "zh" ? "zh" : "en";

    const handle = startQuizJudge(
      {
        question: q.question,
        question_type: q.question_type ?? "",
        options: q.options ?? null,
        correct_answer: q.correct_answer ?? "",
        explanation: q.explanation ?? "",
        user_answer: userAnswer,
        user_answer_images: answer.images.map((image) => ({
          base64: image.base64,
          url: image.url,
          filename: image.filename,
          mime_type: image.mime,
        })),
        language: judgeLanguage,
      },
      {
        onChunk: (chunk) => {
          setJudgments((prev) => {
            const current = prev[idx] ?? EMPTY_JUDGMENT;
            return {
              ...prev,
              [idx]: { ...current, text: current.text + chunk },
            };
          });
        },
        onDone: () => {
          let finalText = "";
          setJudgments((prev) => {
            const current = prev[idx] ?? EMPTY_JUDGMENT;
            finalText = current.text;
            return {
              ...prev,
              [idx]: { ...current, isStreaming: false },
            };
          });
          judgeHandlesRef.current.delete(idx);
          // Persist the AI judgment text on the notebook entry so it
          // survives a page refresh. Best-effort — a failed write just
          // means the next reload won't have the judgment cached.
          const key = q ? getQuestionKey(q, idx) : "";
          const eId = key ? entryIds[key] : undefined;
          if (eId && finalText.trim().length > 0) {
            void updateNotebookEntry(eId, { ai_judgment: finalText }).catch(
              () => {},
            );
          }
        },
        onError: (message) => {
          setJudgments((prev) => {
            const current = prev[idx] ?? EMPTY_JUDGMENT;
            return {
              ...prev,
              [idx]: { ...current, isStreaming: false, error: message },
            };
          });
          judgeHandlesRef.current.delete(idx);
        },
      },
    );
    judgeHandlesRef.current.set(idx, handle);
  }, [answers, entryIds, idx, language, q]);

  const handleToggleAnswerView = useCallback(
    (view: AnswerView) => {
      setAnswerViews((prev) => ({ ...prev, [idx]: view }));
    },
    [idx],
  );

  // ── Follow-up (right-side viewer tab) ─────────────────────────
  //
  // Clicking "Follow-up" no longer expands an in-place panel — it opens
  // a dedicated tab in the SessionViewerPanel on the right, where a
  // chat-page-style UI runs the full ``chat`` capability against a
  // session that pins this question + answer + judgment as fixed
  // context. State for that chat lives in ``QuizFollowupProvider`` so
  // it survives tab toggles and is also reflected in this card's
  // message-count badge.

  const handleOpenFollowup = useCallback(() => {
    if (!q) return;
    const key = getQuestionKey(q, idx);
    const answer = answers[idx] ?? EMPTY_ANSWER;
    const judgment = judgments[idx] ?? EMPTY_JUDGMENT;
    followupController.openFollowupTab({
      questionKey: key,
      question: q,
      userAnswer: getUserAnswer(q, answer),
      isCorrect: isAutoGradable(q) ? isAnswerCorrect(q, answer) : null,
      answerImages: answer.images.map((image) => ({
        id: image.id,
        base64: image.base64,
        url: image.url,
        filename: image.filename,
        mime: image.mime,
        previewUrl: image.previewUrl,
      })),
      aiJudgment: judgment.text,
      parentQuizSessionId: sessionId ?? null,
      notebookEntryId: entryIds[key] ?? null,
      followupSessionId: followupSessionIds[key] ?? null,
      language,
      tabLabel: `Q${idx + 1} · ${t("Follow-up")}`,
    });
  }, [
    answers,
    entryIds,
    followupController,
    followupSessionIds,
    idx,
    judgments,
    language,
    q,
    sessionId,
    t,
  ]);

  if (!q) return null;

  const currentEntryId = entryIds[questionKey];
  const currentBookmarked = bookmarked[questionKey] ?? false;
  const showCategoryDropdown = categoryDropdownKey === questionKey;

  return (
    <div className="overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--card)]">
      <div className="flex items-center gap-2 border-b border-[var(--border)] px-3 py-2">
        <button
          type="button"
          onClick={() => setIdx((value) => Math.max(0, value - 1))}
          disabled={idx === 0}
          title={t("Previous")}
          aria-label={t("Previous")}
          className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-[var(--border)] bg-[var(--muted)]/60 text-[var(--foreground)] shadow-sm transition-colors hover:border-[var(--primary)] hover:bg-[var(--primary)]/10 hover:text-[var(--primary)] disabled:cursor-not-allowed disabled:border-[var(--border)] disabled:bg-transparent disabled:text-[var(--muted-foreground)] disabled:opacity-40 disabled:hover:bg-transparent"
        >
          <ChevronLeft size={18} strokeWidth={2.5} />
        </button>
        <span className="text-[11px] font-semibold text-[var(--muted-foreground)]">
          {completedCount}/{total}
        </span>
        <div className="flex flex-1 flex-wrap gap-1">
          {questions.map((question, questionIndex) => {
            const answer = answers[questionIndex];
            const isCurrent = questionIndex === idx;
            const done = answer?.submitted;
            const hasThread =
              Boolean(
                followupThreads[getQuestionKey(question, questionIndex)]
                  ?.sessionId,
              ) ||
              Boolean(
                followupThreads[getQuestionKey(question, questionIndex)]
                  ?.messages.length,
              );
            // Color the chip by correctness for auto-gradable types
            // (choice, concept, fill_in_blank). For open-ended types
            // (short_answer / written / coding) we'd be guessing — keep
            // the neutral "completed" tint so we don't mark a thoughtful
            // answer red just because it doesn't match the reference
            // string verbatim.
            const autoGradable = isAutoGradable(question);
            const correctness: "correct" | "incorrect" | null =
              done && answer && autoGradable
                ? isAnswerCorrect(question, answer)
                  ? "correct"
                  : "incorrect"
                : null;
            const baseChip =
              "flex h-6 w-6 items-center justify-center rounded-full text-[10px] font-semibold transition-all";
            const chipClass = isCurrent
              ? `${baseChip} bg-[var(--primary)] text-white shadow-sm`
              : correctness === "correct"
                ? `${baseChip} bg-green-100 text-green-700 hover:bg-green-200 dark:bg-green-900/40 dark:text-green-300`
                : correctness === "incorrect"
                  ? `${baseChip} bg-red-100 text-red-700 hover:bg-red-200 dark:bg-red-900/40 dark:text-red-300`
                  : done
                    ? `${baseChip} bg-[var(--primary)]/15 text-[var(--primary)]`
                    : `${baseChip} bg-[var(--muted)] text-[var(--muted-foreground)] hover:bg-[var(--border)]`;
            return (
              <button
                key={question.question_id || questionIndex}
                onClick={() => setIdx(questionIndex)}
                className={chipClass}
              >
                {/* For graded auto-gradable questions we *replace* the ✓
                    with the sequence number — the color is the
                    completion signal, and the digit lets the learner
                    navigate to a specific question by index. The
                    followup-thread dot still rides along when the
                    learner asked a follow-up about this question. */}
                {done && !isCurrent && !autoGradable ? (
                  hasThread ? (
                    <span className="relative inline-flex">
                      <Check size={10} />
                      <span className="absolute -right-1 -top-1 h-1.5 w-1.5 rounded-full bg-[var(--primary)]" />
                    </span>
                  ) : (
                    <Check size={10} />
                  )
                ) : hasThread && done && !isCurrent ? (
                  <span className="relative inline-flex">
                    {questionIndex + 1}
                    <span className="absolute -right-1 -top-1 h-1.5 w-1.5 rounded-full bg-[var(--primary)]" />
                  </span>
                ) : (
                  questionIndex + 1
                )}
              </button>
            );
          })}
        </div>
        <button
          type="button"
          onClick={() => setIdx((value) => Math.min(total - 1, value + 1))}
          disabled={idx === total - 1}
          title={t("Next")}
          aria-label={t("Next")}
          className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-[var(--border)] bg-[var(--muted)]/60 text-[var(--foreground)] shadow-sm transition-colors hover:border-[var(--primary)] hover:bg-[var(--primary)]/10 hover:text-[var(--primary)] disabled:cursor-not-allowed disabled:border-[var(--border)] disabled:bg-transparent disabled:text-[var(--muted-foreground)] disabled:opacity-40 disabled:hover:bg-transparent"
        >
          <ChevronRight size={18} strokeWidth={2.5} />
        </button>
      </div>
      <div className="h-0.5 bg-[var(--muted)]">
        <div
          className="h-full bg-[var(--primary)] transition-all duration-300"
          style={{ width: `${navigationProgress}%` }}
        />
      </div>

      <div className="px-4 py-3">
        <div className="mb-2 flex items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="rounded-md bg-[var(--muted)] px-1.5 py-0.5 text-[10px] font-medium uppercase text-[var(--muted-foreground)]">
              Q{idx + 1}
            </span>
            {q.difficulty && (
              <span
                className={`rounded-md px-1.5 py-0.5 text-[10px] font-medium uppercase ${
                  q.difficulty === "hard"
                    ? "bg-red-50 text-red-600 dark:bg-red-950/30 dark:text-red-400"
                    : q.difficulty === "medium"
                      ? "bg-amber-50 text-amber-600 dark:bg-amber-950/30 dark:text-amber-400"
                      : "bg-green-50 text-green-600 dark:bg-green-950/30 dark:text-green-400"
                }`}
              >
                {q.difficulty}
              </span>
            )}
            <span className="rounded-md bg-[var(--muted)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--muted-foreground)]">
              {q.question_type}
            </span>
          </div>

          {ans.submitted && (
            <div className="relative flex items-center gap-1">
              <button
                onClick={handleToggleBookmark}
                disabled={!currentEntryId}
                title={currentBookmarked ? t("Remove Bookmark") : t("Bookmark")}
                className={`rounded-lg p-1.5 transition-all disabled:opacity-30 ${
                  currentBookmarked
                    ? "scale-110 text-amber-500 dark:text-amber-400"
                    : "text-[var(--muted-foreground)] hover:text-amber-500 dark:hover:text-amber-400"
                }`}
              >
                <Bookmark
                  size={18}
                  strokeWidth={currentBookmarked ? 2.5 : 1.8}
                  fill={currentBookmarked ? "currentColor" : "none"}
                />
              </button>
              <button
                onClick={handleOpenCategoryDropdown}
                disabled={!currentEntryId}
                title={t("Add to Category")}
                className="rounded-lg p-1.5 text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)] disabled:opacity-30"
              >
                <FolderPlus size={16} />
              </button>
              <button
                onClick={handleOpenFollowup}
                title={t("Follow-up Chat")}
                className="ml-1 inline-flex items-center gap-1 rounded-lg border border-[var(--primary)]/60 bg-[var(--primary)]/10 px-2 py-1 text-[12px] font-medium text-[var(--primary)] transition-colors hover:bg-[var(--primary)]/15"
              >
                <MessageSquarePlus size={13} />
                {t("Follow-up")}
                {(() => {
                  const tcount =
                    followupThreads[questionKey]?.messages.filter(
                      (m) => m.role !== "system",
                    ).length ?? 0;
                  return tcount > 0 ? (
                    <span className="rounded-full bg-[var(--primary)]/25 px-1.5 py-0 text-[10px]">
                      {tcount}
                    </span>
                  ) : null;
                })()}
              </button>

              {showCategoryDropdown && (
                <div className="absolute right-0 top-8 z-20 w-48 rounded-lg border border-[var(--border)] bg-[var(--card)] py-1 shadow-lg">
                  {categories.length > 0 && (
                    <div className="max-h-[160px] overflow-y-auto">
                      {categories.map((cat) => (
                        <button
                          key={cat.id}
                          disabled={categoryBusy}
                          onClick={() => void handleAddToCategory(cat.id)}
                          className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-[12px] text-[var(--foreground)] transition-colors hover:bg-[var(--muted)] disabled:opacity-40"
                        >
                          {cat.name}
                        </button>
                      ))}
                    </div>
                  )}
                  <div className="border-t border-[var(--border)] px-2 py-1.5">
                    <div className="flex items-center gap-1">
                      <input
                        value={newCategoryName}
                        onChange={(e) => setNewCategoryName(e.target.value)}
                        onKeyDown={(e) =>
                          e.key === "Enter" && void handleCreateAndAdd()
                        }
                        placeholder={t("New category...")}
                        className="flex-1 rounded border border-[var(--border)] bg-[var(--background)] px-2 py-1 text-[11px] text-[var(--foreground)] outline-none placeholder:text-[var(--muted-foreground)]"
                      />
                      <button
                        disabled={!newCategoryName.trim() || categoryBusy}
                        onClick={() => void handleCreateAndAdd()}
                        className="rounded p-1 text-[var(--primary)] disabled:opacity-30"
                      >
                        {categoryBusy ? (
                          <Loader2 size={12} className="animate-spin" />
                        ) : (
                          <Plus size={12} />
                        )}
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        <div className="mb-3 text-[14px] leading-relaxed">
          <MarkdownRenderer
            content={q.question}
            variant="prose"
            className="text-[var(--foreground)]"
          />
        </div>

        {isChoice ? (
          <div className="space-y-1.5">
            {Object.entries(q.options!).map(([key, text]) => {
              const isSelected = ans.selected === key;
              const correctKey = q.correct_answer
                .trim()
                .charAt(0)
                .toUpperCase();
              const isCorrectOption = key.toUpperCase() === correctKey;
              const showFeedback = ans.submitted;

              let optionClass =
                "border-[var(--border)] bg-[var(--background)] text-[var(--foreground)] hover:border-[var(--primary)]/30 hover:bg-[var(--primary)]/[0.02]";

              if (isSelected && !showFeedback) {
                optionClass =
                  "border-[var(--primary)] bg-[var(--primary)]/[0.06] text-[var(--foreground)] ring-1 ring-[var(--primary)]/20";
              } else if (showFeedback && isCorrectOption) {
                optionClass =
                  "border-green-500 bg-green-50 text-green-800 dark:bg-green-950/20 dark:text-green-300 dark:border-green-700";
              } else if (showFeedback && isSelected && !isCorrectOption) {
                optionClass =
                  "border-red-400 bg-red-50 text-red-700 dark:bg-red-950/20 dark:text-red-300 dark:border-red-700";
              }

              return (
                <button
                  key={key}
                  disabled={ans.submitted}
                  onClick={() => updateAnswer({ selected: key })}
                  className={`flex w-full items-start gap-2.5 rounded-lg border px-3 py-2 text-left text-[13px] transition-all ${optionClass}`}
                >
                  <span
                    className={`mt-[1px] flex h-5 w-5 shrink-0 items-center justify-center rounded-full border text-[11px] font-bold ${
                      isSelected && !showFeedback
                        ? "border-[var(--primary)] bg-[var(--primary)] text-white"
                        : showFeedback && isCorrectOption
                          ? "border-green-500 bg-green-500 text-white"
                          : showFeedback && isSelected && !isCorrectOption
                            ? "border-red-400 bg-red-400 text-white"
                            : "border-[var(--border)] text-[var(--muted-foreground)]"
                    }`}
                  >
                    {showFeedback && isCorrectOption ? (
                      <Check size={11} />
                    ) : (
                      key
                    )}
                  </span>
                  <div className="min-w-0 leading-relaxed">
                    <MarkdownRenderer
                      content={text}
                      variant="compact"
                      enableMath
                    />
                  </div>
                </button>
              );
            })}
          </div>
        ) : isConcept ? (
          // Concept (true/false) — two large buttons.
          (() => {
            const correctTF = resolveConceptAnswer(q.correct_answer);
            const showFeedback = ans.submitted;
            const renderTFButton = (key: "true" | "false", label: string) => {
              const isSelected = ans.selected === key;
              const isCorrect = correctTF === key;
              let cls =
                "border-[var(--border)] bg-[var(--background)] text-[var(--foreground)] hover:border-[var(--primary)]/30";
              if (isSelected && !showFeedback) {
                cls =
                  "border-[var(--primary)] bg-[var(--primary)]/[0.08] text-[var(--foreground)] ring-1 ring-[var(--primary)]/25";
              } else if (showFeedback && isCorrect) {
                cls =
                  "border-green-500 bg-green-50 text-green-800 dark:bg-green-950/20 dark:text-green-300 dark:border-green-700";
              } else if (showFeedback && isSelected && !isCorrect) {
                cls =
                  "border-red-400 bg-red-50 text-red-700 dark:bg-red-950/20 dark:text-red-300 dark:border-red-700";
              }
              return (
                <button
                  key={key}
                  type="button"
                  disabled={ans.submitted}
                  onClick={() => updateAnswer({ selected: key })}
                  className={`flex flex-1 items-center justify-center gap-2 rounded-lg border px-3 py-3 text-[14px] font-semibold transition-all ${cls}`}
                >
                  {label}
                </button>
              );
            };
            return (
              <div className="flex gap-2">
                {renderTFButton("true", t("True"))}
                {renderTFButton("false", t("False"))}
              </div>
            );
          })()
        ) : isFillBlank ? (
          // Fill-in-the-blank — single-line input. The question text
          // already contains the literal ``____`` placeholder which the
          // learner sees in the rendered question above; this is just
          // where they type the missing word/phrase.
          <div>
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-[var(--muted-foreground)]/70">
              {t("Fill in the Blank")}
            </div>
            <input
              type="text"
              value={ans.typed}
              onChange={(event) => updateAnswer({ typed: event.target.value })}
              disabled={ans.submitted}
              placeholder={t("Type your answer...")}
              className={`w-full rounded-lg border px-3 py-2 text-[13px] outline-none transition-colors placeholder:text-[var(--muted-foreground)] ${
                ans.submitted
                  ? "border-[var(--border)] bg-[var(--muted)] text-[var(--foreground)]"
                  : "border-[var(--border)] bg-[var(--background)] text-[var(--foreground)] focus:border-[var(--primary)]/40"
              }`}
            />
          </div>
        ) : (
          // Free-text branches: short_answer / written / coding.
          // Different default heights so essay-style "written" has more
          // room than a concept-style short answer.
          <div>
            <textarea
              value={ans.typed}
              onChange={(event) => updateAnswer({ typed: event.target.value })}
              disabled={ans.submitted}
              rows={
                q.question_type === "coding"
                  ? 6
                  : q.question_type === "written"
                    ? 5
                    : 3
              }
              placeholder={
                q.question_type === "coding"
                  ? t("Write your code here...")
                  : t("Type your answer...")
              }
              className={`w-full resize-y rounded-lg border px-3 py-2 text-[13px] outline-none transition-colors placeholder:text-[var(--muted-foreground)] ${
                ans.submitted
                  ? "border-[var(--border)] bg-[var(--muted)] text-[var(--foreground)]"
                  : "border-[var(--border)] bg-[var(--background)] text-[var(--foreground)] focus:border-[var(--primary)]/40"
              } ${q.question_type === "coding" ? "font-mono" : ""}`}
            />
          </div>
        )}

        {/* Image-as-answer attachment — only offered for question types
            without an auto-gradable answer (short_answer / written /
            coding). These are also the types that benefit most from a
            multimodal AI judgment over handwritten work. */}
        {!isGradable && (
          <div className="mt-2 space-y-2">
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              multiple
              onChange={(event) => void handleImageChange(event)}
              className="hidden"
            />
            {ans.images.length > 0 && (
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4">
                {ans.images.map((image) => {
                  const previewSrc =
                    image.previewUrl ?? resolveImageSrc(image.url);
                  return (
                    <div
                      key={image.id}
                      className="group relative overflow-hidden rounded-md border border-[var(--border)] bg-[var(--background)]"
                    >
                      {previewSrc ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          src={previewSrc}
                          alt={image.filename}
                          className="h-24 w-full object-cover"
                        />
                      ) : (
                        <div className="flex h-24 w-full items-center justify-center text-[10px] text-[var(--muted-foreground)]">
                          {image.filename}
                        </div>
                      )}
                      <div className="absolute inset-x-0 bottom-0 truncate bg-black/45 px-1.5 py-0.5 text-[10px] text-white">
                        {image.filename}
                      </div>
                      {!ans.submitted && (
                        <button
                          type="button"
                          onClick={() => handleRemoveImage(image.id)}
                          title={t("Remove image")}
                          className="absolute right-1 top-1 inline-flex h-5 w-5 items-center justify-center rounded-full bg-black/55 text-white opacity-0 transition-opacity group-hover:opacity-100"
                        >
                          <X size={11} />
                        </button>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
            {!ans.submitted && (
              <button
                type="button"
                onClick={handlePickImageClick}
                className="inline-flex items-center gap-1.5 rounded-md border border-dashed border-[var(--border)] bg-[var(--background)] px-2.5 py-1.5 text-[12px] text-[var(--muted-foreground)] transition-colors hover:border-[var(--primary)] hover:text-[var(--primary)]"
              >
                <ImagePlus size={13} />
                {ans.images.length === 0
                  ? t("Attach an image as your answer")
                  : t("Add another image")}
              </button>
            )}
          </div>
        )}

        <div className="mt-3 flex flex-wrap items-center gap-2">
          {!ans.submitted ? (
            <button
              onClick={handleSubmit}
              disabled={(() => {
                if (isChoice || isConcept) return !ans.selected;
                // For free-text / fill-blank, require a typed answer; for
                // non-auto-gradable types, an image attachment also counts.
                if (ans.typed.trim()) return false;
                if (!isGradable && ans.images.length > 0) return false;
                return true;
              })()}
              className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3 py-1.5 text-[12px] font-medium text-white transition-opacity disabled:opacity-30"
            >
              <Eye size={13} />
              {t("Check Answer")}
            </button>
          ) : (
            <>
              {isGradable && isCorrect !== null && (
                <span
                  className={`rounded-md px-2 py-0.5 text-[11px] font-semibold ${
                    isCorrect
                      ? "bg-green-100 text-green-700 dark:bg-green-950/30 dark:text-green-400"
                      : "bg-red-100 text-red-700 dark:bg-red-950/30 dark:text-red-400"
                  }`}
                >
                  {isCorrect ? t("Correct") : t("Incorrect")}
                </span>
              )}
              <button
                onClick={handleReset}
                className="inline-flex items-center gap-1 rounded-lg bg-[var(--muted)] px-2.5 py-1.5 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
              >
                <RotateCcw size={11} />
                {t("Retry")}
              </button>
              {(() => {
                const j = judgments[idx] ?? EMPTY_JUDGMENT;
                const hasJudgment = j.text.length > 0 || j.error !== null;
                return (
                  <button
                    onClick={handleAiJudge}
                    disabled={j.isStreaming}
                    className="inline-flex items-center gap-1 rounded-lg border border-[var(--primary)]/60 bg-[var(--primary)]/10 px-2.5 py-1.5 text-[12px] font-medium text-[var(--primary)] transition-colors hover:bg-[var(--primary)]/15 disabled:opacity-50"
                  >
                    {j.isStreaming ? (
                      <Loader2 size={11} className="animate-spin" />
                    ) : (
                      <Sparkles size={11} />
                    )}
                    {j.isStreaming
                      ? t("Judging...")
                      : hasJudgment
                        ? t("Re-judge")
                        : t("AI Judge")}
                  </button>
                );
              })()}
            </>
          )}
        </div>

        {ans.submitted &&
          (() => {
            const judgment = judgments[idx] ?? EMPTY_JUDGMENT;
            const hasJudgment =
              judgment.text.length > 0 ||
              judgment.error !== null ||
              judgment.isStreaming;
            // Default to the reference tab; flip to the judgment tab when
            // the learner first triggers a judge run (set in handleAiJudge).
            const view: AnswerView =
              answerViews[idx] ?? (hasJudgment ? "judgment" : "reference");
            const showReferenceAnswer =
              !isChoice && !isConcept && !!q.correct_answer;
            const showAnyReference = showReferenceAnswer || !!q.explanation;
            if (!showAnyReference && !hasJudgment) return null;

            const collapsed = reviewCollapsed[idx] === true;
            const toggleCollapsed = () =>
              setReviewCollapsed((prev) => ({ ...prev, [idx]: !collapsed }));

            return (
              <div className="mt-3 space-y-2 rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2.5">
                {/* Header bar — when there's no tab strip (only one of
                    reference/judgment is showing) we still render this so
                    the collapse chevron has a home. */}
                {hasJudgment && showAnyReference ? (
                  <div className="flex items-center gap-1 border-b border-[var(--border)]/70 pb-1.5">
                    <button
                      type="button"
                      onClick={() => handleToggleAnswerView("reference")}
                      className={`rounded-md px-2 py-0.5 text-[11px] font-medium transition-colors ${
                        view === "reference"
                          ? "bg-[var(--primary)]/12 text-[var(--primary)]"
                          : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                      }`}
                    >
                      {t("Reference Answer")}
                    </button>
                    <button
                      type="button"
                      onClick={() => handleToggleAnswerView("judgment")}
                      className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-medium transition-colors ${
                        view === "judgment"
                          ? "bg-[var(--primary)]/12 text-[var(--primary)]"
                          : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                      }`}
                    >
                      <Sparkles size={10} />
                      {t("AI Judgment")}
                      {judgment.isStreaming && (
                        <Loader2 size={10} className="animate-spin" />
                      )}
                    </button>
                    <button
                      type="button"
                      onClick={toggleCollapsed}
                      aria-label={collapsed ? t("Expand") : t("Collapse")}
                      title={collapsed ? t("Expand") : t("Collapse")}
                      className="ml-auto inline-flex h-5 w-5 items-center justify-center rounded-md text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
                    >
                      <ChevronDown
                        size={13}
                        className={`transition-transform ${
                          collapsed ? "-rotate-90" : ""
                        }`}
                      />
                    </button>
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={toggleCollapsed}
                    className="flex w-full items-center gap-1 pb-1.5 text-left"
                  >
                    <span className="text-[10px] font-semibold uppercase tracking-wider text-[var(--muted-foreground)]">
                      {hasJudgment ? t("AI Judgment") : t("Reference Answer")}
                    </span>
                    <ChevronDown
                      size={13}
                      className={`ml-auto text-[var(--muted-foreground)] transition-transform ${
                        collapsed ? "-rotate-90" : ""
                      }`}
                    />
                  </button>
                )}

                {collapsed ? null : hasJudgment && view === "judgment" ? (
                  <div>
                    <div className="mb-1 flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider text-[var(--muted-foreground)]">
                      <Sparkles size={10} />
                      {t("AI Judgment")}
                      {judgment.isStreaming && (
                        <Loader2
                          size={10}
                          className="animate-spin text-[var(--primary)]"
                        />
                      )}
                    </div>
                    {judgment.error ? (
                      <div className="rounded-md border border-red-200 bg-red-50 px-2 py-1 text-[12px] text-red-700 dark:border-red-950/50 dark:bg-red-950/20 dark:text-red-300">
                        {judgment.error}
                      </div>
                    ) : judgment.text ? (
                      <div className="text-[13px] leading-relaxed text-[var(--foreground)]">
                        <MarkdownRenderer
                          content={judgment.text}
                          variant="prose"
                        />
                      </div>
                    ) : (
                      <div className="text-[12px] text-[var(--muted-foreground)]">
                        {t("Judging...")}
                      </div>
                    )}
                  </div>
                ) : (
                  <>
                    {showReferenceAnswer && (
                      <div>
                        <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-[var(--muted-foreground)]">
                          {t("Reference Answer")}
                        </div>
                        <div className="text-[13px] leading-relaxed text-[var(--foreground)]">
                          <MarkdownRenderer
                            content={
                              q.question_type === "coding" &&
                              !q.correct_answer.trimStart().startsWith("```")
                                ? `\`\`\`python\n${q.correct_answer}\n\`\`\``
                                : q.correct_answer
                            }
                            variant="prose"
                          />
                        </div>
                      </div>
                    )}
                    {q.explanation && (
                      <div>
                        <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-[var(--muted-foreground)]">
                          {t("Explanation")}
                        </div>
                        <div className="text-[13px] leading-relaxed text-[var(--muted-foreground)]">
                          <MarkdownRenderer
                            content={q.explanation}
                            variant="prose"
                          />
                        </div>
                      </div>
                    )}
                  </>
                )}
              </div>
            );
          })()}
      </div>
    </div>
  );
}
