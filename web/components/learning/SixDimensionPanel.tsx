"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Chart as ChartJS,
  Filler,
  Legend,
  LineElement,
  PointElement,
  RadialLinearScale,
  Tooltip,
  type ChartData,
  type ChartOptions,
} from "chart.js";
import {
  BookOpen,
  Brain,
  CalendarCheck,
  History,
  Lightbulb,
  ListChecks,
  Loader2,
  RefreshCw,
  Shuffle,
} from "lucide-react";
import { Radar } from "react-chartjs-2";
import { useTranslation } from "react-i18next";

import SixDimensionEvidenceDrawer from "./SixDimensionEvidenceDrawer";
import {
  fetchSixDimensionSnapshot,
  type SixDimensionKey,
  type SixDimensionResult,
  type SixDimensionSnapshot,
} from "@/lib/learning-api";

ChartJS.register(
  RadialLinearScale,
  PointElement,
  LineElement,
  Filler,
  Tooltip,
  Legend,
);

const DIMENSION_META = {
  knowledge: { zh: "知识", en: "Knowledge", Icon: BookOpen },
  procedure: { zh: "解题程序", en: "Procedure", Icon: ListChecks },
  understanding: { zh: "理解", en: "Understanding", Icon: Lightbulb },
  transfer: { zh: "迁移", en: "Transfer", Icon: Shuffle },
  retention: { zh: "保持", en: "Retention", Icon: History },
  habit: { zh: "习惯", en: "Habit", Icon: CalendarCheck },
} satisfies Record<
  SixDimensionKey,
  { zh: string; en: string; Icon: typeof BookOpen }
>;

interface SixDimensionPanelProps {
  bookId: string;
  className?: string;
}

export default function SixDimensionPanel({
  bookId,
  className = "",
}: SixDimensionPanelProps) {
  const { i18n } = useTranslation();
  const zh = i18n.language?.toLowerCase().startsWith("zh");
  const tr = useCallback((cn: string, en: string) => (zh ? cn : en), [zh]);
  const [snapshot, setSnapshot] = useState<SixDimensionSnapshot | null>(null);
  const [selected, setSelected] = useState<SixDimensionResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [chartColors, setChartColors] = useState({
    primary: "#2563eb",
    border: "#e5e5e5",
    muted: "#737373",
  });

  const loadSnapshot = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      setSnapshot(await fetchSixDimensionSnapshot(bookId));
    } catch {
      setSnapshot(null);
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [bookId]);

  useEffect(() => {
    void loadSnapshot();
  }, [loadSnapshot]);

  useEffect(() => {
    const styles = getComputedStyle(document.documentElement);
    setChartColors({
      primary: styles.getPropertyValue("--primary").trim() || "#2563eb",
      border: styles.getPropertyValue("--border").trim() || "#e5e5e5",
      muted:
        styles.getPropertyValue("--muted-foreground").trim() || "#737373",
    });
  }, []);

  const scoredCount =
    snapshot?.dimensions.filter((dimension) => dimension.data_state === "scored")
      .length ?? 0;

  const chartData = useMemo<ChartData<"radar", (number | null)[], string>>(
    () => ({
      labels:
        snapshot?.dimensions.map((dimension) => {
          const meta = DIMENSION_META[dimension.key];
          return zh ? meta.zh : meta.en;
        }) ?? [],
      datasets: [
        {
          label: tr("学习画像", "Learning profile"),
          data: snapshot?.dimensions.map((dimension) => dimension.score) ?? [],
          backgroundColor: "rgba(37, 99, 235, 0.14)",
          borderColor: chartColors.primary,
          borderWidth: 2,
          pointBackgroundColor: chartColors.primary,
          pointBorderColor: chartColors.primary,
          pointRadius: 3,
          spanGaps: false,
        },
      ],
    }),
    [chartColors.primary, snapshot, tr, zh],
  );

  const chartOptions = useMemo<ChartOptions<"radar">>(
    () => ({
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 240 },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (context) => `${context.formattedValue} / 100`,
          },
        },
      },
      scales: {
        r: {
          min: 0,
          max: 100,
          ticks: {
            display: false,
            stepSize: 25,
          },
          angleLines: { color: chartColors.border },
          grid: { color: chartColors.border },
          pointLabels: {
            color: chartColors.muted,
            font: { size: 11 },
          },
        },
      },
    }),
    [chartColors],
  );

  return (
    <section
      aria-labelledby="six-dimension-title"
      className={`rounded-xl border border-[var(--border)] bg-[var(--card)] p-4 sm:p-5 ${className}`}
    >
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <Brain className="h-5 w-5 text-[var(--primary)]" aria-hidden="true" />
            <h2
              id="six-dimension-title"
              className="text-base font-semibold text-[var(--foreground)]"
            >
              {tr("六维学习画像", "Six-dimension learning profile")}
            </h2>
          </div>
          <p className="mt-1 text-xs leading-5 text-[var(--muted-foreground)]">
            {tr(
              "每个分数都来自可回溯证据；证据不足不会显示成低分。",
              "Every score is traceable; missing evidence is never shown as a low score.",
            )}
          </p>
        </div>
        {snapshot?.overall !== null && snapshot?.overall !== undefined && (
          <div className="rounded-lg bg-[var(--accent)] px-3 py-2 text-right">
            <p className="text-[10px] uppercase tracking-wide text-[var(--muted-foreground)]">
              {tr("有据维度均分", "Evidence-backed average")}
            </p>
            <p className="text-lg font-semibold text-[var(--foreground)]">
              {Math.round(snapshot.overall)}
            </p>
          </div>
        )}
      </header>

      {loading ? (
        <div className="flex min-h-48 items-center justify-center text-[var(--muted-foreground)]">
          <Loader2 className="h-5 w-5 animate-spin" aria-label={tr("加载中", "Loading")} />
        </div>
      ) : error ? (
        <div className="flex min-h-48 flex-col items-center justify-center gap-3 text-center">
          <p className="text-sm text-[var(--muted-foreground)]">
            {tr("学习画像暂时加载失败。", "The learner profile could not be loaded.")}
          </p>
          <button
            type="button"
            onClick={() => void loadSnapshot()}
            className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm text-[var(--foreground)] transition-colors hover:bg-[var(--accent)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]"
          >
            <RefreshCw className="h-4 w-4" aria-hidden="true" />
            {tr("重试", "Retry")}
          </button>
        </div>
      ) : snapshot ? (
        <>
          {scoredCount >= 3 ? (
            <div
              role="img"
              className="mx-auto mt-4 h-64 w-full max-w-lg sm:h-72"
              aria-label={tr("六维雷达图", "Six-dimension radar chart")}
            >
              <Radar data={chartData} options={chartOptions} />
            </div>
          ) : (
            <div className="mt-4 rounded-lg border border-dashed border-[var(--border)] px-4 py-5 text-center">
              <p className="text-sm font-medium text-[var(--foreground)]">
                {tr("再积累一些证据后生成雷达图", "More evidence is needed for the radar chart")}
              </p>
              <p className="mt-1 text-xs text-[var(--muted-foreground)]">
                {tr(
                  `当前 ${scoredCount}/6 个维度可评分，至少需要 3 个。`,
                  `${scoredCount}/6 dimensions are scored; at least 3 are required.`,
                )}
              </p>
            </div>
          )}

          <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {snapshot.dimensions.map((dimension) => {
              const meta = DIMENSION_META[dimension.key];
              const Icon = meta.Icon;
              const scored = dimension.data_state === "scored";
              return (
                <button
                  key={dimension.key}
                  type="button"
                  onClick={() => setSelected(dimension)}
                  aria-label={tr(
                    `查看${meta.zh}维度证据`,
                    `View ${meta.en} evidence`,
                  )}
                  className="group rounded-xl border border-[var(--border)] p-4 text-left transition-all hover:-translate-y-0.5 hover:border-[var(--primary)]/35 hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-center gap-2">
                      <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--accent)] text-[var(--primary)]">
                        <Icon className="h-4 w-4" aria-hidden="true" />
                      </span>
                      <span className="text-sm font-medium text-[var(--foreground)]">
                        {zh ? meta.zh : meta.en}
                      </span>
                    </div>
                    <span
                      className={`text-lg font-semibold ${
                        scored
                          ? "text-[var(--foreground)]"
                          : "text-[var(--muted-foreground)]"
                      }`}
                    >
                      {scored ? Math.round(dimension.score ?? 0) : "—"}
                    </span>
                  </div>
                  <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-[var(--accent)]">
                    {scored && (
                      <div
                        className="h-full rounded-full bg-[var(--primary)] transition-[width]"
                        style={{ width: `${dimension.score}%` }}
                      />
                    )}
                  </div>
                  <div className="mt-2 flex items-center justify-between gap-2 text-xs text-[var(--muted-foreground)]">
                    <span>
                      {scored
                        ? tr("已评分", "Scored")
                        : tr("证据不足", "Insufficient")}
                    </span>
                    <span>
                      {dimension.evidence_count} {tr("条证据", "evidence")}
                    </span>
                  </div>
                </button>
              );
            })}
          </div>
        </>
      ) : null}

      <SixDimensionEvidenceDrawer
        open={selected !== null}
        dimension={selected}
        onClose={() => setSelected(null)}
      />
    </section>
  );
}
