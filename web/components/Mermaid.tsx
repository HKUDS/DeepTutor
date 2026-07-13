"use client";

import React, { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { subscribeToThemeChanges } from "@/lib/theme";

interface MermaidProps {
  chart: string;
  className?: string;
}

let mermaidLoader: Promise<(typeof import("mermaid"))["default"]> | null = null;

// Read a CSS custom property from :root. We re-derive these on every render
// so the diagram colors track the active theme rather than freezing to the
// first-render palette.
function cssVar(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim();
  return value || fallback;
}

function themeVariablesFromCss() {
  // Mermaid expects opaque colors; we pull from the theme's --foreground /
  // --card / --border / --primary tokens so diagrams blend with the chat
  // surface in every theme (light, dark, snow, glass).
  return {
    primaryColor: cssVar("--card", "#ffffff"),
    primaryTextColor: cssVar("--foreground", "#1f1d1b"),
    primaryBorderColor: cssVar("--border", "#dbd4c8"),
    lineColor: cssVar("--muted-foreground", "#6b655f"),
    secondaryColor: cssVar("--muted", "#ece7dd"),
    tertiaryColor: cssVar("--background", "#faf9f6"),
    textColor: cssVar("--foreground", "#1f1d1b"),
    mainBkg: cssVar("--card", "#ffffff"),
  };
}

async function loadMermaid() {
  if (!mermaidLoader) {
    mermaidLoader = import("mermaid").then((module) => module.default);
  }
  return mermaidLoader;
}

// Re-applied on every render so theme changes pick up. mermaid.initialize()
// is idempotent and cheap; the heavy work is the dynamic import which the
// loader above only runs once.
function applyMermaidTheme(mermaid: (typeof import("mermaid"))["default"]) {
  mermaid.initialize({
    startOnLoad: false,
    theme: "base",
    securityLevel: "strict",
    fontFamily: "ui-sans-serif, system-ui, sans-serif",
    flowchart: {
      useMaxWidth: true,
      htmlLabels: false,
      curve: "basis",
    },
    themeVariables: themeVariablesFromCss(),
  });
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
  const [themeToken, setThemeToken] = useState(0);
  const lastChartRef = useRef(chart);

  useEffect(() => {
    lastChartRef.current = chart;
    setStable(false);

    const timer = window.setTimeout(() => {
      if (lastChartRef.current === chart) setStable(true);
    }, DEBOUNCE_MS);

    return () => window.clearTimeout(timer);
  }, [chart]);

  // Bump a token whenever the app's theme changes so the render effect below
  // re-runs with fresh theme variables. Without this the diagram would keep
  // its initial palette across light/dark/glass/snow switches.
  useEffect(() => {
    return subscribeToThemeChanges(() => setThemeToken((t) => t + 1));
  }, []);

  useEffect(() => {
    if (!stable) return;

    let cancelled = false;
    const renderChart = async () => {
      if (!chart.trim() || !containerRef.current) return;

      try {
        const mermaid = await loadMermaid();
        applyMermaidTheme(mermaid);
        cleanupMermaidOrphans(id);
        const { svg: renderedSvg } = await mermaid.render(id, chart.trim());
        if (!cancelled) {
          setSvg(renderedSvg);
          setError(null);
        }
      } catch (err) {
        cleanupMermaidOrphans(id);
        if (!cancelled) {
          setError(
            err instanceof Error ? err.message : t("Failed to render diagram"),
          );
        }
      }
    };

    void renderChart();
    return () => {
      cancelled = true;
    };
  }, [stable, chart, id, t, themeToken]);

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
      <div
        className={`my-4 rounded-xl border border-[var(--border)] bg-[var(--muted)]/50 px-4 py-3 text-sm text-[var(--muted-foreground)] ${className}`}
      >
        {t("Rendering diagram...")}
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
