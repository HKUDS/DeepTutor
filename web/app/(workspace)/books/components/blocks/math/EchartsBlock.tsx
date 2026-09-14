"use client";

import { useEffect, useRef } from "react";
import * as echarts from "echarts";
import { useTranslation } from "react-i18next";
import type { MathBlockConfig } from "./mathBlockAdapter";

const DEFAULT_CATEGORIES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];
const DEFAULT_SERIES = [
  { name: "学习时长(分钟)", type: "bar" as const, data: [45, 60, 30, 80, 55, 90, 70] },
];

/**
 * YuEdu fork: ECharts 数据图 block。
 * DT 无内建 Chart 类库，故直接用 echarts。config.categories + config.series
 * 构造标准 option（bar/line/pie，纯 JSON 无函数）；为空时用默认样例。
 */
export default function EchartsBlock({ config }: { config: MathBlockConfig }) {
  const { t } = useTranslation();
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  const categories = config.categories.length > 0 ? config.categories : DEFAULT_CATEGORIES;
  const seriesList = config.series.length > 0 ? config.series : DEFAULT_SERIES;

  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    chartRef.current = chart;

    chart.setOption({
      tooltip: { trigger: "axis" },
      legend: { top: 0, textStyle: { fontSize: 12 } },
      grid: { left: "8%", right: "8%", bottom: "10%", top: "15%" },
      xAxis:
        seriesList[0]?.type === "pie"
          ? undefined
          : { type: "category", data: categories, axisLabel: { fontSize: 11 } },
      yAxis:
        seriesList[0]?.type === "pie"
          ? undefined
          : { type: "value", axisLabel: { fontSize: 11 } },
      series: seriesList.map((s) => ({
        name: s.name,
        type: s.type,
        data: s.data,
        // pie 用 radius；bar/line 用默认
        ...(s.type === "pie" ? { radius: "60%" } : {}),
      })),
    });

    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.dispose();
      chartRef.current = null;
    };
  }, [categories, seriesList]);

  return (
    <div className="my-4 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4 shadow-sm">
      <h3 className="mb-1 text-base font-bold text-[var(--foreground)]">
        {config.title || t("Data chart (ECharts)")}
      </h3>
      {config.description && (
        <p className="mb-3 text-sm text-[var(--muted-foreground)]">
          {config.description}
        </p>
      )}
      <div ref={ref} className="h-80 w-full" />
      <p className="mt-2 text-xs text-[var(--muted-foreground)]">
        {config.hint || t("Hover for values; chart resizes with the window.")}
      </p>
    </div>
  );
}
