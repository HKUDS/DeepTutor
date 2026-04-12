"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { CalendarRange, FileSearch, Flag, LineChart, Sparkles, Target, Upload } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useTranslation } from "react-i18next";

import Button from "@/components/ui/Button";
import { analyzeGoalExamMaterials } from "@/lib/goal-api";

type ExamFrequencyItem = {
  name: string;
  count: number;
  ratio: number;
};

type ExamAnalysisData = {
  question_count: number;
  knowledge_points: ExamFrequencyItem[];
  question_types: ExamFrequencyItem[];
  difficulty_distribution: Record<string, number>;
  insights: string[];
  samples: string[];
  source_breakdown: {
    text_sources: number;
    image_sources: number;
  };
};

const GOAL_SESSION_STORAGE_KEY = "deeptutor.goal.session_id";

export default function ExamRadarPage() {
  const { t } = useTranslation();
  const [sessionId, setSessionId] = useState("");
  const [examFiles, setExamFiles] = useState<File[]>([]);
  const [examText, setExamText] = useState("");
  const [examLoading, setExamLoading] = useState(false);
  const [examError, setExamError] = useState("");
  const [examAnalysis, setExamAnalysis] = useState<ExamAnalysisData | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const saved = window.localStorage.getItem(GOAL_SESSION_STORAGE_KEY);
    if (saved) setSessionId(saved);
  }, []);

  const handleAnalyze = async () => {
    if (!sessionId.trim()) {
      setExamError(t("请先在备考式学习中生成学习路径，再回到考点雷达。"));
      return;
    }
    if (!examText.trim() && examFiles.length === 0) {
      setExamError(t("请至少粘贴题目文本或上传一个文件。"));
      return;
    }

    setExamLoading(true);
    setExamError("");
    try {
      const payload = await analyzeGoalExamMaterials(sessionId.trim(), {
        pastedText: examText,
        files: examFiles,
      });
      setExamAnalysis((payload.data as { analysis?: ExamAnalysisData }).analysis || null);
    } catch (err) {
      setExamError(err instanceof Error ? err.message : t("真题分析失败"));
    } finally {
      setExamLoading(false);
    }
  };

  return (
    <div className="h-screen overflow-y-auto bg-[radial-gradient(circle_at_top_left,_rgba(195,90,44,0.14),_transparent_28%),linear-gradient(180deg,_rgba(255,255,255,0.3),_transparent_40%)] px-6 py-8 animate-fade-in">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <section className="surface-card overflow-hidden border-0 bg-[linear-gradient(135deg,#fff7f0_0%,#f8f1e6_52%,#f4efe8_100%)]">
          <div className="grid gap-6 px-6 py-7 md:grid-cols-[1.3fr_0.9fr] md:px-8">
            <div className="space-y-4">
              <div className="inline-flex items-center gap-2 rounded-full bg-white/80 px-3 py-1 text-xs font-medium text-[var(--primary)] shadow-sm">
                <Sparkles className="h-3.5 w-3.5" />
                {t("Exam Radar")}
              </div>
              <h1 className="max-w-3xl text-3xl font-semibold tracking-tight text-[var(--foreground)] md:text-4xl">
                {t("从真题中提取高频题型与高频考点，给出可执行的冲刺优先级。")}
              </h1>
              <p className="max-w-2xl text-sm leading-7 text-[var(--muted-foreground)] md:text-base">
                {t("支持 PDF、题目截图和文本粘贴，自动统计频次并输出考点 Top 与题型 Top，作为后续备考路径优化依据。")}
              </p>
            </div>

            <div className="grid gap-3 rounded-[28px] border border-white/70 bg-white/80 p-5 shadow-[0_18px_60px_rgba(195,90,44,0.08)] backdrop-blur">
              <Metric icon={Target} label={t("分析目标")} value={t("高频考点挖掘")} />
              <Metric
                icon={CalendarRange}
                label={t("当前样本")}
                value={examAnalysis ? t("{{count}} 题", { count: examAnalysis.question_count }) : t("待分析")}
              />
              <Metric
                icon={LineChart}
                label={t("文本来源")}
                value={examAnalysis ? String(examAnalysis.source_breakdown.text_sources) : "0"}
              />
              <Metric icon={Flag} label={t("关联会话")} value={sessionId || t("尚未创建")} />
            </div>
          </div>
        </section>

        <div className="grid gap-6 lg:grid-cols-[420px_1fr]">
          <section className="surface-card p-5">
            <div className="space-y-4">
              <div>
                <div className="text-sm font-semibold text-[var(--foreground)]">{t("分析输入")}</div>
                <p className="mt-1 text-xs leading-6 text-[var(--muted-foreground)]">
                  {t("建议先在备考式学习中生成路径，再将真题材料在这里统一分析。")}
                </p>
              </div>

              <label className="block space-y-2">
                <span className="text-xs font-medium uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                  {t("会话 ID")}
                </span>
                <input
                  value={sessionId}
                  onChange={(event) => setSessionId(event.target.value)}
                  placeholder={t("输入备考式学习会话 ID")}
                  className="w-full rounded-2xl border bg-[var(--card)] px-4 py-3 text-sm outline-none transition focus:border-[var(--ring)] focus:ring-2 focus:ring-[var(--ring)]/10"
                />
              </label>

              <label className="block space-y-2">
                <span className="text-xs font-medium uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                  {t("真题分析输入")}
                </span>
                <textarea
                  value={examText}
                  onChange={(event) => setExamText(event.target.value)}
                  rows={8}
                  placeholder={t("可粘贴题目原文、考点说明、历年题摘录...")}
                  className="w-full rounded-2xl border bg-[var(--card)] px-4 py-3 text-sm outline-none transition focus:border-[var(--ring)] focus:ring-2 focus:ring-[var(--ring)]/10"
                />
              </label>

              <input
                type="file"
                multiple
                accept=".pdf,.txt,.md,.json,image/*"
                onChange={(event) => setExamFiles(Array.from(event.target.files || []))}
                className="block w-full text-xs text-[var(--muted-foreground)] file:mr-3 file:rounded-xl file:border-0 file:bg-[var(--secondary)] file:px-3 file:py-2 file:text-xs file:text-[var(--foreground)]"
              />

              {examFiles.length > 0 ? (
                <div className="text-xs text-[var(--muted-foreground)]">
                  {t("已选择 {{count}} 个文件", { count: examFiles.length })}
                </div>
              ) : null}

              <Button
                loading={examLoading}
                onClick={() => void handleAnalyze()}
                className="w-full rounded-2xl py-3 text-sm"
                icon={<Upload className="h-4 w-4" />}
              >
                {t("开始分析真题频次")}
              </Button>

              <Link
                href="/goal"
                className="inline-flex w-full items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--card)] px-4 py-3 text-sm text-[var(--foreground)] transition hover:bg-[var(--secondary)]"
              >
                {t("返回备考式学习")}
              </Link>

              {examError ? (
                <div className="rounded-2xl border border-[var(--destructive)]/20 bg-[var(--destructive)]/5 px-4 py-3 text-sm text-[var(--destructive)]">
                  {examError}
                </div>
              ) : null}
            </div>
          </section>

          <section className="surface-card p-5">
            <div className="mb-4 flex items-center gap-2 text-sm font-semibold text-[var(--foreground)]">
              <FileSearch className="h-4 w-4 text-[var(--primary)]" />
              {t("雷达结果面板")}
            </div>

            {examAnalysis ? (
              <div className="space-y-4">
                <div className="rounded-2xl border bg-[var(--secondary)]/45 p-3 text-xs text-[var(--muted-foreground)]">
                  {t("样本题数")}：{examAnalysis.question_count} · {t("文本来源")}：
                  {examAnalysis.source_breakdown.text_sources} · {t("图片来源")}：
                  {examAnalysis.source_breakdown.image_sources}
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                  <div className="rounded-2xl border bg-white/80 p-3">
                    <div className="mb-2 text-xs font-semibold text-[var(--foreground)]">{t("高频考点 Top")}</div>
                    <div className="space-y-1.5">
                      {examAnalysis.knowledge_points.slice(0, 10).map((item) => (
                        <div key={`kp-${item.name}`} className="text-xs text-[var(--muted-foreground)]">
                          {item.name} · {item.count} ({Math.round(item.ratio * 100)}%)
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="rounded-2xl border bg-white/80 p-3">
                    <div className="mb-2 text-xs font-semibold text-[var(--foreground)]">{t("高频题型 Top")}</div>
                    <div className="space-y-1.5">
                      {examAnalysis.question_types.slice(0, 10).map((item) => (
                        <div key={`qt-${item.name}`} className="text-xs text-[var(--muted-foreground)]">
                          {item.name} · {item.count} ({Math.round(item.ratio * 100)}%)
                        </div>
                      ))}
                    </div>
                  </div>
                </div>

                {examAnalysis.insights.length ? (
                  <div className="rounded-2xl border bg-white/80 p-3">
                    <div className="mb-2 text-xs font-semibold text-[var(--foreground)]">{t("分析结论")}</div>
                    <ul className="list-disc space-y-1 pl-5 text-xs text-[var(--muted-foreground)]">
                      {examAnalysis.insights.map((line, index) => (
                        <li key={`ins-${index}`}>{line}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </div>
            ) : (
              <div className="rounded-2xl border border-dashed border-[var(--border)] p-8 text-center text-sm text-[var(--muted-foreground)]">
                {t("上传真题后，这里会展示高频题型与高频考点分析结果。")}
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

function Metric({ icon: Icon, label, value }: { icon: LucideIcon; label: string; value: string }) {
  return (
    <div className="flex items-center gap-3 rounded-2xl border border-[var(--border)]/70 bg-[var(--card)] px-3 py-2.5">
      <div className="rounded-xl bg-[var(--secondary)] p-2 text-[var(--primary)]">
        <Icon className="h-4 w-4" />
      </div>
      <div className="min-w-0">
        <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--muted-foreground)]">
          {label}
        </div>
        <div className="truncate text-sm font-medium text-[var(--foreground)]">{value}</div>
      </div>
    </div>
  );
}
