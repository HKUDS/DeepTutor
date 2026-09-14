"use client";

import { useEffect, useRef } from "react";
import type { Block } from "@/lib/book-types";

function toFiniteNumber(value: unknown): number | null {
  if (
    typeof value !== "number" &&
    (typeof value !== "string" || value.trim() === "")
  ) {
    return null;
  }
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

/**
 * YuEdu fork: 气候 block 渲染组件（地理专用）。
 * 用 ECharts（CDN）渲染气候数据图（温度折线 + 降水柱状组合图）。
 * Payload 形如:
 * {
 *   title: "北京气候数据",
 *   description: "温带季风气候，夏热多雨，冬寒干燥",
 *   months: ["1月","2月",...,"12月"],
 *   temperature: [-4, -1, 6, 14, 20, 25, 27, 26, 21, 14, 5, -2],
 *   precipitation: [3, 6, 9, 26, 29, 71, 176, 182, 49, 19, 8, 3]
 * }
 */
export default function ClimateBlock({ block }: { block: Block }) {
  const params = (block.payload as Record<string, unknown> | undefined) ?? {};
  const title = String(params.title ?? "");
  const description = String(params.description ?? "");
  const rawMonths = Array.isArray(params.months) ? params.months : [];
  const rawTemperature = Array.isArray(params.temperature)
    ? params.temperature
    : [];
  const rawPrecipitation = Array.isArray(params.precipitation)
    ? params.precipitation
    : [];
  const dataLength = Math.min(
    rawMonths.length,
    rawTemperature.length,
    rawPrecipitation.length,
  );
  const dataPoints = Array.from({ length: dataLength }, (_, index) => {
    const month = rawMonths[index];
    const temperatureValue = rawTemperature[index];
    const precipitationValue = rawPrecipitation[index];
    if (typeof month !== "string" && typeof month !== "number") {
      return null;
    }
    const monthLabel = String(month).trim();
    const temperature = toFiniteNumber(temperatureValue);
    const precipitation = toFiniteNumber(precipitationValue);
    if (!monthLabel || temperature === null || precipitation === null) {
      return null;
    }
    return { month: monthLabel, temperature, precipitation };
  }).filter(
    (
      point,
    ): point is {
      month: string;
      temperature: number;
      precipitation: number;
    } => point !== null,
  );
  const months = dataPoints.map((point) => point.month);
  const temperature = dataPoints.map((point) => point.temperature);
  const precipitation = dataPoints.map((point) => point.precipitation);
  const chartRef = useRef<HTMLDivElement>(null);
  const chartInstanceRef = useRef<unknown>(null);

  useEffect(() => {
    if (!chartRef.current || months.length === 0) return;

    const loadECharts = async () => {
      const w = window as unknown as Record<string, unknown>;
      if (!w.echarts) {
        await new Promise<void>((resolve, reject) => {
          const script = document.createElement("script");
          script.src = "https://cdn.bootcdn.net/ajax/libs/echarts/5.5.0/echarts.min.js";
          script.onload = () => resolve();
          script.onerror = () => reject(new Error("ECharts failed to load"));
          document.head.appendChild(script);
        });
      }

      const echarts = w.echarts as {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        init: (el: HTMLElement) => any;
      };

      if (chartInstanceRef.current) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (chartInstanceRef.current as any)?.dispose?.();
      }

      const chart = echarts.init(chartRef.current!);
      chartInstanceRef.current = chart;

      const option = {
        tooltip: {
          trigger: "axis",
          axisPointer: { type: "cross" },
        },
        legend: {
          data: ["气温(°C)", "降水(mm)"],
          top: 0,
          textStyle: { fontSize: 12 },
        },
        grid: {
          left: "8%",
          right: "8%",
          bottom: "10%",
          top: "15%",
        },
        xAxis: {
          type: "category",
          data: months,
          axisLabel: { fontSize: 11 },
        },
        yAxis: [
          {
            type: "value",
            name: "气温(°C)",
            position: "left",
            axisLabel: { formatter: "{value}°C", fontSize: 11 },
          },
          {
            type: "value",
            name: "降水(mm)",
            position: "right",
            axisLabel: { formatter: "{value}mm", fontSize: 11 },
            splitLine: { show: false },
          },
        ],
        series: [
          {
            name: "气温(°C)",
            type: "line",
            data: temperature,
            smooth: true,
            itemStyle: { color: "#e74c3c" },
            lineStyle: { width: 2 },
            areaStyle: { opacity: 0.1 },
          },
          {
            name: "降水(mm)",
            type: "bar",
            yAxisIndex: 1,
            data: precipitation,
            itemStyle: { color: "#3498db", opacity: 0.7 },
          },
        ],
      };

      chart.setOption(option);

      const handleResize = () => {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (chartInstanceRef.current as any)?.resize?.();
      };
      window.addEventListener("resize", handleResize);
    };

    loadECharts().catch(() => {
      if (chartRef.current) {
        chartRef.current.innerHTML =
          '<div class="flex h-full items-center justify-center text-sm text-[var(--muted-foreground)]">图表加载失败，请检查网络连接</div>';
      }
    });

    return () => {
      if (chartInstanceRef.current) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (chartInstanceRef.current as any)?.dispose?.();
        chartInstanceRef.current = null;
      }
    };
  }, [months, temperature, precipitation]);

  // 无图表数据时，显示文字描述表格
  const hasChartData = months.length > 0;

  return (
    <div className="my-4 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4 shadow-sm">
      {title && (
        <h3 className="mb-1 text-base font-bold text-[var(--foreground)]">{title}</h3>
      )}
      {description && (
        <p className="mb-3 text-sm text-[var(--muted-foreground)]">{description}</p>
      )}
      {hasChartData ? (
        <div ref={chartRef} className="h-72 w-full" />
      ) : (
        <div className="flex h-32 items-center justify-center text-sm text-[var(--muted-foreground)]">
          暂无气候数据
        </div>
      )}
    </div>
  );
}
