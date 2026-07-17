"use client";

/**
 * DesmosGraph — embeds the Desmos Graphing Calculator.
 *
 * Two-phase initialization:
 *  1. Mount effect: loads script, creates calculator, marks `ready`.
 *  2. Expression effect: fires whenever `ready` or `expressions` changes
 *     and calls setExpression on the live instance.
 *
 * This separation eliminates race conditions where setExpression was called
 * before the calculator instance existed, producing a blank graph despite
 * a valid expressions list.
 */

import React, { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

/* ------------------------------------------------------------------ */
/*  Minimal Desmos typings                                             */
/* ------------------------------------------------------------------ */

interface DesmosExpression {
  id: string;
  latex: string;
  color?: string;
}

interface DesmosCalculator {
  setExpression(opts: DesmosExpression): void;
  setDefaultState(): void;
  destroy(): void;
}

interface DesmosLib {
  GraphingCalculator(
    el: HTMLElement,
    options?: Record<string, unknown>,
  ): DesmosCalculator;
}

declare global {
  interface Window {
    Desmos?: DesmosLib;
  }
}

/* ------------------------------------------------------------------ */
/*  Script loader — cached promise, called once per page               */
/* ------------------------------------------------------------------ */

const DESMOS_SCRIPT =
  "https://www.desmos.com/api/v1.9/calculator.js?apiKey=dcb31709b452b1cf9dc26972add0fda6";

let scriptPromise: Promise<void> | null = null;

function loadDesmos(): Promise<void> {
  if (typeof window === "undefined")
    return Promise.reject(new Error("SSR"));
  if (window.Desmos) return Promise.resolve();
  if (scriptPromise) return scriptPromise;

  scriptPromise = new Promise<void>((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>(
      `script[src="${DESMOS_SCRIPT}"]`,
    );
    if (existing) {
      if (window.Desmos) { resolve(); return; }
      existing.addEventListener("load", () => resolve());
      existing.addEventListener("error", () => { scriptPromise = null; reject(new Error("Desmos load failed")); });
      return;
    }
    const s = document.createElement("script");
    s.src = DESMOS_SCRIPT;
    s.async = true;
    s.onload = () => resolve();
    s.onerror = () => { scriptPromise = null; reject(new Error("Desmos load failed")); };
    document.head.appendChild(s);
  });

  return scriptPromise;
}

/* ------------------------------------------------------------------ */
/*  Color palette                                                      */
/* ------------------------------------------------------------------ */

const COLORS = [
  "#2d70b3",
  "#d9490b",
  "#388c46",
  "#6042a6",
  "#c74440",
];

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export interface DesmosGraphProps {
  expressions: string[];
  title?: string;
  className?: string;
  height?: number;
}

const DesmosGraph: React.FC<DesmosGraphProps> = ({
  expressions,
  title,
  className = "",
  height = 480,
}) => {
  const { t } = useTranslation();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const calcRef    = useRef<DesmosCalculator | null>(null);
  const [ready, setReady]   = useState(false);
  const [error, setError]   = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  /* ── Phase 1: create the calculator instance once ── */
  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        await loadDesmos();
        if (cancelled || !containerRef.current || !window.Desmos) return;

        calcRef.current?.destroy();

        calcRef.current = window.Desmos.GraphingCalculator(
          containerRef.current,
          {
            keypad: false,
            expressions: false,   // hides the expression side-panel
            settingsMenu: false,
            zoomButtons: true,
            invertedColors: false, // white background always
            border: false,
            lockViewport: false,
          },
        );

        if (!cancelled) {
          setLoading(false);
          setReady(true);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : String(e));
          setLoading(false);
        }
      }
    })();

    return () => {
      cancelled = true;
      calcRef.current?.destroy();
      calcRef.current = null;
      setReady(false);
    };
  }, []); // runs once on mount

  /* ── Phase 2: push expressions whenever calc is ready or list changes ── */
  useEffect(() => {
    const calc = calcRef.current;
    if (!ready || !calc) return;

    // Reset state first so stale curves don't linger
    calc.setDefaultState();

    // Re-add all current expressions
    expressions.forEach((latex, idx) => {
      calc.setExpression({
        id: `e${idx}`,
        latex,
        color: COLORS[idx % COLORS.length],
      });
    });
  }, [ready, expressions]);

  /* ── Render ── */
  return (
    <div
      className={`flex flex-col overflow-hidden rounded-xl border border-gray-200 bg-white ${className}`}
    >
      {title && (
        <div className="flex items-center gap-2 border-b border-gray-200 bg-white px-3 py-2">
          <span className="text-sm font-semibold text-gray-800">{title}</span>
          {expressions.length > 0 && (
            <span className="rounded-full bg-blue-50 px-2 py-0.5 text-xs text-blue-600">
              {expressions.length}{" "}
              {expressions.length === 1 ? t("expression") : t("expressions")}
            </span>
          )}
        </div>
      )}

      {error ? (
        <div className="flex flex-col items-center justify-center gap-2 p-6 text-sm text-red-600">
          <span>{t("Failed to load Desmos")}</span>
          <code className="text-xs opacity-70">{error}</code>
        </div>
      ) : (
        <div className="relative bg-white" style={{ height }}>
          {loading && (
            <div className="absolute inset-0 flex items-center justify-center bg-white">
              <span className="animate-pulse text-sm text-gray-400">
                {t("Loading graph…")}
              </span>
            </div>
          )}
          {/* The div Desmos mounts into — must always be in DOM */}
          <div ref={containerRef} className="h-full w-full bg-white" />
        </div>
      )}
    </div>
  );
};

export default DesmosGraph;
