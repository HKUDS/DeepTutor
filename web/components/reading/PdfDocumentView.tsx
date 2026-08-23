"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { loadPdfjs, type PdfDocument } from "@/lib/pdfjs-loader";
import type {
  AnnotationItem,
  NormalisedRect,
  ReadingTextSelector,
} from "@/lib/reading-api";
import { rawMaterialUrl } from "@/lib/reading-api";
import { domRangeForQuote } from "@/lib/reading-quote-locator";
import {
  cleanQuote,
  locatorOfSelection,
  normaliseRects,
} from "@/lib/reading-selection";
import { PdfPage } from "./PdfPage";

/** Pages kept rendered on each side of the viewport. */
const RENDER_MARGIN = 1;
/** How long a `reader_goto` highlight pulses before fading. */
const PAGE_GAP = 16;

export interface SelectionPayload {
  locator: number;
  quote: string;
  rects: NormalisedRect[];
  sourceAnchor?: string;
  selectors?: ReadingTextSelector[];
  /** Viewport coordinates of the selection, for popover placement. */
  anchor: { x: number; y: number };
}

export interface JumpRequest {
  locator: number;
  quote?: string;
  /** Changes on every request so repeats of the same target still fire. */
  nonce: number;
}

export interface PdfDocumentViewProps {
  materialId: string;
  unitCount: number;
  annotations: AnnotationItem[];
  jump: JumpRequest | null;
  highlightedAnnotationId?: string | null;
  onSelection: (payload: SelectionPayload | null) => void;
  onAnnotationClick?: (annotation: AnnotationItem) => void;
  onVisibleLocatorChange?: (locator: number) => void;
}

/**
 * Scrolling PDF view with windowed rendering.
 *
 * Every page is laid out at its real height from the start (measured from page
 * one and refined as pages render), so the scrollbar is honest and jumping to a
 * locator lands in the right place without rendering the pages in between. Only
 * pages near the viewport hold a canvas — a 600-page book would otherwise
 * exhaust canvas memory long before the user reached the end.
 */
export function PdfDocumentView({
  materialId,
  unitCount,
  annotations,
  jump,
  highlightedAnnotationId,
  onSelection,
  onAnnotationClick,
  onVisibleLocatorChange,
}: PdfDocumentViewProps) {
  const { t } = useTranslation();
  const scrollRef = useRef<HTMLDivElement | null>(null);
  // Loaded document and load error are both tagged with the material they
  // belong to, so switching documents invalidates them by derivation instead of
  // by a synchronous reset inside the effect (which would cascade a render).
  const [loaded, setLoaded] = useState<{
    materialId: string;
    doc: PdfDocument;
    ratio: number;
  } | null>(null);
  const [loadError, setLoadError] = useState<{
    materialId: string;
    message: string;
  } | null>(null);
  const [pageWidth, setPageWidth] = useState(0);
  const [visibleLocator, setVisibleLocator] = useState(1);
  // Tagged with the jump's nonce for the same reason: a stale flash cannot
  // outlive the request that produced it.
  const [flash, setFlash] = useState<{
    nonce: number;
    locator: number;
    rects: NormalisedRect[];
  } | null>(null);

  const doc = loaded?.materialId === materialId ? loaded.doc : null;
  const fallbackRatio =
    loaded?.materialId === materialId ? loaded.ratio : 1.414; // A4 until measured
  const error = loadError?.materialId === materialId ? loadError.message : null;

  // -- document ------------------------------------------------------------

  useEffect(() => {
    let cancelled = false;
    // The loading task — not the document proxy — owns `destroy()`, and
    // destroying it is what releases the worker port and the buffered file.
    let task: { destroy: () => Promise<void> } | null = null;

    (async () => {
      try {
        const pdfjs = await loadPdfjs();
        const loadingTask = pdfjs.getDocument({
          url: rawMaterialUrl(materialId),
          // The raw route sits behind the session cookie like every other API
          // route; pdf.js does its own fetching, so it needs telling.
          withCredentials: true,
        });
        task = loadingTask;
        const opened: PdfDocument = await loadingTask.promise;
        if (cancelled) return;
        const first = await opened.getPage(1);
        const viewport = first.getViewport({ scale: 1 });
        if (cancelled) return;
        setLoaded({
          materialId,
          doc: opened,
          ratio: viewport.width > 0 ? viewport.height / viewport.width : 1.414,
        });
      } catch (caught) {
        if (cancelled) return;
        setLoadError({
          materialId,
          message:
            caught instanceof Error
              ? caught.message
              : t("This document could not be opened."),
        });
      }
    })();

    return () => {
      cancelled = true;
      // Release the worker's copy of the file; without this each opened
      // document leaks a worker port for the life of the session.
      void task?.destroy();
    };
  }, [materialId, t]);

  // -- width ---------------------------------------------------------------

  useEffect(() => {
    const element = scrollRef.current;
    if (!element) return;
    const measure = () => {
      // Leave room for the scrollbar gutter and the page's own margin.
      const available = element.clientWidth - 48;
      setPageWidth(Math.max(240, Math.min(1100, available)));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [doc]);

  // -- which page is on screen --------------------------------------------

  /**
   * Track the page on screen from scroll position, measured directly.
   *
   * Deliberately not an `IntersectionObserver`. That was the first
   * implementation and it does not fire at all in some embedded browsers — which
   * silently froze the render window at page 1, so scrolling to page 10 showed a
   * blank placeholder forever. Rect maths on a throttled scroll event has no
   * such dependency, and "which page covers the most of the viewport" is a
   * question it answers directly.
   */
  useEffect(() => {
    const root = scrollRef.current;
    if (!root || !doc) return;

    let frame = 0;
    const measure = () => {
      frame = 0;
      const rootRect = root.getBoundingClientRect();
      const pages = root.querySelectorAll<HTMLElement>("[data-reader-unit]");
      let best: { locator: number; covered: number } | null = null;
      for (const page of pages) {
        const rect = page.getBoundingClientRect();
        const covered =
          Math.min(rect.bottom, rootRect.bottom) -
          Math.max(rect.top, rootRect.top);
        if (covered <= 0) continue;
        const locator = Number(page.dataset.readerUnit ?? "0");
        if (!locator) continue;
        if (!best || covered > best.covered) best = { locator, covered };
      }
      if (best)
        setVisibleLocator((current) =>
          current === best.locator ? current : best.locator,
        );
    };

    const onScroll = () => {
      // One measurement per frame: a fast flick fires scroll dozens of times and
      // each measurement walks every page element.
      if (!frame) frame = window.requestAnimationFrame(measure);
    };

    measure();
    root.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      root.removeEventListener("scroll", onScroll);
      if (frame) window.cancelAnimationFrame(frame);
    };
  }, [doc, unitCount, pageWidth]);

  useEffect(() => {
    onVisibleLocatorChange?.(visibleLocator);
  }, [visibleLocator, onVisibleLocatorChange]);

  /**
   * Which pages hold a canvas: those near the viewport, plus those near an
   * outstanding jump target.
   *
   * The jump anchor matters — a jump to a distant page has to render it *before*
   * its text layer can be searched for the quote, and waiting for the smooth
   * scroll to bring it into view first would time the search out.
   */
  const isActive = useCallback(
    (locator: number) => {
      const near = (anchor: number) =>
        Math.abs(locator - anchor) <= RENDER_MARGIN;
      return near(visibleLocator) || (jump ? near(jump.locator) : false);
    },
    [visibleLocator, jump],
  );

  // -- jumping -------------------------------------------------------------

  const scrollToLocator = useCallback((locator: number) => {
    const root = scrollRef.current;
    if (!root) return false;
    const target = root.querySelector<HTMLElement>(
      `[data-reader-unit="${locator}"]`,
    );
    if (!target) return false;
    // Measured, not `offsetTop`: the nearest positioned ancestor is the reader
    // shell (it is absolutely positioned), not this scroll container, so
    // `offsetTop` is off by the header's height. Rect maths is independent of
    // the offset-parent chain and cannot drift when the chrome above changes.
    const top =
      target.getBoundingClientRect().top -
      root.getBoundingClientRect().top +
      root.scrollTop -
      PAGE_GAP;
    // Assigned, never animated. Programmatic smooth scrolling is silently a
    // no-op in some embedded browsers, and `scroll-behavior` in CSS would make
    // this assignment inherit that failure — a citation jump that does nothing
    // is far worse than one that does not glide.
    root.scrollTop = Math.max(0, top);
    return true;
  }, []);

  useEffect(() => {
    if (!jump || !doc) return;
    const locator = Math.min(Math.max(1, jump.locator), unitCount);
    const nonce = jump.nonce;
    const quote = jump.quote;
    let cancelled = false;
    let timer: number | undefined;

    // Scrolling and searching both wait a frame: the jump may have just widened
    // the render window, and the target page needs to exist in the DOM first.
    let scrollTries = 0;
    const run = () => {
      if (cancelled) return;
      if (!scrollToLocator(locator)) {
        // The page div may not be in the DOM for a frame after a jump widens the
        // render window. Bounded, so a locator that never appears (a truncated
        // document, say) cannot spin forever.
        scrollTries += 1;
        if (scrollTries <= 20) timer = window.setTimeout(run, 120);
        return;
      }
      if (!quote) return;
      let attempts = 0;
      const findQuote = () => {
        if (cancelled) return;
        attempts += 1;
        const root = scrollRef.current;
        const page = root?.querySelector<HTMLElement>(
          `[data-reader-unit="${locator}"]`,
        );
        const layer = page?.querySelector<HTMLElement>(".textLayer");
        if (layer && layer.childElementCount > 0) {
          const range = domRangeForQuote(layer, quote);
          const box = page?.getBoundingClientRect();
          if (range && box) {
            const rects = normaliseRects([...range.getClientRects()], {
              left: box.left,
              top: box.top,
              width: box.width,
              height: box.height,
            });
            if (rects.length) {
              setFlash({ nonce, locator, rects });
              return;
            }
          }
        }
        // Keep trying on a miss rather than giving up: a text layer is populated
        // progressively, so "has some children" does not mean "has all of them"
        // — a quote spanning a not-yet-rendered span would be lost forever if
        // the first non-empty poll were treated as final. Bounded, so a quote
        // that genuinely is not on the page (an image caption, a scan) stops
        // polling; the page is still scrolled into view, which is the useful
        // part of the request.
        if (attempts < 25) timer = window.setTimeout(findQuote, 120);
      };
      timer = window.setTimeout(findQuote, 140);
    };
    timer = window.setTimeout(run, 0);

    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [jump, doc, unitCount, scrollToLocator]);

  // Tagged with the nonce that produced it, so the previous jump's highlight is
  // superseded by derivation — no timer, and no way for a stale highlight to
  // outlive the request behind it. The mark itself persists until then; see the
  // `dt-reader-flash` rules for why it does not fade out.
  const activeFlash =
    flash && jump && flash.nonce === jump.nonce ? flash : null;

  // -- selection -----------------------------------------------------------

  const handlePointerUp = useCallback(() => {
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed || selection.rangeCount === 0) {
      onSelection(null);
      return;
    }
    const range = selection.getRangeAt(0);
    const root = scrollRef.current;
    if (!root || !root.contains(range.commonAncestorContainer)) {
      onSelection(null);
      return;
    }
    const quote = cleanQuote(selection.toString());
    if (!quote) {
      onSelection(null);
      return;
    }

    // Attribute the selection to the page it started on, and measure against
    // that page's box so the rects are in its own normalised space.
    const startElement =
      range.startContainer.nodeType === Node.ELEMENT_NODE
        ? (range.startContainer as HTMLElement)
        : range.startContainer.parentElement;
    const page = startElement?.closest<HTMLElement>("[data-reader-unit]");
    const locator = locatorOfSelection([
      Number(page?.dataset.readerUnit ?? "0") || null,
    ]);
    if (!page || !locator) {
      onSelection(null);
      return;
    }

    const box = page.getBoundingClientRect();
    const clientRects = [...range.getClientRects()];
    const rects = normaliseRects(clientRects, {
      left: box.left,
      top: box.top,
      width: box.width,
      height: box.height,
    });
    if (!rects.length) {
      onSelection(null);
      return;
    }
    const last = clientRects[clientRects.length - 1];
    onSelection({
      locator,
      quote,
      rects,
      anchor: { x: last.left + last.width / 2, y: last.top },
    });
  }, [onSelection]);

  // -- render --------------------------------------------------------------

  if (error) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 px-8 text-center">
        <p className="text-[13px] font-medium text-[var(--foreground)]">
          {t("This document could not be opened.")}
        </p>
        <p className="max-w-[420px] text-[12px] text-[var(--muted-foreground)]">
          {error}
        </p>
      </div>
    );
  }

  return (
    <div
      ref={scrollRef}
      onMouseUp={handlePointerUp}
      className="dt-reader-scroll h-full overflow-y-auto overscroll-contain bg-[var(--muted)]/40 px-6 py-4"
    >
      {!doc ? (
        <div className="flex h-full items-center justify-center gap-2 text-[12px] text-[var(--muted-foreground)]">
          <Loader2 size={14} className="animate-spin" />
          {t("Opening document…")}
        </div>
      ) : (
        <div className="flex flex-col items-center" style={{ gap: PAGE_GAP }}>
          {Array.from({ length: unitCount }, (_, index) => index + 1).map(
            (locator) => (
              <PdfPage
                key={locator}
                doc={doc}
                locator={locator}
                width={pageWidth}
                fallbackRatio={fallbackRatio}
                active={isActive(locator)}
                annotations={annotations}
                highlightedAnnotationId={highlightedAnnotationId}
                flashRects={
                  activeFlash?.locator === locator
                    ? activeFlash.rects
                    : undefined
                }
                onAnnotationClick={onAnnotationClick}
              />
            ),
          )}
        </div>
      )}
    </div>
  );
}
