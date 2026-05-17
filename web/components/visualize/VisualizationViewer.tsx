"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Code2,
  Copy,
  Check,
  ExternalLink,
  Maximize2,
  X,
  Sparkles,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { Mermaid } from "@/components/Mermaid";
import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import { prepareIframeHtml } from "@/lib/iframe-html";
import type { VisualizeResult } from "@/lib/visualize-types";

function ChartJsRenderer({ config }: { config: string }) {
  const { t } = useTranslation();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const chartRef = useRef<unknown>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function render() {
      if (!canvasRef.current) return;

      try {
        const ChartModule = await import("chart.js/auto");
        const Chart = ChartModule.default;

        if (chartRef.current) {
          (chartRef.current as InstanceType<typeof Chart>).destroy();
          chartRef.current = null;
        }

        const parsedConfig = new Function(
          `"use strict"; return (${config});`,
        )();

        if (cancelled) return;

        chartRef.current = new Chart(canvasRef.current, parsedConfig);
        setError(null);
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof Error ? err.message : t("Failed to render chart"),
          );
        }
      }
    }

    void render();

    return () => {
      cancelled = true;
      if (chartRef.current) {
        (chartRef.current as { destroy: () => void }).destroy();
        chartRef.current = null;
      }
    };
  }, [config, t]);

  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-4 dark:border-red-900/60 dark:bg-red-950/30">
        <p className="text-sm font-medium text-red-600 dark:text-red-400">
          {t("Chart rendering error")}
        </p>
        <pre className="mt-2 whitespace-pre-wrap text-xs text-red-500">
          {error}
        </pre>
      </div>
    );
  }

  return (
    <div className="relative h-full min-h-0 w-full">
      <canvas ref={canvasRef} />
    </div>
  );
}

function readIframeTheme(): "light" | "dark" {
  if (typeof document === "undefined") return "light";
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

function HtmlRenderer({ html }: { html: string }) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [iframeTheme, setIframeTheme] = useState<"light" | "dark">(
    readIframeTheme,
  );

  useEffect(() => {
    if (typeof document === "undefined") return;

    const htmlEl = document.documentElement;
    const updateTheme = () => setIframeTheme(readIframeTheme());
    const observer = new MutationObserver(updateTheme);
    observer.observe(htmlEl, { attributes: true, attributeFilter: ["class"] });
    window.addEventListener("storage", updateTheme);

    return () => {
      observer.disconnect();
      window.removeEventListener("storage", updateTheme);
    };
  }, []);

  const prepared = useMemo(
    () => prepareIframeHtml(html || "", iframeTheme),
    [html, iframeTheme],
  );

  useEffect(() => {
    const iframe = iframeRef.current;
    if (!iframe) return;
    iframe.srcdoc = prepared;
  }, [prepared]);

  const handleOpenInNewTab = () => {
    try {
      const blob = new Blob([prepared], { type: "text/html" });
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank", "noopener,noreferrer");
      // Best-effort cleanup; the new tab keeps its own reference.
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch {
      /* no-op */
    }
  };

  return (
    <div className="relative w-full" style={{ height: 420 }}>
      <button
        type="button"
        onClick={handleOpenInNewTab}
        className="absolute right-2 top-2 z-10 inline-flex items-center gap-1 rounded-md border border-[var(--border)] bg-[var(--background)]/90 px-2 py-1 text-[10px] font-medium text-[var(--muted-foreground)] backdrop-blur transition-colors hover:text-[var(--foreground)]"
        title="Open in new tab"
      >
        <ExternalLink size={10} strokeWidth={1.8} />
        Open
      </button>
      <iframe
        ref={iframeRef}
        title="HTML visualization"
        sandbox="allow-scripts"
        allowtransparency="true"
        className="h-full w-full rounded-[18px] border-0"
        style={{ background: "transparent" }}
      />
    </div>
  );
}

function normalizeSvgMarkup(svg: string): {
  markup: string;
  error: string | null;
} {
  const trimmed = svg.trim();
  if (!trimmed.startsWith("<svg")) {
    return { markup: "", error: "Invalid SVG: does not start with <svg" };
  }

  if (typeof window === "undefined" || typeof DOMParser === "undefined") {
    return {
      markup: trimmed
        .replace(/<svg\b/i, '<svg preserveAspectRatio="xMidYMid meet"')
        .replace(/\s(width|height)="[^"]*"/gi, ""),
      error: null,
    };
  }

  try {
    const parser = new DOMParser();
    const doc = parser.parseFromString(trimmed, "image/svg+xml");
    if (doc.querySelector("parsererror")) {
      return { markup: "", error: "Invalid SVG markup" };
    }
    const root = doc.documentElement;
    if (!root || root.tagName.toLowerCase() !== "svg") {
      return { markup: "", error: "Invalid SVG document" };
    }

    const parseSize = (value: string | null): number | null => {
      if (!value) return null;
      const match = value.match(/-?\d+(?:\.\d+)?/);
      if (!match) return null;
      const parsed = Number(match[0]);
      return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
    };

    if (!root.getAttribute("viewBox")) {
      const width = parseSize(root.getAttribute("width")) ?? 900;
      const height = parseSize(root.getAttribute("height")) ?? 480;
      root.setAttribute("viewBox", `0 0 ${width} ${height}`);
    }
    root.setAttribute("width", "100%");
    root.setAttribute("height", "100%");
    root.setAttribute("preserveAspectRatio", "xMidYMid meet");
    root.setAttribute(
      "style",
      `${root.getAttribute("style") || ""};max-width:100%;max-height:100%;display:block;`,
    );

    return { markup: new XMLSerializer().serializeToString(root), error: null };
  } catch {
    return { markup: "", error: "Could not normalize SVG for preview" };
  }
}

function SvgRenderer({ svg }: { svg: string }) {
  const { t } = useTranslation();
  const containerRef = useRef<HTMLDivElement>(null);
  const { markup, error } = useMemo(() => normalizeSvgMarkup(svg), [svg]);

  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-4 dark:border-red-900/60 dark:bg-red-950/30">
        <p className="text-sm font-medium text-red-600 dark:text-red-400">
          {t("SVG rendering error")}
        </p>
        <pre className="mt-2 whitespace-pre-wrap text-xs text-red-500">
          {t(error)}
        </pre>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className="flex h-full min-h-0 w-full items-center justify-center overflow-hidden"
      dangerouslySetInnerHTML={{ __html: markup }}
    />
  );
}

function renderVisualization(result: VisualizeResult) {
  if (result.render_type === "svg") {
    return <SvgRenderer svg={result.code.content} />;
  }
  if (result.render_type === "mermaid") {
    return <Mermaid chart={result.code.content} />;
  }
  if (result.render_type === "html") {
    return <HtmlRenderer html={result.code.content} />;
  }
  return <ChartJsRenderer config={result.code.content} />;
}

function labelForResult(result: VisualizeResult): string {
  if (result.render_type === "svg") return "SVG";
  if (result.render_type === "mermaid") {
    return `Mermaid · ${result.analysis.chart_type || "diagram"}`;
  }
  if (result.render_type === "html") {
    return `Interactive · ${result.analysis.chart_type || "visual"}`;
  }
  return `Chart.js · ${result.analysis.chart_type || "chart"}`;
}

/**
 * Strip fenced code blocks from a response string so we only keep the
 * prose explanation.  The `response` field often contains both a solution
 * paragraph and a ```lang … ``` block — we want only the former.
 */
function stripCodeFences(value: string): string {
  // Remove all fenced code blocks (```lang\n…\n```)
  const stripped = value.replace(/```[\w-]*\s*[\s\S]*?```/g, "").trim();
  return stripped;
}

/**
 * Detect and discard text that looks like leaked LLM reasoning / chain-of-
 * thought rather than an actual user-facing explanation.
 */
function looksLikeLeakedReasoning(text: string): boolean {
  const lower = text.slice(0, 300).toLowerCase();
  return (
    lower.includes("we need to") ||
    lower.includes("let me") ||
    lower.includes("i need to") ||
    lower.includes("the user wants") ||
    lower.includes("based on the analysis") ||
    lower.includes("let's design") ||
    lower.includes("let's build") ||
    lower.includes("as per the instructions")
  );
}

function solutionForResult(result: VisualizeResult): string {
  // 1. Prefer explicit solution field from the backend
  const explicit = (result.solution || "").trim();
  if (explicit && !looksLikeLeakedReasoning(explicit)) return explicit;

  // 2. Try the response field, but strip code fences and leaked reasoning
  const responseText = stripCodeFences(result.response || "");
  if (responseText && !looksLikeLeakedReasoning(responseText))
    return responseText;

  // 3. Fall back to analysis metadata
  const labels =
    result.analysis.visual_elements?.filter(Boolean).slice(0, 6) ?? [];
  const parts = [
    result.analysis.description,
    result.analysis.data_description,
    labels.length ? `Diagram labels: ${labels.join(", ")}.` : "",
  ].filter(Boolean);
  return parts.join("\n\n");
}

export default function VisualizationViewer({
  result,
}: {
  result: VisualizeResult;
}) {
  const { t } = useTranslation();
  const [showCode, setShowCode] = useState(false);
  const [copied, setCopied] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const solution = useMemo(() => solutionForResult(result), [result]);
  const resultLabel = labelForResult(result);

  // HTML iframe already provides its own "Open in new tab" affordance; the
  // sandboxed iframe also doesn't behave well inside a re-rendered modal.
  const supportsFullscreen = result.render_type !== "html";

  useEffect(() => {
    if (!fullscreen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setFullscreen(false);
    };
    document.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [fullscreen]);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(result.code.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard API may be unavailable */
    }
  };

  return (
    <div className="dt-viz-shell overflow-hidden rounded-[22px] border border-[var(--border)] bg-[var(--card)] shadow-sm">
      <div className="dt-viz-stage relative bg-[var(--background)]/55 px-4 py-4 sm:px-6">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div className="inline-flex min-w-0 items-center gap-2">
            <Sparkles className="h-3.5 w-3.5 shrink-0 text-[var(--primary)]" />
            <span className="truncate text-[12px] font-semibold text-[var(--muted-foreground)]">
              {result.analysis.description || t("Visualization")}
            </span>
          </div>
          {supportsFullscreen && (
            <button
              type="button"
              onClick={() => setFullscreen(true)}
              title={t("Fullscreen")}
              className="inline-flex shrink-0 items-center gap-1 rounded-md border border-[var(--border)]/70 bg-[var(--card)]/80 px-2 py-1 text-[10px] font-medium text-[var(--muted-foreground)] backdrop-blur transition-colors hover:text-[var(--foreground)]"
            >
              <Maximize2 size={10} strokeWidth={1.8} />
              {t("Open")}
            </button>
          )}
        </div>
        <div
          className={`dt-viz-canvas relative mx-auto flex w-full items-center justify-center overflow-hidden rounded-[18px] border border-[var(--border)]/70 bg-[var(--card)]/80 ${
            result.render_type === "html"
              ? "p-0 min-h-[420px]"
              : "p-3 sm:p-5 min-h-[300px]"
          }`}
        >
          {renderVisualization(result)}
        </div>
      </div>

      {solution && (
        <div className="border-t border-[var(--border)]/80 px-4 py-4 sm:px-6">
          <div className="mb-3 text-[22px] font-semibold tracking-normal text-[var(--foreground)]">
            {t("Step-by-Step Derivation")}
          </div>
          <MarkdownRenderer
            content={solution}
            variant="prose"
            className="text-[14px] leading-[1.7] text-[var(--foreground)]"
          />
        </div>
      )}

      {/* Toolbar */}
      <div className="flex items-center gap-2 border-t border-[var(--border)]/80 px-4 py-3 sm:px-6">
        <button
          type="button"
          onClick={() => setShowCode((prev) => !prev)}
          className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--background)] px-2.5 py-1.5 text-[11px] font-medium text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
        >
          <Code2 size={12} strokeWidth={1.8} />
          {showCode ? t("Hide code") : t("Show code")}
        </button>

        <button
          type="button"
          onClick={handleCopy}
          className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--background)] px-2.5 py-1.5 text-[11px] font-medium text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
        >
          {copied ? (
            <Check size={12} strokeWidth={1.8} />
          ) : (
            <Copy size={12} strokeWidth={1.8} />
          )}
          {copied ? t("Copied") : t("Copy code")}
        </button>

        <span className="ml-auto text-[10px] uppercase tracking-wider text-[var(--muted-foreground)]/50">
          {resultLabel}
        </span>
      </div>

      {/* Code panel */}
      {showCode && (
        <div className="mx-4 mb-4 overflow-hidden rounded-xl border border-[var(--border)] bg-[#1f2937] sm:mx-6">
          <div className="border-b border-white/10 px-3 py-2 text-[11px] font-medium uppercase tracking-wider text-[#9ca3af]">
            {result.code.language}
          </div>
          <pre className="max-h-80 overflow-auto p-4 text-[13px] leading-relaxed text-[#d1d5db]">
            <code>{result.code.content}</code>
          </pre>
        </div>
      )}

      {/* Review notes */}
      {result.review.changed && result.review.review_notes && (
        <p className="px-4 pb-4 text-[11px] text-[var(--muted-foreground)] sm:px-6">
          {t("Review")}: {result.review.review_notes}
        </p>
      )}

      {/* Fullscreen overlay */}
      {fullscreen && supportsFullscreen && (
        <div
          className="fixed inset-0 z-[120] flex flex-col bg-black/85 p-4 backdrop-blur-sm"
          onClick={() => setFullscreen(false)}
        >
          <div className="mb-2 flex shrink-0 items-center justify-between text-white">
            <div className="text-xs uppercase tracking-wider opacity-80">
              {resultLabel}
            </div>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                setFullscreen(false);
              }}
              title={t("Close")}
              className="inline-flex items-center gap-1 rounded-md bg-white/10 px-2.5 py-1.5 text-[11px] font-medium text-white transition-colors hover:bg-white/20"
            >
              <X size={12} strokeWidth={1.8} />
              {t("Close")}
            </button>
          </div>
          <div
            className="flex flex-1 items-center justify-center overflow-auto rounded-xl bg-white p-6 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="w-full max-w-[1600px]">
              {renderVisualization(result)}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
