"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import { createPortal } from "react-dom";
import { Code2, Copy, Check, ExternalLink, Maximize2, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Mermaid } from "@/components/Mermaid";
import { prepareIframeHtml } from "@/lib/iframe-html";
import { isManimResult, type VisualizeResult } from "@/lib/visualize-types";
import "./svg-theme.css";

const MathAnimatorViewer = dynamic(
  () => import("@/components/math-animator/MathAnimatorViewer"),
  { ssr: false },
);

function stripCodeFence(source: string): string {
  const trimmed = source.trim();
  const fenced = trimmed.match(
    /^```(?:json|javascript|js)?\s*([\s\S]*?)\s*```$/i,
  );
  return fenced ? fenced[1].trim() : trimmed;
}

function parseChartConfig(source: string): unknown {
  const raw = stripCodeFence(source);
  try {
    return JSON.parse(raw);
  } catch {
    const jsonish = raw
      .replace(/([{,]\s*)([A-Za-z_$][\w$]*)\s*:/g, '$1"$2":')
      .replace(/'([^'\\]*(?:\\.[^'\\]*)*)'/g, (_match, value: string) =>
        JSON.stringify(value.replace(/\\'/g, "'")),
      )
      .replace(/,\s*([}\]])/g, "$1");
    return JSON.parse(jsonish);
  }
}

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

        const parsedConfig = parseChartConfig(config) as ConstructorParameters<
          typeof Chart
        >[1];

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
    <div className="dt-chart-wrap relative w-full">
      <canvas ref={canvasRef} />
    </div>
  );
}

function HtmlRenderer({ html }: { html: string }) {
  const { t } = useTranslation();
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [height, setHeight] = useState(560);

  const prepared = useMemo(() => prepareIframeHtml(html || ""), [html]);

  useEffect(() => {
    const iframe = iframeRef.current;
    if (!iframe) return;
    iframe.srcdoc = prepared;
  }, [prepared]);

  // Listen for the iframe bridge: a sendPrompt() call (mirror into the composer
  // via the shared window event) or a height report (grow to fit, no clipping).
  useEffect(() => {
    const onMessage = (e: MessageEvent) => {
      const iframe = iframeRef.current;
      if (!iframe || e.source !== iframe.contentWindow) return;
      const data = e.data as { type?: string; text?: string; height?: number };
      if (!data || typeof data !== "object") return;
      if (data.type === "dt:visualize-prompt" && data.text) {
        window.dispatchEvent(
          new CustomEvent("dt:visualize-prompt", { detail: data.text }),
        );
      } else if (
        data.type === "dt:visualize-height" &&
        typeof data.height === "number"
      ) {
        setHeight(Math.min(2400, Math.max(240, Math.ceil(data.height) + 8)));
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  const handleOpenInNewTab = () => {
    try {
      const contentUrl = URL.createObjectURL(
        new Blob([prepared], { type: "text/html" }),
      );
      const wrapper = `<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Visualization</title><style>html,body,iframe{height:100%;width:100%;margin:0;border:0;}</style></head><body><iframe sandbox="allow-scripts" src="${contentUrl}"></iframe></body></html>`;
      const url = URL.createObjectURL(
        new Blob([wrapper], { type: "text/html" }),
      );
      window.open(url, "_blank", "noopener,noreferrer");
      setTimeout(() => {
        URL.revokeObjectURL(url);
        URL.revokeObjectURL(contentUrl);
      }, 60_000);
    } catch {
      /* no-op */
    }
  };

  return (
    <div className="relative w-full">
      <button
        type="button"
        onClick={handleOpenInNewTab}
        className="absolute right-2 top-2 z-10 inline-flex items-center gap-1 rounded-md border border-[var(--border)] bg-[var(--background)]/90 px-2 py-1 text-[10px] font-medium text-[var(--muted-foreground)] backdrop-blur transition-colors hover:text-[var(--foreground)]"
        title={t("Open in new tab")}
      >
        <ExternalLink size={10} strokeWidth={1.8} />
        {t("Open")}
      </button>
      <iframe
        ref={iframeRef}
        title={t("HTML visualization")}
        sandbox="allow-scripts"
        className="w-full rounded-lg border border-[var(--border)] bg-[var(--card)]"
        style={{ minHeight: 320, height }}
      />
    </div>
  );
}

// Per-page sequence used to scope SVG ids (see the scoping block below).
let svgScopeSeq = 0;

// Sanitize an SVG string for safe inline rendering: parse as XML, strip
// script/foreign-object/event-handler vectors, then reserialize. SVGs come from
// our own LLM and already pass a backend well-formedness check, but we still
// defend against prompt-injected <script>/on* handlers. Kept dependency-free
// (same sanitize→string contract as DOMPurify, so it can be swapped later).
function sanitizeSvg(raw: string): string {
  const trimmed = raw.trim();
  if (typeof DOMParser === "undefined") return "";
  const doc = new DOMParser().parseFromString(trimmed, "image/svg+xml");
  const root = doc.documentElement;
  if (!root || root.nodeName.toLowerCase() !== "svg") return "";
  if (root.getElementsByTagName("parsererror").length > 0) return "";

  const STRIP = [
    "script",
    "foreignObject",
    "iframe",
    "object",
    "embed",
    "audio",
    "video",
    "handler",
  ];
  root.querySelectorAll(STRIP.join(",")).forEach((n) => n.remove());

  const walk = (el: Element) => {
    const tag = el.nodeName.toLowerCase();
    for (const attr of Array.from(el.attributes)) {
      const name = attr.name.toLowerCase();
      const val = attr.value.replace(/\s+/g, "").toLowerCase();
      if (name.startsWith("on")) {
        el.removeAttribute(attr.name);
      } else if (
        (name === "href" || name === "xlink:href") &&
        (val.startsWith("javascript:") ||
          (val.startsWith("data:") && !val.startsWith("data:image/")))
      ) {
        el.removeAttribute(attr.name);
      } else if (name === "style" && val.includes("javascript:")) {
        el.removeAttribute(attr.name);
      } else if (
        (tag === "set" || tag === "animate") &&
        name === "attributename" &&
        val.startsWith("on")
      ) {
        // <set attributeName="onclick" .../> can inject a handler — drop it.
        el.remove();
        return;
      }
    }
    Array.from(el.children).forEach((child) => walk(child));
  };
  walk(root);

  // Scope ids so multiple inlined SVGs on one page don't collide: marker /
  // clipPath / gradient defs are referenced via url(#id) or href="#id". A bare
  // <img> kept each SVG in its own document; inline DOM shares one namespace,
  // so without this the 2nd+ figure's arrows/gradients break.
  const ids = new Set<string>();
  root.querySelectorAll("[id]").forEach((el) => {
    const id = el.getAttribute("id");
    if (id) ids.add(id);
  });
  if (ids.size) {
    const prefix = `dtsvg${svgScopeSeq++}-`;
    const rescope = (el: Element) => {
      const ownId = el.getAttribute("id");
      if (ownId && ids.has(ownId)) el.setAttribute("id", prefix + ownId);
      for (const attr of Array.from(el.attributes)) {
        const lname = attr.name.toLowerCase();
        let v = attr.value.replace(
          /url\(\s*(['"]?)#([^)'"\s]+)\1\s*\)/g,
          (m, q, id) => (ids.has(id) ? `url(${q}#${prefix}${id}${q})` : m),
        );
        if (
          (lname === "href" || lname.endsWith(":href")) &&
          v.charAt(0) === "#" &&
          ids.has(v.slice(1))
        ) {
          v = `#${prefix}${v.slice(1)}`;
        } else if (
          lname === "aria-labelledby" ||
          lname === "aria-describedby"
        ) {
          v = v
            .split(/\s+/)
            .map((token) => (ids.has(token) ? prefix + token : token))
            .join(" ");
        }
        if (v !== attr.value) el.setAttribute(attr.name, v);
      }
      Array.from(el.children).forEach((child) => rescope(child));
    };
    rescope(root);
  }

  return root.outerHTML;
}

function SvgFigure({ svg }: { svg: string }) {
  const { t } = useTranslation();
  const trimmed = svg.trim();
  const looksSvg = trimmed.startsWith("<svg") || trimmed.startsWith("<?xml");

  // Client-only component (mounted via dynamic ssr:false), so DOMParser is
  // always available and there's no SSR/hydration concern — sanitize in useMemo.
  const safe = useMemo(
    () => (looksSvg ? sanitizeSvg(trimmed) : ""),
    [looksSvg, trimmed],
  );

  if (!looksSvg || !safe) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-4 dark:border-red-900/60 dark:bg-red-950/30">
        <p className="text-sm font-medium text-red-600 dark:text-red-400">
          {t("SVG rendering error")}
        </p>
        <pre className="mt-2 whitespace-pre-wrap text-xs text-red-500">
          {looksSvg
            ? t("SVG could not be safely rendered")
            : t("Invalid SVG: does not start with <svg")}
        </pre>
      </div>
    );
  }

  // Inline (not <img>) so host CSS and the SVG's own <style> apply. Clicking a
  // node carrying data-prompt drops a follow-up question into the composer (via
  // a window event the chat page listens for) — prefilled, not auto-sent.
  const onSvgClick = (e: MouseEvent<HTMLDivElement>) => {
    const node = (e.target as Element).closest?.("[data-prompt]");
    const prompt = node?.getAttribute("data-prompt")?.trim();
    if (prompt) {
      window.dispatchEvent(
        new CustomEvent("dt:visualize-prompt", { detail: prompt }),
      );
    }
  };

  return (
    <div
      className="dt-svg-root flex justify-center overflow-x-auto"
      onClick={onSvgClick}
      dangerouslySetInnerHTML={{ __html: safe }}
    />
  );
}

// A model occasionally emits several <svg> blocks in one response, and the
// backend extractor concatenates everything from the first <svg to the last
// </svg> — so one code.content can hold multiple svgs with colliding ids
// (marker/gradient/clipPath). Split them and render each as its own figure,
// independently sanitized and id-scoped, instead of one malformed multi-root
// document where only the last svg's defs win.
function splitSvgBlocks(raw: string): string[] {
  const blocks = raw.match(/<svg[\s\S]*?<\/svg>/gi);
  return blocks && blocks.length ? blocks : [raw.trim()];
}

function SvgRenderer({ svg }: { svg: string }) {
  const blocks = useMemo(() => splitSvgBlocks(svg.trim()), [svg]);
  if (blocks.length <= 1) {
    return <SvgFigure svg={blocks[0] ?? svg} />;
  }
  return (
    <div className="flex w-full flex-col gap-4">
      {blocks.map((block, i) => (
        <SvgFigure key={i} svg={block} />
      ))}
    </div>
  );
}

type TextResult = Extract<
  VisualizeResult,
  { render_type: "svg" | "chartjs" | "mermaid" | "html" }
>;

function renderTextVisualization(result: TextResult) {
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

export default function VisualizationViewer({
  result,
}: {
  result: VisualizeResult;
}) {
  const { t } = useTranslation();

  // All hooks must run unconditionally before any early return — React
  // requires a stable hook order across renders. The text-path body below
  // is the only consumer of these states; the manim path returns earlier
  // and ignores them.
  const [showCode, setShowCode] = useState(false);
  const [copied, setCopied] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);

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

  if (isManimResult(result)) {
    return <MathAnimatorViewer result={result.manim} />;
  }

  // TypeScript narrows ``result`` to the text-only variant from here on.
  // HTML iframe already provides its own "Open in new tab" affordance; the
  // sandboxed iframe also doesn't behave well inside a re-rendered modal.
  const supportsFullscreen = result.render_type !== "html";

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
    <div className="space-y-3">
      {/* Visualization area */}
      <div
        className={`relative ${
          result.render_type === "html"
            ? "overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--background)]"
            : "overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--background)] p-4"
        }`}
      >
        {supportsFullscreen && (
          <button
            type="button"
            onClick={() => setFullscreen(true)}
            title={t("Fullscreen")}
            className="absolute right-2 top-2 z-10 inline-flex items-center gap-1 rounded-md border border-[var(--border)] bg-[var(--background)]/90 px-2 py-1 text-[10px] font-medium text-[var(--muted-foreground)] backdrop-blur transition-colors hover:text-[var(--foreground)]"
          >
            <Maximize2 size={10} strokeWidth={1.8} />
            {t("Fullscreen")}
          </button>
        )}
        {renderTextVisualization(result)}
      </div>

      {/* Toolbar */}
      <div className="flex items-center gap-2">
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
          {result.render_type === "svg"
            ? "SVG"
            : result.render_type === "mermaid"
              ? `Mermaid · ${result.analysis.chart_type || "diagram"}`
              : result.render_type === "html"
                ? `HTML · ${result.analysis.chart_type || "interactive"}`
                : `Chart.js · ${result.analysis.chart_type || "chart"}`}
        </span>
      </div>

      {/* Code panel — matches the always-dark .md-code-block style used by the
          markdown renderers so a "Show code" toggle inside a chart message
          looks identical to a fenced code block in the assistant response. */}
      {showCode && (
        <div className="md-code-block overflow-hidden rounded-xl border border-[var(--border)] bg-[#1f2937]">
          <div className="border-b border-white/10 px-3 py-2 text-[11px] font-medium uppercase tracking-wider text-[#9ca3af]">
            {result.code.language}
          </div>
          <pre className="max-h-80 overflow-auto p-4 text-[13px] leading-relaxed text-[#e5e7eb]">
            <code>{result.code.content}</code>
          </pre>
        </div>
      )}

      {/* Review notes */}
      {result.review.changed && result.review.review_notes && (
        <p className="text-[11px] text-[var(--muted-foreground)]">
          {t("Review")}: {result.review.review_notes}
        </p>
      )}

      {/* Fullscreen overlay — rendered via portal: the message bubble sits
          inside transformed/overflow ancestors (streaming animations, chat
          scroll root), which break position:fixed and put the composer above
          the overlay. document.body has neither problem. */}
      {fullscreen &&
        supportsFullscreen &&
        createPortal(
          <div
            className="fixed inset-0 z-[120] flex flex-col bg-black/85 p-4 backdrop-blur-sm"
            onClick={() => setFullscreen(false)}
          >
            <div className="mb-2 flex shrink-0 items-center justify-between text-white">
              <div className="text-xs uppercase tracking-wider opacity-80">
                {result.render_type === "svg"
                  ? "SVG"
                  : result.render_type === "mermaid"
                    ? `Mermaid · ${result.analysis.chart_type || "diagram"}`
                    : `Chart.js · ${result.analysis.chart_type || "chart"}`}
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
            {/* m-auto (not items-center/justify-center) so oversized content
                stays scrollable from its start edge instead of clipping. */}
            <div
              className="flex flex-1 overflow-auto rounded-xl bg-[var(--card)] p-6 shadow-2xl"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="dt-viz-fullscreen m-auto w-full max-w-[1600px]">
                {renderTextVisualization(result)}
              </div>
            </div>
          </div>,
          document.body,
        )}
    </div>
  );
}
