"use client";

import React, { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

interface MermaidProps {
  chart: string;
  className?: string;
}

type MermaidApi = {
  initialize: (config: Record<string, unknown>) => void;
  render: (id: string, chart: string) => Promise<{ svg: string }>;
};

let mermaidLoader: Promise<MermaidApi> | null = null;

async function loadMermaid() {
  if (!mermaidLoader) {
    // Work around broken mermaid package entrypoints in some offline installs:
    // load the bundled browser build directly and read its global export.
    mermaidLoader = import("mermaid/dist/mermaid.min.js").then((module) => {
      const candidate = (module as unknown as { default?: MermaidApi }).default
        ?? (globalThis as { mermaid?: MermaidApi }).mermaid;
      if (!candidate) {
        throw new Error("Mermaid runtime not available");
      }
      const mermaid = candidate;
      mermaid.initialize({
        startOnLoad: false,
        theme: "neutral",
        securityLevel: "strict",
        fontFamily: "ui-sans-serif, system-ui, sans-serif",
        flowchart: {
          useMaxWidth: true,
          htmlLabels: false,
          curve: "basis",
        },
        themeVariables: {
          primaryColor: "#6366f1",
          primaryTextColor: "#1e293b",
          primaryBorderColor: "#c7d2fe",
          lineColor: "#94a3b8",
          secondaryColor: "#f1f5f9",
          tertiaryColor: "#f8fafc",
        },
      });
      return mermaid;
    });
  }

  return mermaidLoader;
}

function cleanupMermaidOrphans(id: string) {
  try {
    document.getElementById(id)?.remove();
    document.getElementById(`d${id}`)?.remove();
  } catch {
    /* ignore */
  }
}

let mermaidIdCounter = 0;

const DEBOUNCE_MS = 600;

export const Mermaid: React.FC<MermaidProps> = ({ chart, className = "" }) => {
  const { t } = useTranslation();
  const containerRef = useRef<HTMLDivElement>(null);
  const [svg, setSvg] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [stable, setStable] = useState(false);
  const [id] = useState(() => `mermaid-${++mermaidIdCounter}`);
  const lastChartRef = useRef(chart);

  useEffect(() => {
    lastChartRef.current = chart;
    setStable(false);

    const timer = window.setTimeout(() => {
      if (lastChartRef.current === chart) setStable(true);
    }, DEBOUNCE_MS);

    return () => window.clearTimeout(timer);
  }, [chart]);

  useEffect(() => {
    if (!stable) return;

    let cancelled = false;
    const renderChart = async () => {
      if (!chart.trim() || !containerRef.current) return;

      try {
        const mermaid = await loadMermaid();
        cleanupMermaidOrphans(id);
        const { svg: renderedSvg } = await mermaid.render(id, chart.trim());
        if (!cancelled) {
          setSvg(renderedSvg);
          setError(null);
        }
      } catch (err) {
        cleanupMermaidOrphans(id);
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to render diagram");
        }
      }
    };

    void renderChart();
    return () => {
      cancelled = true;
    };
  }, [stable, chart, id]);

  if (error) {
    return (
      <div
        className={`my-4 p-4 bg-red-50 border border-red-200 rounded-lg ${className}`}
      >
        <p className="text-red-600 text-sm font-medium mb-2">
          {t("Diagram rendering error")}
        </p>
        <pre className="text-xs text-red-500 whitespace-pre-wrap">{error}</pre>
        <details className="mt-2">
          <summary className="text-xs text-[var(--muted-foreground)] cursor-pointer">
            {t("Show source")}
          </summary>
          <pre className="mt-2 p-2 bg-[var(--muted)] rounded text-xs overflow-x-auto text-[var(--foreground)]">
            {chart}
          </pre>
        </details>
      </div>
    );
  }

  if (!stable && !svg) {
    return (
      <div className={`my-4 rounded-xl border border-[var(--border)] bg-[var(--muted)]/50 px-4 py-3 text-sm text-[var(--muted-foreground)] ${className}`}>
        Rendering diagram...
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className={`my-6 flex justify-center overflow-x-auto ${className}`}
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
};

export default Mermaid;
