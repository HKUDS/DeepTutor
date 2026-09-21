"use client";

import { useEffect, useId, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslation } from "react-i18next";
import { BarChart3, ChartNoAxesCombined, RefreshCw } from "lucide-react";
import { practiceRoute } from "@/lib/learning-routes";
import {
  getPracticeAnalytics,
  type PracticeAnalytics,
  type PracticeMetric,
} from "@/lib/practice-api";

const METRICS: { key: PracticeMetric; label: string; color: string }[] = [
  { key: "questions", label: "New questions", color: "#4f70d9" },
  { key: "mistakes", label: "New mistakes", color: "#d08732" },
  { key: "reviews", label: "Review submissions", color: "#329080" },
];
const SOURCES: Record<string, string> = {
  mastery_path: "Mastery Path",
  book: "Book",
  deep_question: "Deep Question",
  immersive_reading: "Immersive Reading",
  partner_chat: "Partner Chat",
  import: "Imported",
};
const number = (value: number) => value.toLocaleString();
const dateLabel = (date: string) =>
  new Date(`${date}T12:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric" });

export function PracticeInsights({ courseId, revision, workspaceId }: { courseId: string; revision: number; workspaceId?: string }) {
  const { t } = useTranslation();
  const search = useSearchParams();
  const router = useRouter();
  const days = [7, 30, 90].includes(Number(search.get("stats_days")))
    ? Number(search.get("stats_days"))
    : 30;
  const metric = METRICS.find(item => item.key === search.get("stats_metric")) || METRICS[0];
  const style = search.get("stats_chart") === "bars" ? "bars" : "line";
  const [result, setResult] = useState<{ scope: string; data: PracticeAnalytics } | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  const scope = `${workspaceId}:${courseId}:${days}`;
  const data = result?.scope === scope ? result.data : null;
  function setView(key: string, value: string) {
    const query = new URLSearchParams(search.toString());
    query.set(key, value);
    router.replace(practiceRoute(query), { scroll: false });
  }
  useEffect(() => {
    let active = true;
    let sequence = 0;
    async function load() {
      const request = ++sequence;
      setLoading(true);
      try {
        const next = await getPracticeAnalytics(courseId, days, workspaceId);
        if (active && request === sequence) {
          setResult({ scope, data: next });
          setError("");
        }
      } catch (err) {
        if (active && request === sequence)
          setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (active && request === sequence) setLoading(false);
      }
    }
    void load();
    const refresh = () => {
      if (!document.hidden) void load();
    };
    window.addEventListener("focus", refresh);
    const timer = window.setInterval(refresh, 60000);
    return () => {
      active = false;
      window.clearInterval(timer);
      window.removeEventListener("focus", refresh);
    };
  }, [courseId, days, scope, revision, retry, workspaceId]);
  const total = data?.totals[metric.key] || 0;
  const sources = [...(data?.sources || [])]
    .filter(row => row[metric.key] > 0)
    .sort((a, b) => b[metric.key] - a[metric.key]);
  return (
    <section
      aria-label={t("Practice activity")}
      className="mb-5 overflow-hidden rounded-2xl border border-border bg-card"
    >
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 pt-5">
        <div>
          <h2 className="text-sm font-semibold">{t("Practice activity")}</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            {data
              ? `${dateLabel(data.start_date)} – ${dateLabel(data.end_date)}`
              : t("Daily activity and sources")}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            aria-label={t("Statistics period")}
            value={days}
            onChange={e => setView("stats_days", e.target.value)}
            className="h-9 rounded-lg border border-border bg-background px-2 text-xs"
          >
            {[7, 30, 90].map(value => (
              <option key={value} value={value}>
                {t("Last {{count}} days", { count: value })}
              </option>
            ))}
          </select>
          <div
            className="flex rounded-lg border border-border p-0.5"
            role="group"
            aria-label={t("Chart style")}
          >
            {(["line", "bars"] as const).map(value => (
              <button
                key={value}
                type="button"
                aria-pressed={style === value}
                title={t(value === "line" ? "Line chart" : "Bar chart")}
                aria-label={t(value === "line" ? "Line chart" : "Bar chart")}
                onClick={() => setView("stats_chart", value)}
                className={`rounded-md p-2 ${style === value ? "bg-muted text-foreground" : "text-muted-foreground hover:text-foreground"}`}
              >
                {value === "line" ? <ChartNoAxesCombined size={15} /> : <BarChart3 size={15} />}
              </button>
            ))}
          </div>
        </div>
      </div>
      <div className="mt-4 grid grid-cols-3 border-b border-border px-3">
        {METRICS.map(item => (
          <button
            key={item.key}
            type="button"
            aria-pressed={metric.key === item.key}
            onClick={() => setView("stats_metric", item.key)}
            className={`relative min-w-0 px-2 pb-4 pt-2 text-left sm:px-3 ${metric.key === item.key ? "text-foreground" : "text-muted-foreground hover:text-foreground"}`}
          >
            <span className="flex items-center gap-1.5 text-[11px] sm:text-xs">
              <span
                className="h-1.5 w-1.5 shrink-0 rounded-full"
                style={{ background: item.color }}
              />
              {t(item.label)}
            </span>
            <span className="mt-2 block text-2xl font-semibold tabular-nums tracking-tight">
              {data ? number(data.totals[item.key]) : "—"}
            </span>
            {metric.key === item.key && (
              <span
                className="absolute inset-x-2 bottom-0 h-0.5 rounded-t"
                style={{ background: item.color }}
              />
            )}
          </button>
        ))}
      </div>
      {error && (
        <div
          role="alert"
          className="flex items-center justify-between gap-3 px-5 pt-3 text-xs text-muted-foreground"
        >
          <span>
            {data
              ? t("Could not refresh statistics. Showing the last loaded data.")
              : t("Could not load statistics.")}{" "}
            {error}
          </span>
          <button
            type="button"
            onClick={() => setRetry(value => value + 1)}
            className="inline-flex shrink-0 items-center gap-1 underline"
          >
            <RefreshCw size={12} />
            {t("Retry")}
          </button>
        </div>
      )}
      {data ? (
        <div className="grid lg:grid-cols-[minmax(0,1fr)_240px]">
          <div className="min-w-0 px-4 pb-3 pt-4 sm:px-5">
            <DailyChart
              rows={data.daily}
              metric={metric.key}
              color={metric.color}
              label={t(metric.label)}
              style={style}
            />
          </div>
          <div className="border-t border-border px-5 py-4 lg:border-l lg:border-t-0">
            <div className="mb-4 flex items-center justify-between gap-2 text-xs">
              <h3 className="font-medium">{t("Sources in this period")}</h3>
              <span className="text-muted-foreground">{t(metric.label)}</span>
            </div>
            {sources.length ? (
              <ul className="space-y-3.5">
                {sources.map(source => (
                  <li key={source.source}>
                    <div className="mb-1.5 flex items-center justify-between gap-3 text-xs">
                      <span>{t(SOURCES[source.source] || "Other")}</span>
                      <span className="whitespace-nowrap tabular-nums">
                        {number(source[metric.key])}
                        <span className="ml-2 text-muted-foreground">
                          {Math.round((source[metric.key] / total) * 100)}%
                        </span>
                      </span>
                    </div>
                    <div className="h-1 overflow-hidden rounded-full bg-muted">
                      <div
                        className="h-full rounded-full"
                        style={{
                          width: `${(source[metric.key] / total) * 100}%`,
                          background: metric.color,
                          opacity: 0.8,
                        }}
                      />
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="py-6 text-center text-xs text-muted-foreground">
                {t("No activity in this period")}
              </p>
            )}
          </div>
        </div>
      ) : (
        <div
          role="status"
          className="flex h-52 items-center justify-center text-sm text-muted-foreground"
        >
          {loading ? t("Loading…") : t("Statistics unavailable")}
        </div>
      )}
      <div className="border-t border-border px-5 py-3 text-[11px] leading-relaxed text-muted-foreground">
        {t(
          "New mistakes count each question once, on its first wrong day. Reviews count saved submissions. Deleted questions are excluded."
        )}
        {data && (
          <details className="mt-2">
            <summary className="w-fit cursor-pointer font-medium hover:text-foreground">
              {t("View daily data")}
            </summary>
            <div className="mt-2 max-h-60 overflow-auto">
              <table className="w-full text-right tabular-nums">
                <caption className="sr-only">{t("Daily practice data")}</caption>
                <thead className="sticky top-0 bg-card">
                  <tr>
                    <th scope="col" className="py-2 text-left">
                      {t("Date")}
                    </th>
                    {METRICS.map(item => (
                      <th key={item.key} scope="col">
                        {t(item.label)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.daily.map(row => (
                    <tr key={row.date} className="border-t border-border/60">
                      <th scope="row" className="py-2 text-left font-normal">
                        {row.date}
                      </th>
                      {METRICS.map(item => (
                        <td key={item.key}>{number(row[item.key])}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        )}
      </div>
    </section>
  );
}

function DailyChart({
  rows,
  metric,
  color,
  label,
  style,
}: {
  rows: PracticeAnalytics["daily"];
  metric: PracticeMetric;
  color: string;
  label: string;
  style: "line" | "bars";
}) {
  const { t } = useTranslation();
  const id = useId();
  const container = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(600);
  const [selected, setSelected] = useState<string | null>(null);
  useEffect(() => {
    const node = container.current;
    if (!node) return;
    const observer = new ResizeObserver(entries =>
      setWidth(Math.max(240, entries[0].contentRect.width))
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  const index = Math.max(
    0,
    selected ? rows.findIndex(row => row.date === selected) : rows.length - 1
  );
  const maximum = Math.max(1, ...rows.map(row => row[metric]));
  const step = Math.max(1, 10 ** Math.floor(Math.log10(maximum)));
  const top = Math.ceil(maximum / step) * step;
  const left = 32,
    right = width - 12,
    bottom = 156,
    height = 136;
  const unit = (right - left) / rows.length;
  const x = (i: number) => left + (i + 0.5) * unit;
  const y = (value: number) => bottom - (value / top) * height;
  const line = rows.map((row, i) => `${i ? "L" : "M"}${x(i)},${y(row[metric])}`).join(" ");
  const ticks = [...new Set([0, Math.floor(top / 2), top])];
  const dates = [...new Set([0, Math.floor((rows.length - 1) / 2), rows.length - 1])];
  const active = rows[index];
  return (
    <div ref={container}>
      <div className="mb-1 flex min-h-6 items-center justify-between gap-2 text-xs">
        <span className="text-muted-foreground">{dateLabel(active.date)}</span>
        <span className="font-medium tabular-nums">
          {label}
          <span className="ml-2">{number(active[metric])}</span>
        </span>
      </div>
      <div
        tabIndex={0}
        role="group"
        aria-label={t("Daily chart. Use left and right arrows to inspect dates.")}
        className="rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
        onKeyDown={event => {
          if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
            event.preventDefault();
            setSelected(
              rows[
                Math.max(0, Math.min(rows.length - 1, index + (event.key === "ArrowLeft" ? -1 : 1)))
              ].date
            );
          }
        }}
      >
        <svg
          role="img"
          aria-labelledby={`${id}-title`}
          viewBox={`0 0 ${width} 184`}
          className="block h-[184px] w-full overflow-visible"
        >
          <title id={`${id}-title`}>
            {t("{{metric}} by day. Exact values are available in the daily data table.", {
              metric: label,
            })}
          </title>
          {ticks.map(value => (
            <g key={value}>
              <line
                x1={left}
                x2={right}
                y1={y(value)}
                y2={y(value)}
                stroke="currentColor"
                className="text-border"
                strokeDasharray={value ? "3 4" : undefined}
              />
              <text
                x={left - 9}
                y={y(value) + 4}
                textAnchor="end"
                fontSize="10"
                fill="currentColor"
                className="text-muted-foreground"
              >
                {value}
              </text>
            </g>
          ))}
          {style === "line" ? (
            <>
              <path
                d={`${line} L${x(rows.length - 1)},${bottom} L${x(0)},${bottom} Z`}
                fill={color}
                opacity="0.055"
              />
              <path
                d={line}
                fill="none"
                stroke={color}
                strokeWidth="2"
                strokeLinejoin="round"
                strokeLinecap="round"
              />
              {rows.length <= 7 &&
                rows.map((row, i) => (
                  <circle key={row.date} cx={x(i)} cy={y(row[metric])} r="2.5" fill={color} />
                ))}
            </>
          ) : (
            rows.map((row, i) => (
              <rect
                key={row.date}
                x={x(i) - unit * 0.32}
                y={y(row[metric])}
                width={Math.max(1, unit * 0.64)}
                height={bottom - y(row[metric])}
                rx={Math.min(2, unit / 5)}
                fill={color}
                opacity={index === i ? 1 : 0.68}
              />
            ))
          )}
          <line
            x1={x(index)}
            x2={x(index)}
            y1="16"
            y2={bottom}
            stroke={color}
            opacity="0.25"
            strokeDasharray="3 3"
          />
          <circle
            cx={x(index)}
            cy={y(active[metric])}
            r="3.5"
            fill={color}
            stroke="var(--card)"
            strokeWidth="2"
          />
          {dates.map(i => (
            <text
              key={i}
              x={i === 0 ? left : i === rows.length - 1 ? right : x(i)}
              y="178"
              textAnchor={i === 0 ? "start" : i === rows.length - 1 ? "end" : "middle"}
              fontSize="10"
              fill="currentColor"
              className="text-muted-foreground"
            >
              {dateLabel(rows[i].date)}
            </text>
          ))}
          {rows.map((row, i) => (
            <rect
              key={row.date}
              x={left + i * unit}
              y="0"
              width={unit}
              height={bottom}
              fill="transparent"
              onPointerMove={() => setSelected(row.date)}
              onClick={() => setSelected(row.date)}
            >
              <title>{`${row.date}: ${row[metric]}`}</title>
            </rect>
          ))}
        </svg>
      </div>
    </div>
  );
}
