"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { ChevronLeft, ChevronRight, Sparkles, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { TOUR_STEPS, useSettings } from "./SettingsContext";

// Cross-route guided tour. Mounted in the settings layout so the same
// instance survives navigation between sub-pages. After each step
// transition the controller pushes router.push to the step's route;
// here we wait until the pathname matches AND the target ``data-tour``
// element exists before painting, so we never spotlight an empty rect
// mid-transition.
//
// Visual design:
//   • Soft full-screen scrim (no harsh cutout) plus a translucent
//     highlight ring around the target — feels less "modal blocker",
//     more "look here".
//   • Tooltip card carries a step pill (3 / 10), a section title +
//     short description, and Back / Next + Skip controls.
//   • Arrow keys + Esc work as keyboard shortcuts so tour-as-orientation
//     doesn't require mousing.
const TOOLTIP_W = 340;
const TOOLTIP_H_EST = 200;
const SCROLL_PADDING = 80;
const HIGHLIGHT_PAD = 10;

export function SettingsTourOverlay() {
  const { t } = useTranslation();
  const pathname = usePathname();
  const { tourStepIndex, advanceTour, goBackTour, skipTour } = useSettings();
  const [rect, setRect] = useState<DOMRect | null>(null);

  const guideStep =
    tourStepIndex >= 0 && tourStepIndex < TOUR_STEPS.length
      ? TOUR_STEPS[tourStepIndex]
      : null;
  const totalSteps = TOUR_STEPS.length;
  const isFirst = tourStepIndex <= 0;
  const isLast = tourStepIndex === totalSteps - 1;

  // The "wanted" target identity. When this changes between renders we
  // drop the previously resolved rect during render (React's "store
  // info from previous render" pattern), then the effect below resolves
  // the new one.
  const wantKey = guideStep
    ? `${guideStep.target}@${guideStep.route}@${pathname}`
    : null;
  const [resolvedFor, setResolvedFor] = useState<string | null>(null);
  if (resolvedFor !== wantKey) {
    setResolvedFor(wantKey);
    if (rect !== null) setRect(null);
  }

  // Resolve the target element. We retry briefly because the new
  // sub-page may not have mounted by the time the step changes
  // (Next.js route transitions are async). 8 attempts × 80ms = 640ms
  // ceiling; enough for any normal client-side route swap, well below
  // perceptual budget.
  useEffect(() => {
    if (!guideStep) return;
    if (!pathname.startsWith(guideStep.route)) return;
    let cancelled = false;
    let attempt = 0;
    const tryResolve = () => {
      if (cancelled) return;
      const el = document.querySelector(`[data-tour="${guideStep.target}"]`);
      if (el) {
        // Scroll the target into view BEFORE measuring so a
        // far-down target like the toolbar Apply button isn't
        // painted off-screen.
        el.scrollIntoView({ behavior: "smooth", block: "center" });
        // Defer measurement by one frame so the scroll animation
        // has settled.
        window.requestAnimationFrame(() => {
          if (cancelled) return;
          setRect(el.getBoundingClientRect());
        });
        return;
      }
      attempt += 1;
      if (attempt < 8) {
        window.setTimeout(tryResolve, 80);
      }
    };
    const raf = window.requestAnimationFrame(tryResolve);
    return () => {
      cancelled = true;
      window.cancelAnimationFrame(raf);
    };
  }, [guideStep, pathname]);

  // Keep the highlight in sync as the user resizes the window.
  useEffect(() => {
    if (!guideStep) return;
    const onResize = () => {
      const el = document.querySelector(`[data-tour="${guideStep.target}"]`);
      if (el) setRect(el.getBoundingClientRect());
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [guideStep]);

  // Keyboard shortcuts. Esc skips; ←/→ navigates.
  useEffect(() => {
    if (!guideStep) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        skipTour();
      } else if (e.key === "ArrowRight" || e.key === "Enter") {
        e.preventDefault();
        advanceTour();
      } else if (e.key === "ArrowLeft" && !isFirst) {
        e.preventDefault();
        goBackTour();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [guideStep, advanceTour, goBackTour, skipTour, isFirst]);

  if (!guideStep || !rect) return null;

  const holeLeft = rect.left - HIGHLIGHT_PAD;
  const holeTop = rect.top - HIGHLIGHT_PAD;
  const holeW = rect.width + HIGHLIGHT_PAD * 2;
  const holeH = rect.height + HIGHLIGHT_PAD * 2;

  // Tooltip placement: prefer below the highlight; flip above if it
  // would overflow; clamp horizontally so the card stays on-screen.
  const wouldOverflowBelow =
    holeTop + holeH + 16 + TOOLTIP_H_EST > window.innerHeight - SCROLL_PADDING;
  const tooltipTop = wouldOverflowBelow
    ? Math.max(16, holeTop - TOOLTIP_H_EST - 16)
    : Math.min(holeTop + holeH + 16, window.innerHeight - TOOLTIP_H_EST - 16);
  const tooltipLeft = Math.max(
    16,
    Math.min(holeLeft, window.innerWidth - TOOLTIP_W - 16),
  );

  return (
    <div className="fixed inset-0 z-[9999] pointer-events-none">
      {/* Soft scrim — pointer-events disabled so the user can still
          click highlighted controls if they want to. The click-through
          experience is intentional: the tour describes; it does not
          block. */}
      <div className="absolute inset-0 bg-[var(--overlay)] backdrop-blur-[1px] transition-opacity duration-200" />

      {/* Highlight ring around the target. A soft outer glow + a crisp
          inner outline reads more "spotlight" than a hard cut-out. */}
      <div
        className="absolute rounded-2xl ring-2 ring-[var(--primary)] ring-offset-2 ring-offset-transparent transition-all duration-300"
        style={{
          left: holeLeft,
          top: holeTop,
          width: holeW,
          height: holeH,
          boxShadow:
            "0 0 0 9999px rgba(0,0,0,0.35), 0 0 32px rgba(var(--primary-rgb,212,160,90), 0.45)",
        }}
      />

      {/* Tooltip */}
      <div
        className="pointer-events-auto absolute z-10 w-[340px] overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-[0_24px_60px_-12px_rgba(0,0,0,0.3)] animate-fade-in"
        style={{ top: tooltipTop, left: tooltipLeft }}
        role="dialog"
        aria-labelledby="tour-title"
      >
        {/* Step progress bar — thin strip across the top of the card. */}
        <div className="h-1 w-full bg-[var(--muted)]/40">
          <div
            className="h-full bg-[var(--foreground)] transition-all duration-500"
            style={{
              width: `${((tourStepIndex + 1) / totalSteps) * 100}%`,
            }}
          />
        </div>

        <div className="px-5 pt-4 pb-3">
          {/* Header row: step pill + skip × */}
          <div className="mb-3 flex items-center justify-between">
            <div className="inline-flex items-center gap-1.5 rounded-full bg-[var(--muted)]/50 px-2.5 py-1 text-[11px] font-medium text-[var(--muted-foreground)]">
              <Sparkles className="h-3 w-3" />
              <span>
                {t("Step {{current}} of {{total}}", {
                  current: tourStepIndex + 1,
                  total: totalSteps,
                })}
              </span>
            </div>
            <button
              type="button"
              onClick={skipTour}
              aria-label={t("Skip tour")}
              className="rounded-md p-1 text-[var(--muted-foreground)]/60 transition-colors hover:bg-[var(--muted)]/40 hover:text-[var(--foreground)]"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>

          <h2
            id="tour-title"
            className="mb-1.5 text-[14px] font-semibold text-[var(--foreground)]"
          >
            {t(guideStep.titleKey)}
          </h2>
          <p className="text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
            {t(guideStep.descKey)}
          </p>
        </div>

        {/* Footer: Back / Next */}
        <div className="flex items-center justify-between gap-2 border-t border-[var(--border)]/60 bg-[var(--background)]/30 px-5 py-3">
          <button
            type="button"
            onClick={goBackTour}
            disabled={isFirst}
            className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)] disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <ChevronLeft className="h-3 w-3" />
            {t("Back")}
          </button>
          <button
            type="button"
            onClick={skipTour}
            className="text-[12px] text-[var(--muted-foreground)]/60 transition-colors hover:text-[var(--muted-foreground)]"
          >
            {t("Skip tour")}
          </button>
          <button
            type="button"
            onClick={advanceTour}
            className="inline-flex items-center gap-1 rounded-lg bg-[var(--foreground)] px-3 py-1.5 text-[12px] font-medium text-[var(--background)] transition-opacity hover:opacity-80"
          >
            {isLast ? t("Got it") : t("Next")}
            <ChevronRight className="h-3 w-3" />
          </button>
        </div>
      </div>
    </div>
  );
}
