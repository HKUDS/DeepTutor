"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowRight, CalendarRange, Flag, LineChart, Sparkles, Target } from "lucide-react";
import Link from "next/link";
import { useTranslation } from "react-i18next";

import Button from "@/components/ui/Button";
import { wsUrl } from "@/lib/api";
import {
  createGoalSession,
  getGoalPlan,
  replanGoalSession,
  runGoalPlan,
  type GoalConfigPayload,
} from "@/lib/goal-api";

type GoalPlanTask = {
  task_id: string;
  day_index: number;
  title: string;
  kind: string;
  status?: "pending" | "done" | "skipped";
  estimate_minutes: number;
  objective: string;
};

type GoalPlanDay = {
  day_index: number;
  date?: string;
  budget_minutes: number;
  task_ids: string[];
  notes: string;
};

type GoalPlan = {
  plan_id: string;
  plan_version: number;
  tasks: GoalPlanTask[];
  days: GoalPlanDay[];
};

const DEFAULT_CONFIG: GoalConfigPayload = {
  goal_level: "foundation",
  remaining_days: 7,
  daily_minutes: 90,
  days_per_week: 7,
  preferences: {
    strategy: "high_yield_first",
    include_practice: true,
    practice_ratio: 0.4,
    review_ratio: 0.2,
    language: "en",
  },
};

const GOAL_SESSION_STORAGE_KEY = "deeptutor.goal.session_id";
const GOAL_PLAN_STORAGE_PREFIX = "deeptutor.goal.plan";

function planStorageKey(sessionId: string): string {
  return `${GOAL_PLAN_STORAGE_PREFIX}.${sessionId}`;
}

export default function GoalPage() {
  const { t } = useTranslation();
  const restoredSessionIdRef = useRef<string | null>(null);
  const [goalText, setGoalText] = useState(t("7天内完成微积分核心知识复习，并建立可执行的刷题节奏"));
  const [kbName, setKbName] = useState("placeholder_kb");
  const [config, setConfig] = useState<GoalConfigPayload>(DEFAULT_CONFIG);
  const [sessionId, setSessionId] = useState("");
  const [plan, setPlan] = useState<GoalPlan | null>(null);
  const [loading, setLoading] = useState(false);
  const [replanLoading, setReplanLoading] = useState(false);
  const [error, setError] = useState("");
  const [statusText, setStatusText] = useState("");
  const [wsStage, setWsStage] = useState("");
  const [wsProgress, setWsProgress] = useState<number | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const savedSessionId = window.localStorage.getItem(GOAL_SESSION_STORAGE_KEY);
    if (!savedSessionId) return;
    restoredSessionIdRef.current = savedSessionId;
    setSessionId(savedSessionId);
    const cachedPlan = window.localStorage.getItem(planStorageKey(savedSessionId));
    if (!cachedPlan) return;
    try {
      setPlan(JSON.parse(cachedPlan) as GoalPlan);
    } catch {
      window.localStorage.removeItem(planStorageKey(savedSessionId));
    }
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!sessionId) {
      window.localStorage.removeItem(GOAL_SESSION_STORAGE_KEY);
      return;
    }
    window.localStorage.setItem(GOAL_SESSION_STORAGE_KEY, sessionId);
  }, [sessionId]);

  useEffect(() => {
    if (typeof window === "undefined" || !sessionId || !plan) return;
    window.localStorage.setItem(planStorageKey(sessionId), JSON.stringify(plan));
  }, [sessionId, plan]);

  useEffect(() => {
    if (!sessionId || restoredSessionIdRef.current !== sessionId) return;
    let cancelled = false;
    void getGoalPlan(sessionId)
      .then((payload) => {
        if (cancelled) return;
        setPlan(payload.data as GoalPlan);
      })
      .catch(() => {
        // Keep cached plan if fetch fails, so /goal still renders after back navigation.
      })
      .finally(() => {
        restoredSessionIdRef.current = null;
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  const tasksByDay = useMemo(() => {
    if (!plan) return new Map<number, GoalPlanTask[]>();
    const grouped = new Map<number, GoalPlanTask[]>();
    plan.tasks.forEach((task) => {
      const current = grouped.get(task.day_index) || [];
      current.push(task);
      grouped.set(task.day_index, current);
    });
    return grouped;
  }, [plan]);

  const completionStats = useMemo(() => {
    const total = plan?.tasks.length || 0;
    if (total === 0) return { total: 0, done: 0, skipped: 0, pending: 0, percent: 0 };
    const done = plan?.tasks.filter((task) => task.status === "done").length || 0;
    const skipped = plan?.tasks.filter((task) => task.status === "skipped").length || 0;
    const pending = total - done - skipped;
    const percent = Math.round((done / total) * 100);
    return { total, done, skipped, pending, percent };
  }, [plan]);

  const handleRestoreLatestPlan = async () => {
    if (!sessionId) return;
    setError("");
    setStatusText(t("Restoring latest plan..."));
    try {
      const planPayload = await getGoalPlan(sessionId);
      setPlan(planPayload.data as GoalPlan);
      setStatusText(t("Latest plan restored."));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("Failed to restore latest plan"));
      setStatusText("");
    }
  };

  const runPlanWithWebSocket = async (activeSessionId: string): Promise<GoalPlan> =>
    new Promise<GoalPlan>((resolve, reject) => {
      const socket = new WebSocket(wsUrl(`/api/v1/goal/ws/${activeSessionId}`));
      let settled = false;
      let latestPlan: GoalPlan | null = null;

      const timeout = window.setTimeout(() => {
        if (settled) return;
        settled = true;
        socket.close();
        reject(new Error(t("Planning timed out, please retry.")));
      }, 45_000);

      const fail = (err: Error) => {
        if (settled) return;
        settled = true;
        window.clearTimeout(timeout);
        socket.close();
        reject(err);
      };

      const succeed = (resolvedPlan: GoalPlan) => {
        if (settled) return;
        settled = true;
        window.clearTimeout(timeout);
        socket.close();
        resolve(resolvedPlan);
      };

      socket.onopen = () => {
        socket.send(JSON.stringify({ type: "run_plan" }));
      };

      socket.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data) as {
            type?: string;
            stage?: string;
            progress?: number;
            content?: string;
            code?: string;
            data?: GoalPlan;
          };
          if (payload.type === "stage") {
            if (payload.stage) setWsStage(payload.stage);
            if (typeof payload.progress === "number") {
              setWsProgress(Math.max(0, Math.min(100, Math.round(payload.progress * 100))));
            }
            if (payload.content) setStatusText(payload.content);
            return;
          }
          if (payload.type === "plan" && payload.data) {
            latestPlan = payload.data;
            setPlan(payload.data);
            return;
          }
          if (payload.type === "error") {
            const prefix = payload.code ? `[${payload.code}] ` : "";
            fail(new Error(`${prefix}${payload.content || t("Planner failed")}`));
            return;
          }
          if (payload.type === "complete") {
            if (latestPlan) {
              succeed(latestPlan);
              return;
            }
            void getGoalPlan(activeSessionId)
              .then((planPayload) => succeed(planPayload.data as GoalPlan))
              .catch((err) =>
                fail(err instanceof Error ? err : new Error(t("Failed to load generated plan"))),
              );
          }
        } catch {
          fail(new Error(t("Received invalid planner stream message")));
        }
      };

      socket.onerror = () => fail(new Error(t("WebSocket planning failed")));
      socket.onclose = () => {
        if (!settled && !latestPlan) {
          fail(new Error(t("Planning stream closed unexpectedly")));
        }
      };
    });

  const handleGenerate = async () => {
    setLoading(true);
    setError("");
    setWsStage("");
    setWsProgress(null);
    setStatusText(t("Creating goal session..."));
    try {
      const sessionPayload = await createGoalSession(kbName, {
        ...config,
        goal_statement: goalText.trim(),
      });
      const createdSessionId = sessionPayload.data.session_id as string;
      setSessionId(createdSessionId);
      setStatusText(t("Running planner stream..."));
      try {
        const streamedPlan = await runPlanWithWebSocket(createdSessionId);
        setPlan(streamedPlan);
      } catch {
        setStatusText(t("WebSocket unavailable, falling back to REST planning..."));
        await runGoalPlan(createdSessionId);
        const planPayload = await getGoalPlan(createdSessionId);
        setPlan(planPayload.data as GoalPlan);
      }
      setStatusText(t("Plan generated."));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("Failed to generate goal plan"));
      setStatusText("");
    } finally {
      setLoading(false);
    }
  };

  const handleReplan = async () => {
    if (!sessionId) return;
    setReplanLoading(true);
    setError("");
    setStatusText(t("Replanning from latest feedback..."));
    try {
      await replanGoalSession(sessionId, "manual_feedback");
      const planPayload = await getGoalPlan(sessionId);
      setPlan(planPayload.data as GoalPlan);
      setStatusText(t("Replan finished."));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("Failed to replan"));
    } finally {
      setReplanLoading(false);
    }
  };

  return (
    <div className="h-screen overflow-y-auto bg-[radial-gradient(circle_at_top_left,_rgba(195,90,44,0.14),_transparent_28%),linear-gradient(180deg,_rgba(255,255,255,0.3),_transparent_40%)] px-6 py-8">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <section className="surface-card overflow-hidden border-0 bg-[linear-gradient(135deg,#fff7f0_0%,#f8f1e6_52%,#f4efe8_100%)]">
          <div className="grid gap-6 px-6 py-7 md:grid-cols-[1.3fr_0.9fr] md:px-8">
            <div className="space-y-4">
              <div className="inline-flex items-center gap-2 rounded-full bg-white/80 px-3 py-1 text-xs font-medium text-[var(--primary)] shadow-sm">
                <Sparkles className="h-3.5 w-3.5" />
                {t("Goal-Oriented Adaptive Learning Mode")}
              </div>
              <h1 className="max-w-3xl text-3xl font-semibold tracking-tight text-[var(--foreground)] md:text-4xl">
                {t("把模糊的学习目标，压缩成按天可执行的计划。")}
              </h1>
              <p className="max-w-2xl text-sm leading-7 text-[var(--muted-foreground)] md:text-base">
                {t("当前版本支持在没有知识库的情况下先生成骨架计划，方便你先演示完整链路；后续接入真实 KB 后，计划会自动替换成更细的知识点图谱。")}
              </p>
            </div>

            <div className="grid gap-3 rounded-[28px] border border-white/70 bg-white/80 p-5 shadow-[0_18px_60px_rgba(195,90,44,0.08)] backdrop-blur">
              <Metric icon={Target} label={t("目标级别")} value={config.goal_level} />
              <Metric icon={CalendarRange} label={t("学习周期")} value={t("{{count}} 天", { count: config.remaining_days })} />
              <Metric icon={LineChart} label={t("每日预算")} value={t("{{count}} 分钟", { count: config.daily_minutes })} />
              <Metric icon={Flag} label={t("当前会话")} value={sessionId || t("尚未创建")} />
            </div>
          </div>
        </section>

        <div className="grid gap-6 lg:grid-cols-[380px_1fr]">
          <section className="surface-card p-5">
            <div className="space-y-5">
              <div>
                <div className="text-sm font-semibold text-[var(--foreground)]">{t("Goal Form")}</div>
                <p className="mt-1 text-xs leading-6 text-[var(--muted-foreground)]">
                  {t("先用兜底 KB 跑通 MVP，后面替换成真实知识库即可。")}
                </p>
              </div>

              <label className="block space-y-2">
                <span className="text-xs font-medium uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                  {t("Learning Goal")}
                </span>
                <textarea
                  value={goalText}
                  onChange={(event) => setGoalText(event.target.value)}
                  rows={5}
                  placeholder={t("输入你的学习目标、时间约束和希望达到的水平")}
                  className="w-full rounded-2xl border bg-[var(--card)] px-4 py-3 text-sm outline-none transition focus:border-[var(--ring)] focus:ring-2 focus:ring-[var(--ring)]/10"
                />
              </label>

              <label className="block space-y-2">
                <span className="text-xs font-medium uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                  {t("KB Name")}
                </span>
                <input
                  value={kbName}
                  onChange={(event) => setKbName(event.target.value)}
                  placeholder={t("placeholder_kb")}
                  className="w-full rounded-2xl border bg-[var(--card)] px-4 py-3 text-sm outline-none transition focus:border-[var(--ring)] focus:ring-2 focus:ring-[var(--ring)]/10"
                />
              </label>

              <div className="grid gap-4 sm:grid-cols-2">
                <Control
                  label={t("Goal Level")}
                  value={config.goal_level}
                  onChange={(value) => setConfig((prev) => ({ ...prev, goal_level: value as GoalConfigPayload["goal_level"] }))}
                  options={[
                    ["foundation", t("Foundation")],
                    ["competent", t("Competent")],
                    ["advanced", t("Advanced")],
                  ]}
                />
                <Control
                  label={t("Strategy")}
                  value={config.preferences.strategy}
                  onChange={(value) =>
                    setConfig((prev) => ({
                      ...prev,
                      preferences: { ...prev.preferences, strategy: value as GoalConfigPayload["preferences"]["strategy"] },
                    }))
                  }
                  options={[
                    ["high_yield_first", t("High Yield")],
                    ["depth_first", t("Depth First")],
                    ["breadth_first", t("Breadth First")],
                  ]}
                />
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <NumberField
                  label={t("Remaining Days")}
                  value={config.remaining_days}
                  onChange={(value) => setConfig((prev) => ({ ...prev, remaining_days: value }))}
                />
                <NumberField
                  label={t("Daily Minutes")}
                  value={config.daily_minutes}
                  onChange={(value) => setConfig((prev) => ({ ...prev, daily_minutes: value }))}
                />
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <NumberField
                  label={t("Days per Week")}
                  value={config.days_per_week}
                  min={1}
                  max={7}
                  onChange={(value) => setConfig((prev) => ({ ...prev, days_per_week: Math.max(1, Math.min(7, value)) }))}
                />
                <label className="block space-y-2">
                  <span className="text-xs font-medium uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                    {t("Include Practice")}
                  </span>
                  <div className="flex h-[46px] items-center justify-between rounded-2xl border bg-[var(--card)] px-4">
                    <span className="text-sm text-[var(--foreground)]">
                      {config.preferences.include_practice ? t("Enabled") : t("Disabled")}
                    </span>
                    <input
                      type="checkbox"
                      checked={config.preferences.include_practice}
                      onChange={(event) =>
                        setConfig((prev) => ({
                          ...prev,
                          preferences: { ...prev.preferences, include_practice: event.target.checked },
                        }))
                      }
                      className="h-4 w-4 accent-[var(--primary)]"
                    />
                  </div>
                </label>
              </div>

              <Button
                loading={loading}
                onClick={handleGenerate}
                className="w-full rounded-2xl py-3 text-sm"
                icon={<ArrowRight className="h-4 w-4" />}
              >
                {t("生成学习路径")}
              </Button>

              <Link
                href="/exam-radar"
                className="inline-flex w-full items-center justify-center rounded-2xl bg-[var(--secondary)] px-4 py-3 text-sm font-medium text-[var(--secondary-foreground)] transition hover:bg-[var(--muted)]"
              >
                {t("前往考点雷达")}
              </Link>

              {statusText ? (
                <div className="rounded-2xl border bg-[var(--secondary)]/70 px-4 py-3 text-sm text-[var(--foreground)]">
                  {statusText}
                </div>
              ) : null}

              {error ? (
                <div className="rounded-2xl border border-[var(--destructive)]/20 bg-[var(--destructive)]/5 px-4 py-3 text-sm text-[var(--destructive)]">
                  {error}
                </div>
              ) : null}
            </div>
          </section>

          <section className="grid gap-6">
            <div className="surface-card p-5">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <div className="text-sm font-semibold text-[var(--foreground)]">{t("Planning Progress")}</div>
                  <p className="mt-1 text-xs text-[var(--muted-foreground)]">
                    {t("创建 Session 后会通过 WebSocket 返回阶段进度，并在完成时推送最新计划。")}
                  </p>
                  <div className="mt-3 flex items-center gap-2 text-xs text-[var(--muted-foreground)]">
                    <span>{t("Task Completion")}</span>
                    <span className="font-medium text-[var(--foreground)]">
                      {t("{{count}}%", { count: completionStats.percent })}
                    </span>
                    <span>
                      {t("Completed {{done}}/{{total}}", {
                        done: completionStats.done,
                        total: completionStats.total,
                      })}
                    </span>
                  </div>
                  <div className="mt-1 text-xs text-[var(--muted-foreground)]">
                    {t("Done {{count}}", { count: completionStats.done })} ·{" "}
                    {t("Skipped {{count}}", { count: completionStats.skipped })} ·{" "}
                    {t("Pending {{count}}", { count: completionStats.pending })}
                  </div>
                  <div className="mt-2 h-2 overflow-hidden rounded-full bg-[var(--muted)]">
                    <div
                      className="h-full rounded-full bg-[var(--primary)] transition-[width] duration-300"
                      style={{ width: `${completionStats.percent}%` }}
                    />
                  </div>
                </div>
                <div className="rounded-full bg-[var(--muted)] px-3 py-1 text-xs text-[var(--muted-foreground)]">
                  {loading
                    ? wsProgress !== null
                      ? t("{{count}}%", { count: wsProgress })
                      : t("Planning...")
                    : plan
                      ? t("Plan v{{version}}", { version: plan.plan_version })
                      : t("Idle")}
                </div>
              </div>
              {loading ? (
                <div className="mt-4 space-y-2">
                  <div className="text-xs text-[var(--muted-foreground)]">
                    {wsStage ? t("阶段：{{stage}}", { stage: wsStage }) : t("等待阶段消息...")}
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-[var(--muted)]">
                    <div
                      className="h-full rounded-full bg-[var(--primary)] transition-[width] duration-300"
                      style={{ width: `${wsProgress ?? 10}%` }}
                    />
                  </div>
                </div>
              ) : null}
            </div>

            <div className="surface-card p-5">
              <div className="mb-4 flex items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-semibold text-[var(--foreground)]">{t("Plan Board")}</div>
                  <p className="mt-1 text-xs text-[var(--muted-foreground)]">
                    {t("没有 KB 时会显示 scaffolded plan，便于先联调整条链路。")}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <div className="muted-chip">
                    {plan ? t("{{count}} tasks", { count: plan.tasks.length }) : t("No plan yet")}
                  </div>
                  <Button
                    variant="secondary"
                    size="sm"
                    loading={replanLoading}
                    disabled={!sessionId || !plan}
                    onClick={handleReplan}
                  >
                    {t("触发重排")}
                  </Button>
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={!sessionId}
                    onClick={() => void handleRestoreLatestPlan()}
                  >
                    {t("Restore Latest Plan")}
                  </Button>
                </div>
              </div>

              {!plan ? (
                <div className="rounded-[24px] border border-dashed bg-[var(--secondary)]/55 px-6 py-12 text-center text-sm text-[var(--muted-foreground)]">
                  {t("生成后会在这里按天展示任务卡片。")}
                </div>
              ) : (
                <div className="grid gap-4 xl:grid-cols-3">
                  {plan.days.map((day) => (
                    <article key={day.day_index} className="rounded-[26px] border bg-[linear-gradient(180deg,rgba(255,255,255,0.95),rgba(248,244,238,0.92))] p-4 shadow-sm">
                      <div className="mb-4 flex items-start justify-between gap-3">
                        <div>
                          <div className="text-sm font-semibold text-[var(--foreground)]">{t("Day {{count}}", { count: day.day_index })}</div>
                          <div className="mt-1 text-xs text-[var(--muted-foreground)]">{day.date || t("TBD")}</div>
                        </div>
                        <div className="flex flex-col items-end gap-2">
                          <div className="rounded-full bg-[var(--secondary)] px-2.5 py-1 text-[11px] text-[var(--muted-foreground)]">
                            {t("{{count}} min", { count: day.budget_minutes })}
                          </div>
                          {sessionId ? (
                            <Link
                              href={`/goal/${sessionId}/day/${day.day_index}`}
                              className="rounded-full border px-2.5 py-1 text-[11px] text-[var(--muted-foreground)] transition hover:bg-[var(--secondary)]"
                            >
                              {t("View Day Details")}
                            </Link>
                          ) : null}
                        </div>
                      </div>

                      <div className="space-y-3">
                        {(tasksByDay.get(day.day_index) || []).map((task) => (
                          <div key={task.task_id} className="rounded-2xl border bg-white/90 p-3">
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
                          </div>
                        ))}
                      </div>
                    </article>
                  ))}
                </div>
              )}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}

function Metric({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Target;
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-center gap-3 rounded-2xl border border-[var(--border)]/60 bg-white/75 px-4 py-3">
      <div className="rounded-xl bg-[var(--secondary)] p-2 text-[var(--primary)]">
        <Icon className="h-4 w-4" />
      </div>
      <div className="min-w-0">
        <div className="text-[11px] uppercase tracking-[0.18em] text-[var(--muted-foreground)]">{label}</div>
        <div className="truncate text-sm font-medium text-[var(--foreground)]">{value}</div>
      </div>
    </div>
  );
}

function Control({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: [string, string][];
}) {
  return (
    <label className="block space-y-2">
      <span className="text-xs font-medium uppercase tracking-[0.18em] text-[var(--muted-foreground)]">{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-2xl border bg-[var(--card)] px-4 py-3 text-sm outline-none transition focus:border-[var(--ring)] focus:ring-2 focus:ring-[var(--ring)]/10"
      >
        {options.map(([optionValue, optionLabel]) => (
          <option key={optionValue} value={optionValue}>
            {optionLabel}
          </option>
        ))}
      </select>
    </label>
  );
}

function NumberField({
  label,
  value,
  min = 1,
  max,
  onChange,
}: {
  label: string;
  value: number;
  min?: number;
  max?: number;
  onChange: (value: number) => void;
}) {
  return (
    <label className="block space-y-2">
      <span className="text-xs font-medium uppercase tracking-[0.18em] text-[var(--muted-foreground)]">{label}</span>
      <input
        type="number"
        min={min}
        max={max}
        value={value}
        onChange={(event) => {
          const numeric = Number(event.target.value) || min;
          const bounded = max !== undefined ? Math.min(max, Math.max(min, numeric)) : Math.max(min, numeric);
          onChange(bounded);
        }}
        className="w-full rounded-2xl border bg-[var(--card)] px-4 py-3 text-sm outline-none transition focus:border-[var(--ring)] focus:ring-2 focus:ring-[var(--ring)]/10"
      />
    </label>
  );
}
