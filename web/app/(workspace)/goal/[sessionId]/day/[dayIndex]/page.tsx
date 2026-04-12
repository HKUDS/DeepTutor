"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, Send } from "lucide-react";

import Button from "@/components/ui/Button";
import { useKaTeXInjection } from "@/app/(workspace)/guide/hooks/useKaTeXInjection";
import {
  askGoalDayInteractiveAssistant,
  generateGoalPractice,
  generateGoalDayInteractivePage,
  getGoalDayPlanDetail,
  getGoalPlan,
  replanGoalSession,
  submitGoalFeedback,
} from "@/lib/goal-api";

type DayPlanTimeBlock = {
  block_id: string;
  title: string;
  kind: string;
  minutes: number;
  steps: string[];
  linked_task_ids: string[];
};

type DayPlanDetail = {
  session_id: string;
  day_index: number;
  date?: string;
  objective_summary: string;
  time_blocks: DayPlanTimeBlock[];
  key_points: string[];
  pitfalls: string[];
  acceptance_criteria: string[];
  review_actions: string[];
  linked_task_ids: string[];
};

type GoalPlanTask = {
  task_id: string;
  day_index: number;
  title: string;
  kind: string;
  estimate_minutes: number;
  objective: string;
};

type PracticeItem = {
  prompt?: string;
  question?: string;
  question_type?: string;
  difficulty?: string;
  reference_answer?: string;
};

type ReplanDiff = {
  added_tasks?: string[];
  moved_tasks?: string[];
  dropped_tasks?: string[];
};

type ChatMsg = {
  id: string;
  role: "user" | "assistant";
  content: string;
};

export default function GoalDayDetailPage() {
  const { t } = useTranslation();
  const { injectKaTeX } = useKaTeXInjection();
  const params = useParams<{ sessionId: string; dayIndex: string }>();
  const sessionId = params.sessionId;
  const dayIndex = Number(params.dayIndex);

  const [detail, setDetail] = useState<DayPlanDetail | null>(null);
  const [tasks, setTasks] = useState<GoalPlanTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [statusText, setStatusText] = useState("");
  const [replanLoading, setReplanLoading] = useState(false);
  const [feedbackState, setFeedbackState] = useState<Record<string, "done" | "partial" | "missed" | "skipped">>({});
  const [feedbackLoadingByTask, setFeedbackLoadingByTask] = useState<Record<string, boolean>>({});
  const [practiceLoadingByTask, setPracticeLoadingByTask] = useState<Record<string, boolean>>({});
  const [practiceByTask, setPracticeByTask] = useState<Record<string, PracticeItem[]>>({});
  const [taskErrorByTask, setTaskErrorByTask] = useState<Record<string, string>>({});
  const [taskNoticeByTask, setTaskNoticeByTask] = useState<Record<string, string>>({});
  const [replanDiff, setReplanDiff] = useState<ReplanDiff | null>(null);
  const [lessonHtml, setLessonHtml] = useState("");
  const [lessonLoading, setLessonLoading] = useState(false);
  const [lessonError, setLessonError] = useState("");
  const [messages, setMessages] = useState<ChatMsg[]>([
    {
      id: "assistant-welcome",
      role: "assistant",
      content: "I am your daily learning assistant. Ask me about frequent exam points, knowledge structure, common mistakes, and score-improvement strategies.",
    },
  ]);
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);

  const completionOptions = useMemo(
    () => [
      ["done", t("done")],
      ["partial", t("partial")],
      ["missed", t("missed")],
      ["skipped", t("skipped")],
    ] as const,
    [t],
  );
  const lessonHtmlWithMath = useMemo(
    () => (lessonHtml ? injectKaTeX(lessonHtml) : ""),
    [injectKaTeX, lessonHtml],
  );

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError("");
      try {
        const [detailPayload, planPayload] = await Promise.all([
          getGoalDayPlanDetail(sessionId, dayIndex),
          getGoalPlan(sessionId),
        ]);
        if (cancelled) return;
        setDetail(detailPayload.data as DayPlanDetail);
        const allTasks = ((planPayload.data as { tasks?: GoalPlanTask[] }).tasks || []).filter(
          (task) => task.day_index === dayIndex,
        );
        setTasks(allTasks);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : t("Failed to load day plan detail"));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [dayIndex, sessionId, t]);

  const loadLesson = async (force = false) => {
    setLessonLoading(true);
    setLessonError("");
    try {
      const payload = await generateGoalDayInteractivePage(sessionId, dayIndex, { force });
      const data = payload.data as { html?: string };
      setLessonHtml(data.html || "");
    } catch (err) {
      setLessonError(err instanceof Error ? err.message : t("Failed to generate interactive page"));
    } finally {
      setLessonLoading(false);
    }
  };

  useEffect(() => {
    void loadLesson(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, dayIndex]);

  const askAssistant = async () => {
    const text = question.trim();
    if (!text || asking) return;
    setMessages((prev) => [
      ...prev,
      { id: `user-${Date.now()}`, role: "user", content: text },
    ]);
    setQuestion("");
    setAsking(true);
    try {
      const payload = await askGoalDayInteractiveAssistant(sessionId, dayIndex, {
        question: text,
      });
      const answer = (payload.data as { answer?: string }).answer || t("No response");
      setMessages((prev) => [
        ...prev,
        { id: `assistant-${Date.now()}`, role: "assistant", content: answer },
      ]);
    } catch (err) {
      const message = err instanceof Error ? err.message : t("Failed to ask interactive assistant");
      setMessages((prev) => [
        ...prev,
        { id: `assistant-error-${Date.now()}`, role: "assistant", content: message },
      ]);
    } finally {
      setAsking(false);
    }
  };

  const refreshDay = async () => {
    const [detailPayload, planPayload] = await Promise.all([
      getGoalDayPlanDetail(sessionId, dayIndex),
      getGoalPlan(sessionId),
    ]);
    setDetail(detailPayload.data as DayPlanDetail);
    const allTasks = ((planPayload.data as { tasks?: GoalPlanTask[] }).tasks || []).filter(
      (task) => task.day_index === dayIndex,
    );
    setTasks(allTasks);
  };

  const handleSubmitFeedback = async (taskId: string) => {
    const completion = feedbackState[taskId] || "done";
    setFeedbackLoadingByTask((prev) => ({ ...prev, [taskId]: true }));
    setTaskErrorByTask((prev) => ({ ...prev, [taskId]: "" }));
    setTaskNoticeByTask((prev) => ({ ...prev, [taskId]: "" }));
    try {
      setError("");
      setStatusText(t("Submitting feedback..."));
      await submitGoalFeedback(sessionId, {
        feedback_id: `fb_${taskId}`,
        task_id: taskId,
        completion,
        actual_minutes: 30,
        quiz: completion === "done" ? { score: 4, total: 5 } : { score: 2, total: 5 },
        reflection: t("Quick feedback submitted from Goal board."),
      });
      setStatusText(t("Feedback accepted."));
      const shouldReplanNow = window.confirm(t("反馈已提交，是否基于最新反馈立即重排计划？"));
      if (shouldReplanNow) {
        setReplanLoading(true);
        setTaskNoticeByTask((prev) => ({ ...prev, [taskId]: t("正在根据最新反馈重排计划...") }));
        const replanResult = await replanGoalSession(sessionId, "manual_feedback");
        const replanPayload = replanResult?.data as { diff?: ReplanDiff } | undefined;
        setReplanDiff(replanPayload?.diff || null);
        await refreshDay();
        setStatusText(t("Replan finished."));
      } else {
        setTaskNoticeByTask((prev) => ({ ...prev, [taskId]: t("反馈已提交，可稍后手动触发重排。") }));
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : t("Failed to submit feedback");
      setTaskErrorByTask((prev) => ({ ...prev, [taskId]: message }));
      setError(message);
    } finally {
      setReplanLoading(false);
      setFeedbackLoadingByTask((prev) => ({ ...prev, [taskId]: false }));
    }
  };

  const handleGeneratePractice = async (taskId: string) => {
    setPracticeLoadingByTask((prev) => ({ ...prev, [taskId]: true }));
    setTaskErrorByTask((prev) => ({ ...prev, [taskId]: "" }));
    setTaskNoticeByTask((prev) => ({ ...prev, [taskId]: "" }));
    setError("");
    setStatusText(t("Generating practice..."));
    try {
      const result = await generateGoalPractice(sessionId, taskId, {
        count: 3,
        difficulty: "medium",
        question_type: "short_answer",
      });
      const payload = result.data.practice_set as { questions?: PracticeItem[] };
      const questions = payload.questions || [];
      setPracticeByTask((prev) => ({ ...prev, [taskId]: questions }));
      setStatusText(t("Practice generated."));
      if (questions.length === 0) {
        setTaskNoticeByTask((prev) => ({ ...prev, [taskId]: t("本次未生成题目，可重试一次。") }));
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : t("Failed to generate practice");
      setTaskErrorByTask((prev) => ({ ...prev, [taskId]: message }));
      setError(message);
    } finally {
      setPracticeLoadingByTask((prev) => ({ ...prev, [taskId]: false }));
    }
  };

  return (
    <div className="h-screen overflow-y-auto bg-[radial-gradient(circle_at_top_left,_rgba(195,90,44,0.12),_transparent_28%),linear-gradient(180deg,_rgba(255,255,255,0.25),_transparent_40%)] px-6 py-8">
      <div className="mx-auto grid max-w-7xl gap-4 lg:grid-cols-[320px_1fr]">
        <aside className="lg:sticky lg:top-6 lg:h-[calc(100vh-3rem)]">
          <div className="flex h-full flex-col overflow-hidden rounded-2xl border bg-white">
            <div className="border-b px-4 py-3 text-sm font-medium text-[var(--foreground)]">
              {t("Learning Assistant")}
            </div>
            <div className="flex-1 space-y-3 overflow-y-auto p-4">
              {messages.map((msg) => (
                <div
                  key={msg.id}
                  className={`max-w-[95%] rounded-xl px-3 py-2 text-sm leading-6 ${
                    msg.role === "user"
                      ? "ml-auto bg-[var(--primary)] text-white"
                      : "bg-[var(--secondary)] text-[var(--foreground)]"
                  }`}
                >
                  {msg.content}
                </div>
              ))}
            </div>
            <div className="border-t p-3">
              <div className="flex items-center gap-2">
                <input
                  value={question}
                  onChange={(event) => setQuestion(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !event.shiftKey) {
                      event.preventDefault();
                      void askAssistant();
                    }
                  }}
                  placeholder={t("Ask about key points, framework, or pitfalls...")}
                  className="flex-1 rounded-xl border px-3 py-2 text-sm outline-none transition focus:border-[var(--ring)] focus:ring-2 focus:ring-[var(--ring)]/10"
                />
                <button
                  type="button"
                  onClick={() => void askAssistant()}
                  disabled={!question.trim() || asking}
                  className="rounded-xl bg-[var(--primary)] p-2 text-white transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {asking ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                </button>
              </div>
            </div>
          </div>
        </aside>

        <main className="flex flex-col gap-5">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-semibold text-[var(--foreground)]">
                {t("Day Plan Detail")} · {t("Day {{count}}", { count: dayIndex })}
              </h1>
              {detail?.date ? (
                <p className="mt-1 text-sm text-[var(--muted-foreground)]">{detail.date}</p>
              ) : null}
            </div>
            <Link
              href="/goal"
              className="rounded-xl border px-4 py-2 text-sm text-[var(--muted-foreground)] transition hover:bg-[var(--secondary)]"
            >
              {t("Back to Goal Board")}
            </Link>
          </div>

          {loading ? (
            <div className="rounded-2xl border bg-[var(--card)] px-4 py-3 text-sm text-[var(--muted-foreground)]">
              {t("Loading day plan...")}
            </div>
          ) : null}

          {error ? (
            <div className="rounded-2xl border border-[var(--destructive)]/20 bg-[var(--destructive)]/5 px-4 py-3 text-sm text-[var(--destructive)]">
              {error}
            </div>
          ) : null}

          {statusText ? (
            <div className="rounded-2xl border bg-[var(--secondary)]/70 px-4 py-3 text-sm text-[var(--foreground)]">
              {statusText}
            </div>
          ) : null}

          {detail ? (
            <>
              <section className="surface-card p-5">
              <h2 className="text-sm font-semibold text-[var(--foreground)]">{t("Today's Objective")}</h2>
              <p className="mt-2 text-sm leading-7 text-[var(--muted-foreground)]">{detail.objective_summary}</p>
              </section>

              <section className="surface-card p-5">
              <h2 className="text-sm font-semibold text-[var(--foreground)]">{t("Time Blocks")}</h2>
              <div className="mt-3 grid gap-3">
                {detail.time_blocks.map((block) => (
                  <article key={block.block_id} className="rounded-2xl border bg-white/90 p-4">
                    <div className="flex items-center justify-between">
                      <div className="text-sm font-medium text-[var(--foreground)]">{block.title}</div>
                      <div className="text-xs text-[var(--muted-foreground)]">
                        {block.kind.toUpperCase()} · {t("{{count}} min", { count: block.minutes })}
                      </div>
                    </div>
                    <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm text-[var(--muted-foreground)]">
                      {block.steps.map((step, index) => (
                        <li key={`${block.block_id}_${index}`}>{step}</li>
                      ))}
                    </ol>
                  </article>
                ))}
              </div>
              </section>

              <section className="grid gap-4 lg:grid-cols-2">
              <CardList title={t("Key Points")} items={detail.key_points} />
              <CardList title={t("Pitfalls")} items={detail.pitfalls} />
              <CardList title={t("Acceptance Criteria")} items={detail.acceptance_criteria} />
              <CardList title={t("Review Actions")} items={detail.review_actions} />
              </section>

              <section className="surface-card p-5">
              <h2 className="text-sm font-semibold text-[var(--foreground)]">{t("Linked Tasks")}</h2>
              {detail.linked_task_ids.length ? (
                <div className="mt-3 flex flex-wrap gap-2">
                  {detail.linked_task_ids.map((taskId) => (
                    <span
                      key={taskId}
                      className="rounded-full bg-[var(--secondary)] px-3 py-1 text-xs text-[var(--muted-foreground)]"
                    >
                      {taskId}
                    </span>
                  ))}
                </div>
              ) : (
                <p className="mt-2 text-sm text-[var(--muted-foreground)]">{t("No linked tasks.")}</p>
              )}
              </section>

              <section className="surface-card p-5">
                <div className="flex items-center justify-between">
                  <h2 className="text-sm font-semibold text-[var(--foreground)]">{t("Interactive Lesson")}</h2>
                  <button
                    type="button"
                    onClick={() => void loadLesson(true)}
                    disabled={lessonLoading}
                    className="rounded-xl border px-4 py-2 text-xs text-[var(--muted-foreground)] transition hover:bg-[var(--secondary)] disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {t("Regenerate Lesson")}
                  </button>
                </div>
                {lessonLoading ? (
                  <div className="mt-3 rounded-2xl border bg-[var(--card)] px-4 py-3 text-sm text-[var(--muted-foreground)]">
                    {t("Generating interactive lesson...")}
                  </div>
                ) : null}
                {lessonError ? (
                  <div className="mt-3 rounded-2xl border border-[var(--destructive)]/20 bg-[var(--destructive)]/5 px-4 py-3 text-sm text-[var(--destructive)]">
                    {lessonError}
                  </div>
                ) : null}
                {!lessonLoading && !lessonError && lessonHtmlWithMath ? (
                  <div className="mt-3 h-[78vh] overflow-hidden rounded-2xl border bg-white">
                    <iframe
                      className="h-full w-full border-0"
                      title={t("Interactive Lesson")}
                      sandbox="allow-scripts allow-same-origin"
                      srcDoc={lessonHtmlWithMath}
                    />
                  </div>
                ) : null}
              </section>

              <section className="surface-card p-5">
              <h2 className="text-sm font-semibold text-[var(--foreground)]">{t("Task Actions")}</h2>
              {!tasks.length ? (
                <p className="mt-2 text-sm text-[var(--muted-foreground)]">{t("No tasks for this day.")}</p>
              ) : (
                <div className="mt-3 space-y-3">
                  {tasks.map((task) => (
                    <article key={task.task_id} className="rounded-2xl border bg-white/90 p-4">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-xs font-medium uppercase tracking-[0.16em] text-[var(--primary)]">
                          {task.kind}
                        </span>
                        <span className="text-[11px] text-[var(--muted-foreground)]">
                          {t("{{count}} min", { count: task.estimate_minutes })}
                        </span>
                      </div>
                      <div className="mt-2 text-sm font-medium text-[var(--foreground)]">{task.title}</div>
                      <p className="mt-1 text-xs leading-6 text-[var(--muted-foreground)]">{task.objective}</p>

                      <div className="mt-3 flex items-center gap-2">
                        <select
                          value={feedbackState[task.task_id] || "done"}
                          onChange={(event) =>
                            setFeedbackState((prev) => ({
                              ...prev,
                              [task.task_id]: event.target.value as "done" | "partial" | "missed" | "skipped",
                            }))
                          }
                          className="rounded-xl border bg-[var(--card)] px-3 py-2 text-xs outline-none"
                        >
                          {completionOptions.map(([optionValue, optionLabel]) => (
                            <option key={optionValue} value={optionValue}>
                              {optionLabel}
                            </option>
                          ))}
                        </select>
                        <Button
                          variant="secondary"
                          size="sm"
                          loading={feedbackLoadingByTask[task.task_id]}
                          disabled={replanLoading}
                          onClick={() => void handleSubmitFeedback(task.task_id)}
                        >
                          {t("提交反馈")}
                        </Button>
                        <Button
                          variant="secondary"
                          size="sm"
                          loading={practiceLoadingByTask[task.task_id]}
                          onClick={() => void handleGeneratePractice(task.task_id)}
                        >
                          {t("一键出题")}
                        </Button>
                      </div>

                      {taskErrorByTask[task.task_id] ? (
                        <div className="mt-3 rounded-xl border border-[var(--destructive)]/20 bg-[var(--destructive)]/5 px-3 py-2 text-xs text-[var(--destructive)]">
                          <div>{taskErrorByTask[task.task_id]}</div>
                          <button
                            type="button"
                            className="mt-1 text-[11px] underline underline-offset-2"
                            onClick={() => void handleGeneratePractice(task.task_id)}
                          >
                            {t("重试出题")}
                          </button>
                        </div>
                      ) : null}

                      {taskNoticeByTask[task.task_id] ? (
                        <div className="mt-3 rounded-xl border border-[var(--border)] bg-[var(--secondary)]/35 px-3 py-2 text-xs text-[var(--muted-foreground)]">
                          {taskNoticeByTask[task.task_id]}
                        </div>
                      ) : null}

                      {practiceByTask[task.task_id]?.length ? (
                        <div className="mt-3 rounded-2xl border bg-[var(--secondary)]/45 p-3">
                          <div className="mb-2 text-[11px] font-medium uppercase tracking-[0.16em] text-[var(--muted-foreground)]">
                            {t("Practice Preview")}
                          </div>
                          <div className="space-y-2">
                            {practiceByTask[task.task_id].slice(0, 2).map((item, index) => (
                              <div key={`${task.task_id}-${index}`} className="rounded-xl bg-white/80 px-3 py-2 text-xs text-[var(--foreground)]">
                                <div className="font-medium">{item.prompt || item.question || t("Practice question")}</div>
                                {item.reference_answer ? (
                                  <div className="mt-1 text-[var(--muted-foreground)]">{item.reference_answer}</div>
                                ) : null}
                              </div>
                            ))}
                          </div>
                        </div>
                      ) : null}
                    </article>
                  ))}
                </div>
              )}
              </section>

              {replanDiff ? (
                <section className="surface-card p-5">
                  <h2 className="text-sm font-semibold text-[var(--foreground)]">{t("Replan Changes")}</h2>
                  <div className="mt-2 text-sm text-[var(--muted-foreground)]">
                    {t("Added {{count}}", { count: replanDiff.added_tasks?.length || 0 })} ·{" "}
                    {t("Moved {{count}}", { count: replanDiff.moved_tasks?.length || 0 })} ·{" "}
                    {t("Dropped {{count}}", { count: replanDiff.dropped_tasks?.length || 0 })}
                  </div>
                </section>
              ) : null}
            </>
          ) : null}
        </main>
      </div>
    </div>
  );
}

function CardList({ title, items }: { title: string; items: string[] }) {
  return (
    <section className="surface-card p-5">
      <h2 className="text-sm font-semibold text-[var(--foreground)]">{title}</h2>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-sm leading-7 text-[var(--muted-foreground)]">
        {items.map((item, index) => (
          <li key={`${title}_${index}`}>{item}</li>
        ))}
      </ul>
    </section>
  );
}
