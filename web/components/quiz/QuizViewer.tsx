"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronLeft, ChevronRight, Eye, RotateCcw } from "lucide-react";
import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import QuestionFollowupPanel, {
  type FollowupThreadState,
} from "@/components/quiz/QuestionFollowupPanel";
import { buildQuizFollowupConfig, type QuizQuestion } from "@/lib/quiz-types";
import { recordQuizResults } from "@/lib/session-api";
import { shouldAppendEventContent } from "@/lib/stream";
import { type StartTurnMessage, type StreamEvent, UnifiedWSClient } from "@/lib/unified-ws";

interface QuizViewerProps {
  questions: QuizQuestion[];
  sessionId?: string | null;
  language?: string;
}

type AnswerState = {
  selected: string | null;
  typed: string;
  submitted: boolean;
};

const EMPTY_ANSWER: AnswerState = { selected: null, typed: "", submitted: false };

function createEmptyThreadState(): FollowupThreadState {
  return {
    isOpen: false,
    input: "",
    isStreaming: false,
    currentStage: "",
    sessionId: null,
    activeTurnId: null,
    messages: [],
    error: null,
  };
}

function getQuestionKey(question: QuizQuestion, index: number): string {
  return question.question_id || `question_${index + 1}`;
}

function getUserAnswer(question: QuizQuestion, answer: AnswerState): string {
  if (
    question.question_type === "choice" &&
    question.options &&
    Object.keys(question.options).length > 0
  ) {
    return answer.selected ?? "";
  }
  return answer.typed.trim();
}

function isAnswerCorrect(question: QuizQuestion, answer: AnswerState): boolean {
  const userAnswer = getUserAnswer(question, answer);
  if (!userAnswer) return false;
  const correct = question.correct_answer.trim();
  const isChoice =
    question.question_type === "choice" &&
    question.options &&
    Object.keys(question.options).length > 0;
  if (isChoice) {
    return (
      userAnswer.toUpperCase() === correct.toUpperCase() ||
      userAnswer.toUpperCase() === correct.charAt(0).toUpperCase()
    );
  }
  return userAnswer.toLowerCase() === correct.toLowerCase();
}

export default function QuizViewer({
  questions,
  sessionId,
  language = "zh",
}: QuizViewerProps) {
  const [idx, setIdx] = useState(0);
  const [answers, setAnswers] = useState<Record<number, AnswerState>>({});
  const [threads, setThreads] = useState<Record<string, FollowupThreadState>>({});
  const lastReportedSignatureRef = useRef("");
  const threadsRef = useRef<Record<string, FollowupThreadState>>({});
  const threadRunnersRef = useRef<
    Map<string, { questionKey: string; client: UnifiedWSClient }>
  >(new Map());

  const q = questions[idx];
  const ans = answers[idx] ?? EMPTY_ANSWER;
  const total = questions.length;
  const navigationProgress = total > 0 ? ((idx + 1) / total) * 100 : 0;
  const questionKey = q ? getQuestionKey(q, idx) : "";
  const thread = questionKey
    ? threads[questionKey] ?? createEmptyThreadState()
    : createEmptyThreadState();
  const completedCount = useMemo(
    () => Object.values(answers).filter((answer) => answer.submitted).length,
    [answers],
  );

  useEffect(() => {
    threadsRef.current = threads;
  }, [threads]);

  useEffect(
    () => () => {
      threadRunnersRef.current.forEach(({ client }) => client.disconnect());
      threadRunnersRef.current.clear();
    },
    [],
  );

  const updateAnswer = useCallback(
    (patch: Partial<AnswerState>) =>
      setAnswers((prev) => ({
        ...prev,
        [idx]: { ...(prev[idx] ?? EMPTY_ANSWER), ...patch },
      })),
    [idx],
  );

  const updateThread = useCallback(
    (key: string, updater: (prev: FollowupThreadState) => FollowupThreadState) => {
      setThreads((prev) => ({
        ...prev,
        [key]: updater(prev[key] ?? createEmptyThreadState()),
      }));
    },
    [],
  );

  const handleThreadEvent = useCallback(
    (key: string, event: StreamEvent) => {
      if (event.type === "session") {
        const metadata = (event.metadata ?? {}) as {
          session_id?: string;
          turn_id?: string;
        };
        const nextSessionId = metadata.session_id || event.session_id || "";
        const nextTurnId = metadata.turn_id || event.turn_id || null;
        if (!nextSessionId) return;
        updateThread(key, (prev) => ({
          ...prev,
          sessionId: nextSessionId,
          activeTurnId: nextTurnId,
        }));
        const runner = threadRunnersRef.current.get(key);
        if (runner) runner.questionKey = nextSessionId;
        return;
      }

      if (event.type === "done") {
        updateThread(key, (prev) => ({
          ...prev,
          isStreaming: false,
          currentStage: "",
          activeTurnId: null,
        }));
        const runner = threadRunnersRef.current.get(key);
        runner?.client.disconnect();
        threadRunnersRef.current.delete(key);
        return;
      }

      updateThread(key, (prev) => {
        const next = { ...prev, activeTurnId: event.turn_id || prev.activeTurnId };
        if (event.type === "stage_start") {
          next.currentStage = event.stage;
          return next;
        }
        if (event.type === "stage_end") {
          next.currentStage = "";
          return next;
        }
        if (event.type === "error") {
          next.error = event.content || prev.error;
          const terminal = Boolean(
            ((event.metadata ?? {}) as { turn_terminal?: boolean }).turn_terminal,
          );
          if (terminal) {
            next.isStreaming = false;
            next.currentStage = "";
            next.activeTurnId = null;
          }
          return next;
        }
        if (shouldAppendEventContent(event)) {
          const messages = [...prev.messages];
          const last = messages[messages.length - 1];
          if (!last || last.role !== "assistant") {
            messages.push({ role: "assistant", content: event.content });
          } else {
            messages[messages.length - 1] = {
              ...last,
              content: `${last.content}${event.content}`,
            };
          }
          next.messages = messages;
        }
        return next;
      });
    },
    [updateThread],
  );

  const ensureThreadRunner = useCallback(
    (key: string) => {
      const existing = threadRunnersRef.current.get(key);
      if (existing) {
        if (!existing.client.connected) existing.client.connect();
        return existing;
      }
      const record = {
        questionKey: key,
        client: new UnifiedWSClient(
          (event) => handleThreadEvent(key, event),
          () => {
            const current = threadsRef.current[key];
            if (current?.isStreaming) {
              updateThread(key, (prev) => ({
                ...prev,
                isStreaming: false,
                currentStage: "",
                activeTurnId: null,
                error: prev.error || "Follow-up chat failed because the connection closed.",
              }));
            }
          },
        ),
      };
      threadRunnersRef.current.set(key, record);
      record.client.connect();
      return record;
    },
    [handleThreadEvent, updateThread],
  );

  const sendThroughThreadRunner = useCallback(
    function sendThroughThreadRunner(
      key: string,
      message: StartTurnMessage,
      attempt = 0,
    ) {
      const runner = ensureThreadRunner(key);
      if (!runner.client.connected) {
        if (attempt >= 10) {
          updateThread(key, (prev) => ({
            ...prev,
            isStreaming: false,
            currentStage: "",
            error: "Follow-up chat failed to connect.",
          }));
          return;
        }
        window.setTimeout(
          () => sendThroughThreadRunner(key, message, attempt + 1),
          200,
        );
        return;
      }
      runner.client.send(message);
    },
    [ensureThreadRunner, updateThread],
  );

  const isChoice =
    q?.question_type === "choice" && q.options && Object.keys(q.options).length > 0;
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
            user_answer: getUserAnswer(question, answer),
            correct_answer: question.correct_answer,
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
    void recordQuizResults(sessionId, submittedResults).catch((error) => {
      console.error("Failed to record quiz results:", error);
      if (lastReportedSignatureRef.current === signature) {
        lastReportedSignatureRef.current = "";
      }
    });
  }, [completedCount, sessionId, submittedResults, total]);

  const handleSubmit = () => {
    if (ans.submitted) return;
    updateAnswer({ submitted: true });
  };

  const handleReset = () => {
    updateAnswer({ selected: null, typed: "", submitted: false });
  };

  const handleToggleFollowup = useCallback(() => {
    if (!q) return;
    const key = getQuestionKey(q, idx);
    updateThread(key, (prev) => ({ ...prev, isOpen: !prev.isOpen }));
  }, [idx, q, updateThread]);

  const handleFollowupInputChange = useCallback(
    (value: string) => {
      if (!q) return;
      const key = getQuestionKey(q, idx);
      updateThread(key, (prev) => ({ ...prev, input: value }));
    },
    [idx, q, updateThread],
  );

  const handleSendFollowup = useCallback(() => {
    if (!q) return;
    const key = getQuestionKey(q, idx);
    const currentThread = threadsRef.current[key] ?? createEmptyThreadState();
    const content = currentThread.input.trim();
    if (!content || currentThread.isStreaming) return;

    const answer = answers[idx] ?? EMPTY_ANSWER;
    const followupConfig = buildQuizFollowupConfig(
      q,
      getUserAnswer(q, answer),
      isAnswerCorrect(q, answer),
      sessionId,
    );

    updateThread(key, (prev) => ({
      ...prev,
      isOpen: true,
      input: "",
      isStreaming: true,
      error: null,
      messages: [...prev.messages, { role: "user", content }],
    }));

    sendThroughThreadRunner(key, {
      type: "start_turn",
      content,
      tools: [],
      capability: "deep_question",
      knowledge_bases: [],
      session_id: currentThread.sessionId,
      attachments: [],
      language,
      config: followupConfig,
    });
  }, [answers, idx, language, q, sendThroughThreadRunner, sessionId, updateThread]);

  if (!q) return null;

  return (
    <div className="overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--card)]">
      <div className="flex items-center gap-1 border-b border-[var(--border)] px-3 py-2">
        <span className="mr-2 text-[11px] font-semibold text-[var(--muted-foreground)]">
          {completedCount}/{total}
        </span>
        <div className="flex flex-wrap gap-1">
          {questions.map((question, questionIndex) => {
            const answer = answers[questionIndex];
            const isCurrent = questionIndex === idx;
            const done = answer?.submitted;
            const hasThread =
              Boolean(
                threads[getQuestionKey(question, questionIndex)]?.sessionId,
              ) ||
              Boolean(
                threads[getQuestionKey(question, questionIndex)]?.messages.length,
              );
            return (
              <button
                key={question.question_id || questionIndex}
                onClick={() => setIdx(questionIndex)}
                className={`flex h-6 w-6 items-center justify-center rounded-full text-[10px] font-semibold transition-all ${
                  isCurrent
                    ? "bg-[var(--primary)] text-white shadow-sm"
                    : done
                      ? "bg-[var(--primary)]/15 text-[var(--primary)]"
                      : "bg-[var(--muted)] text-[var(--muted-foreground)] hover:bg-[var(--border)]"
                }`}
              >
                {done && !isCurrent ? (
                  hasThread ? (
                    <span className="relative inline-flex">
                      <Check size={10} />
                      <span className="absolute -right-1 -top-1 h-1.5 w-1.5 rounded-full bg-[var(--primary)]" />
                    </span>
                  ) : (
                    <Check size={10} />
                  )
                ) : (
                  questionIndex + 1
                )}
              </button>
            );
          })}
        </div>
      </div>

      <div className="px-4 py-3">
        <div className="mb-2 flex flex-wrap items-center gap-1.5">
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
              const correctKey = q.correct_answer.trim().charAt(0).toUpperCase();
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
                    {showFeedback && isCorrectOption ? <Check size={11} /> : key}
                  </span>
                  <span className="leading-relaxed">{text}</span>
                </button>
              );
            })}
          </div>
        ) : (
          <div>
            <textarea
              value={ans.typed}
              onChange={(event) => updateAnswer({ typed: event.target.value })}
              disabled={ans.submitted}
              rows={3}
              placeholder={
                q.question_type === "coding" ? "Write your code here..." : "Type your answer..."
              }
              className={`w-full resize-none rounded-lg border px-3 py-2 text-[13px] outline-none transition-colors placeholder:text-[var(--muted-foreground)] ${
                ans.submitted
                  ? "border-[var(--border)] bg-[var(--muted)] text-[var(--foreground)]"
                  : "border-[var(--border)] bg-[var(--background)] text-[var(--foreground)] focus:border-[var(--primary)]/40"
              } ${q.question_type === "coding" ? "font-mono" : ""}`}
            />
          </div>
        )}

        <div className="mt-3 flex items-center gap-2">
          {!ans.submitted ? (
            <button
              onClick={handleSubmit}
              disabled={isChoice ? !ans.selected : !ans.typed.trim()}
              className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3 py-1.5 text-[12px] font-medium text-white transition-opacity disabled:opacity-30"
            >
              <Eye size={13} />
              Check Answer
            </button>
          ) : (
            <>
              {isChoice && isCorrect !== null && (
                <span
                  className={`rounded-md px-2 py-0.5 text-[11px] font-semibold ${
                    isCorrect
                      ? "bg-green-100 text-green-700 dark:bg-green-950/30 dark:text-green-400"
                      : "bg-red-100 text-red-700 dark:bg-red-950/30 dark:text-red-400"
                  }`}
                >
                  {isCorrect ? "Correct" : "Incorrect"}
                </span>
              )}
              <button
                onClick={handleReset}
                className="inline-flex items-center gap-1 rounded-lg bg-[var(--muted)] px-2.5 py-1.5 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
              >
                <RotateCcw size={11} />
                Retry
              </button>
            </>
          )}
        </div>

        {ans.submitted && (
          <div className="mt-3 space-y-2 rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2.5">
            {!isChoice && q.correct_answer && (
              <div>
                <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-[var(--muted-foreground)]">
                  Reference Answer
                </div>
                <div className="text-[13px] leading-relaxed text-[var(--foreground)]">
                  <MarkdownRenderer content={q.correct_answer} variant="prose" />
                </div>
              </div>
            )}
            {q.explanation && (
              <div>
                <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-[var(--muted-foreground)]">
                  Explanation
                </div>
                <div className="text-[13px] leading-relaxed text-[var(--muted-foreground)]">
                  <MarkdownRenderer content={q.explanation} variant="prose" />
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      <div className="flex items-center justify-between border-t border-[var(--border)] px-3 py-2">
        <button
          onClick={() => setIdx((value) => Math.max(0, value - 1))}
          disabled={idx === 0}
          className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-30"
        >
          <ChevronLeft size={13} />
          Previous
        </button>

        <div className="mx-3 h-1 flex-1 overflow-hidden rounded-full bg-[var(--muted)]">
          <div
            className="h-full rounded-full bg-[var(--primary)] transition-all duration-300"
            style={{ width: `${navigationProgress}%` }}
          />
        </div>

        <button
          onClick={() => setIdx((value) => Math.min(total - 1, value + 1))}
          disabled={idx === total - 1}
          className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-30"
        >
          Next
          <ChevronRight size={13} />
        </button>
      </div>

      {ans.submitted && (
        <QuestionFollowupPanel
          question={q}
          questionNumber={idx + 1}
          thread={thread}
          onToggle={handleToggleFollowup}
          onInputChange={handleFollowupInputChange}
          onSend={handleSendFollowup}
        />
      )}
    </div>
  );
}
