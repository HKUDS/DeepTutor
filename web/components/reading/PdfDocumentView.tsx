"use client";

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  loadPdfjs,
  outputScale,
  pdfjsCMapUrl,
  pdfjsWasmUrl,
  type PdfDocument,
} from "@/lib/pdfjs-loader";
import type {
  AnnotationItem,
  NormalisedRect,
  ReadingTextSelector,
} from "@/lib/reading-api";
import { rawMaterialUrl } from "@/lib/reading-api";
import { domRangeForQuote } from "@/lib/reading-quote-locator";
import {
  cleanQuote,
  selectionTextWithoutLineNumbers,
  locatorOfSelection,
  normaliseRects,
} from "@/lib/reading-selection";
import {
  DEFAULT_PDF_ZOOM,
  READER_WIDTH_INSET,
  clampPdfZoom,
  cropsPageMargins,
  effectiveZoomPercent,
  fitZoomRatio,
  fittedPageWidth,
  loadPdfZoom,
  pdfZoomShortcut,
  savePdfZoom,
  zoomedBy,
  zoomedPageWidth,
  type PdfZoomPreference,
} from "@/lib/reading-zoom";
import type { NormalisedBox } from "@/lib/pdf-page-geometry";
import { PdfPage } from "./PdfPage";
import dynamic from "next/dynamic";

const PdfZoomControls = dynamic(
  () => import("./PdfZoomControls").then((module) => module.PdfZoomControls),
  { ssr: false },
);

/** Pages kept rendered on each side of the viewport. */
const RENDER_MARGIN = 1;
/** Pages this close keep their parsed form after their canvas is freed. */
const RETAIN_MARGIN = 6;
/** How long a `reader_goto` highlight pulses before fading. */
const PAGE_GAP = 16;

export interface SelectionPayload {
  locator: number;
  quote: string;
  /**
   * The quote as reading text, when the page put something that is not text
   * into it (margin line numbers). Questions carry this; marks keep `quote`.
   */
  text?: string;
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
    /** Page 1's width at `scale: 1`, in PDF points — the base for "100%". */
    intrinsicWidth: number;
  } | null>(null);
  const [loadError, setLoadError] = useState<{
    materialId: string;
    message: string;
  } | null>(null);
  // What the pane can give the page. The page's own width is derived from this
  // and the zoom preference, so a zoom change is never mistaken for a resize.
  const [measuredWidth, setMeasuredWidth] = useState(0);
  // Seeded from storage lazily: the stored zoom never reaches the server
  // render, because the page width stays 0 and the toolbar stays unmounted
  // until the ResizeObserver and the document loader have both run.
  const [zoom, setZoom] = useState<PdfZoomPreference>(loadPdfZoom);
  // Mirrors `zoom` for the wheel/keydown handlers, which must read the
  // preference without being re-registered on every gesture frame.
  const zoomRef = useRef<PdfZoomPreference>(DEFAULT_PDF_ZOOM);
  // Debounced write of a gesture's settled zoom.
  const settleRef = useRef<number | null>(null);
  const controlsHideRef = useRef<number | null>(null);
  // A device without hover can never move a pointer into the reveal strip, so
  // the bar would be permanently unreachable: keep it out instead. Read lazily
  // for the same reason as the zoom preference above.
  const [controlsVisible, setControlsVisible] = useState(
    () =>
      typeof window !== "undefined" &&
      typeof window.matchMedia === "function" &&
      window.matchMedia("(hover: none)").matches,
  );
  // The wheel listener is registered once, so it reaches the latest
  // `showControls` through a ref instead of a dependency.
  const showControlsRef = useRef<(() => void) | null>(null);
  const pointerNearBottom = useRef(false);
  const overControls = useRef(false);
  const committedWidthRef = useRef(0);
  // Where the reader was looking when the page changed shape (fitting the text
  // vs fitting the page), so the line they were reading stays put while the
  // page heights change under them.
  const modeAnchorRef = useRef<{ locator: number; fraction: number } | null>(null);
  const resizeAnchorRef = useRef<{
    doc: PdfDocument;
    locator: string;
    /** Where the anchored point sits inside the page, vertically. */
    fraction: number;
    /** The same share, across the page's width. */
    xFraction: number;
    /** How far that point sits from the pane's top and left edges. */
    viewportOffset: number;
    horizontalOffset: number;
  } | null>(null);
  const [visibleLocator, setVisibleLocator] = useState(1);
  // Tagged with the jump's nonce for the same reason: a stale flash cannot
  // outlive the request that produced it.
  const [flash, setFlash] = useState<{
    nonce: number;
    locator: number;
    rects: NormalisedRect[];
  } | null>(null);

  // Timers that outlive the component would fire into a torn-down reader: the
  // save debounce would write a preference nobody is looking at, and the hide
  // timer would set state on an unmounted tree. Clear both on unmount.
  useEffect(() => {
    return () => {
      if (settleRef.current !== null) clearTimeout(settleRef.current);
      if (controlsHideRef.current !== null) {
        clearTimeout(controlsHideRef.current);
      }
      settleRef.current = null;
      controlsHideRef.current = null;
    };
  }, []);

  const doc = loaded?.materialId === materialId ? loaded.doc : null;
  const fallbackRatio =
    loaded?.materialId === materialId ? loaded.ratio : 1.414; // A4 until measured
  const error = loadError?.materialId === materialId ? loadError.message : null;
  const intrinsicWidth =
    loaded?.materialId === materialId ? loaded.intrinsicWidth : 0;
  // Both fit modes fill the pane at the pre-zoom width — the difference is
  // what fills it, the page or its text block. `fixed` is a share of the page's
  // real size, so it holds still when the pane changes width.
  const pageWidth =
    measuredWidth <= 0
      ? 0
      : zoom.mode === "fixed"
        ? zoomedPageWidth(
            intrinsicWidth,
            zoom.scale,
            fallbackRatio,
            outputScale(),
          )
        : fittedPageWidth(measuredWidth);
  const zoomPercent = effectiveZoomPercent(pageWidth, intrinsicWidth);

  // -- page size mode ------------------------------------------------------

  // How much of the page the reader actually sees: 1 when the page is drawn
  // whole, `visible / full` when its own margins are trimmed. The active page
  // reports it, and it is the base for "one zoom stop" — without it, stepping
  // away from a trimmed page would land below the size already on screen.
  const [cropRatio, setCropRatio] = useState(1);
  const reportCropRatio = useCallback((ratio: number) => {
    setCropRatio(Number.isFinite(ratio) && ratio > 0 ? ratio : 1);
  }, []);

  /**
   * Where the reader is looking, captured before the page changes shape.
   *
   * Fitting the text and fitting the page give every page a different height,
   * so without this the line under the reader's eyes jumps when they switch.
   */
  const captureModeAnchor = useCallback(() => {
    const root = scrollRef.current;
    if (!root) return;
    const rootRect = root.getBoundingClientRect();
    for (const page of root.querySelectorAll<HTMLElement>("[data-reader-unit]")) {
      const rect = page.getBoundingClientRect();
      if (rect.height <= 0 || rect.bottom <= rootRect.top) continue;
      if (rect.top >= rootRect.bottom) break;
      modeAnchorRef.current = {
        locator: Number(page.dataset.readerUnit ?? "0"),
        fraction: Math.max(0, (rootRect.top - rect.top) / rect.height),
      };
      return;
    }
  }, []);

  // Restore the anchored line once the new page heights have committed.
  useLayoutEffect(() => {
    const anchor = modeAnchorRef.current;
    if (!anchor) return;
    modeAnchorRef.current = null;
    const root = scrollRef.current;
    if (!root) return;
    const page = root.querySelector<HTMLElement>(
      `[data-reader-unit="${anchor.locator}"]`,
    );
    if (!page) return;
    const pageRect = page.getBoundingClientRect();
    const rootRect = root.getBoundingClientRect();
    root.scrollTop = Math.max(
      0,
      pageRect.top - rootRect.top + root.scrollTop + anchor.fraction * pageRect.height,
    );
  }, [zoom.mode]);

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
          // PDF.js loads OpenJPEG/JBIG2/QCMS from these assets when a PDF uses
          // JPEG2000 or other formats that are not decoded in pure JS.
          wasmUrl: pdfjsWasmUrl(),
          // CID fonts (most CJK documents) are translated through PDF.js'
          // predefined character maps; without this the font is dropped and its
          // runs vanish from both the canvas and the text layer.
          cMapUrl: pdfjsCMapUrl(),
          cMapPacked: true,
          // The raw route sits behind the session cookie like every other API
          // route; pdf.js does its own fetching, so it needs telling.
          withCredentials: true,
          // pdf.js asks for the file in 64 KB ranges by default. Behind the
          // app's proxy each range is a full request, and a browser runs six
          // at a time, so a few-MB paper queued dozens of them before its
          // pages could draw. 1 MB ranges ask for the same bytes in a handful.
          rangeChunkSize: 1 << 20,
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
          // Letter is the fallback: 612pt is the width most documents that
          // report nothing are actually laid out at.
          intrinsicWidth: viewport.width || 612,
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

  useLayoutEffect(() => {
    committedWidthRef.current = pageWidth;
    const anchor = resizeAnchorRef.current;
    resizeAnchorRef.current = null;
    const root = scrollRef.current;
    if (!root || !anchor || anchor.doc !== doc) return;
    const page = root.querySelector<HTMLElement>(
      `[data-reader-unit="${anchor.locator}"]`,
    );
    if (!page) return;
    const rect = page.getBoundingClientRect();
    const rootRect = root.getBoundingClientRect();
    // Restore after the new page heights commit, before paint or the visible
    // locator effect can report the page at the old pixel scroll position.
    root.scrollTop = Math.max(
      0,
      root.scrollTop +
        rect.top -
        rootRect.top +
        anchor.fraction * rect.height -
        anchor.viewportOffset,
    );
    // The same maths across, because a page zoomed past the pane's width also
    // scrolls sideways — that is the point of zoom — and restoring only the
    // vertical axis snapped the column back to its left edge on every zoom.
    // The page's CSS width is shared between pages, but it still changes with
    // the zoom, so the horizontal offset has to be re-derived, not left alone.
    root.scrollLeft = Math.max(
      0,
      root.scrollLeft +
        rect.left -
        rootRect.left +
        anchor.xFraction * rect.width -
        anchor.horizontalOffset,
    );
  }, [doc, pageWidth]);

  /**
   * Remember the point on screen that must not move.
   *
   * Without a `clientY` the anchor is the viewport's top edge — what a pane
   * resize has always used. With one it is the pointer — what a zoom gesture
   * needs, so the page grows away from the reader's cursor instead of jumping
   * to a different part of the document. `clientX` is the same idea across:
   * a zoomed page overflows the pane sideways, and without an x anchor the
   * column snaps back to its left edge on every gesture.
   */
  const captureAnchor = useCallback(
    (clientY?: number, clientX?: number) => {
      const root = scrollRef.current;
      if (!root || !doc) return;
      const rootRect = root.getBoundingClientRect();
      const y = clientY ?? rootRect.top;
      const x = clientX ?? rootRect.left;
      const pages = root.querySelectorAll<HTMLElement>("[data-reader-unit]");
      for (const page of pages) {
        const rect = page.getBoundingClientRect();
        if (rect.height <= 0 || rect.bottom <= y) continue;
        if (rect.top >= rootRect.bottom) break;
        // The point in page coordinates, plus any padding/gap above that page.
        // Coalesced notifications retain this anchor until the width commits.
        //
        // When the target sits above this page — a pane resize with a gap or the
        // document's own top padding in view — the anchor is the page's top
        // edge, not a point inside it. `Math.max` expresses both cases: the
        // anchor never floats above the page it belongs to.
        const anchorY = Math.max(y, rect.top);
        // Across, the same clamp, plus one the vertical axis does not need: a
        // page narrower than the pane leaves the pointer over the desk on
        // either side of it, so the share is pinned to the page's own edges.
        // Anchoring the nearest edge is what "the page grows away from here"
        // means when the pointer is not over the paper at all.
        const anchorX = Math.max(x, rect.left);
        resizeAnchorRef.current = {
          doc,
          locator: page.dataset.readerUnit!,
          fraction: Math.max(0, (anchorY - rect.top) / rect.height),
          xFraction:
            rect.width > 0
              ? Math.min(1, Math.max(0, (anchorX - rect.left) / rect.width))
              : 0,
          viewportOffset: Math.max(0, anchorY - rootRect.top),
          horizontalOffset: Math.max(0, anchorX - rootRect.left),
        };
        return;
      }
    },
    [doc],
  );

  useEffect(() => {
    const element = scrollRef.current;
    if (!element) return;
    const measure = () => {
      // Leave room for the scrollbar gutter and the page's own margin.
      const available = element.clientWidth - READER_WIDTH_INSET;
      const fitWidth = fittedPageWidth(available);
      if (fitWidth === committedWidthRef.current) {
        // A resize can return to the committed width before React renders.
        // Do not leave an unused anchor to override a later user scroll.
        resizeAnchorRef.current = null;
      } else if (doc && !resizeAnchorRef.current) {
        captureAnchor();
      }
      setMeasuredWidth(available);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [doc, captureAnchor]);

  // -- zoom ----------------------------------------------------------------

  // Keep the ref in step with the state; `applyZoom` also writes it eagerly so
  // a second gesture in the same frame starts from the new value.
  useEffect(() => {
    zoomRef.current = zoom;
  }, [zoom]);

  const applyZoom = useCallback(
    (next: PdfZoomPreference, clientY?: number, clientX?: number) => {
      if (cropsPageMargins(next) !== cropsPageMargins(zoomRef.current)) {
        // The pages change height rather than width, so the width-based
        // restore below would not run: anchor the line here instead.
        captureModeAnchor();
      } else {
        captureAnchor(clientY, clientX);
      }
      setZoom(next);
      zoomRef.current = next;
      if (settleRef.current !== null) clearTimeout(settleRef.current);
      settleRef.current = window.setTimeout(() => {
        settleRef.current = null;
        savePdfZoom(next);
      }, 150);
    },
    [captureAnchor, captureModeAnchor],
  );

  /** What the page is drawn at right now, used as the base for one step. */
  const currentZoomRatio = useCallback(() => {
    const current = zoomRef.current;
    if (current.mode === "fixed") return current.scale;
    // A trimmed page is drawn larger than the strip it fills: the strip is
    // `cropRatio` of the page, so the drawn size is fit / cropRatio.
    const fit = fitZoomRatio(pageWidth, intrinsicWidth);
    return cropRatio > 0 ? fit / cropRatio : fit;
  }, [pageWidth, intrinsicWidth, cropRatio]);

  const zoomBy = useCallback(
    (direction: 1 | -1, clientY?: number, clientX?: number) => {
      applyZoom(
        { mode: "fixed", scale: zoomedBy(currentZoomRatio(), direction) },
        clientY,
        clientX,
      );
    },
    [applyZoom, currentZoomRatio],
  );

  // -- zoom bar visibility -------------------------------------------------

  const showControls = useCallback(() => {
    if (controlsHideRef.current !== null) clearTimeout(controlsHideRef.current);
    setControlsVisible(true);
  }, []);

  const scheduleControlsHide = useCallback(() => {
    if (controlsHideRef.current !== null) clearTimeout(controlsHideRef.current);
    if (pointerNearBottom.current || overControls.current) return;
    controlsHideRef.current = window.setTimeout(
      () => setControlsVisible(false),
      420,
    );
  }, []);

  const handleControlsActive = useCallback(
    (active: boolean) => {
      overControls.current = active;
      if (active) showControls();
      else scheduleControlsHide();
    },
    [showControls, scheduleControlsHide],
  );

  const handlePointerMove = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      const rect = event.currentTarget.getBoundingClientRect();
      pointerNearBottom.current = event.clientY >= rect.bottom - 72;
      if (pointerNearBottom.current) showControls();
      else scheduleControlsHide();
    },
    [showControls, scheduleControlsHide],
  );

  const handlePointerLeave = useCallback(() => {
    pointerNearBottom.current = false;
    scheduleControlsHide();
  }, [scheduleControlsHide]);

  // Ctrl+wheel — and, on macOS, a trackpad pinch, which Chromium reports as
  // exactly this event. Registered non-passively because the pane would
  // otherwise scroll vertically instead of zooming.
  useEffect(() => {
    const node = scrollRef.current;
    if (!node) return;
    const onWheel = (event: WheelEvent) => {
      if (!event.ctrlKey) return;
      event.preventDefault();
      showControlsRef.current?.();
      const unit =
        event.deltaMode === 1
          ? 16
          : event.deltaMode === 2
            ? node.clientHeight
            : 1;
      // A single wheel notch can report hundreds of pixels; capping the exponent
      // keeps one notch from jumping half the range.
      const delta = Math.max(-40, Math.min(40, event.deltaY * unit));
      applyZoom(
        {
          mode: "fixed",
          scale: clampPdfZoom(currentZoomRatio() * Math.exp(-delta * 0.01)),
        },
        event.clientY,
        event.clientX,
      );
    };
    node.addEventListener("wheel", onWheel, { passive: false });
    return () => node.removeEventListener("wheel", onWheel);
  }, [applyZoom, currentZoomRatio]);

  useEffect(() => {
    showControlsRef.current = showControls;
  }, [showControls]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const root = scrollRef.current;
      // The zoom bar is a sibling of the scroll root, so neither `:hover` on
      // the root nor `activeElement` inside the root covers it: after clicking
      // Zoom the shortcut went dead until the pointer moved back over a page.
      // The bar is part of the reader — the pointer on it already reports
      // through `overControls`, and focus inside it is matched here.
      const controls = document.querySelector<HTMLElement>(
        "[data-pdf-zoom-controls]",
      );
      const focused = document.activeElement;
      const action = pdfZoomShortcut({
        key: event.key,
        modifier: event.metaKey || event.ctrlKey,
        readerHovered:
          (root?.matches(":hover") ?? false) || overControls.current,
        readerFocused:
          Boolean(root && root.contains(focused)) ||
          Boolean(controls && focused && controls.contains(focused)),
      });
      if (!action) return;
      event.preventDefault();
      if (action === "increase") zoomBy(1);
      if (action === "decrease") zoomBy(-1);
      if (action === "reset") applyZoom(DEFAULT_PDF_ZOOM);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [applyZoom, zoomBy]);

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
    const text = selectionTextWithoutLineNumbers(range);
    onSelection({
      locator,
      quote,
      ...(text ? { text } : {}),
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
    <div className="relative h-full">
      <div
        ref={scrollRef}
        // `tabIndex={-1}` makes the scrollable region focusable, which is what
        // lets a keyboard user scroll it and reach the zoom shortcuts without a
        // pointer. `TextUnitView` does the same for its own root.
        tabIndex={-1}
        onPointerDown={() => scrollRef.current?.focus({ preventScroll: true })}
        onMouseUp={handlePointerUp}
        onPointerMove={handlePointerMove}
        onPointerLeave={handlePointerLeave}
        // The desk the pages lie on. This was `bg-[var(--muted)]/40`, which
        // compiles to nothing here — a var() colour has no channels for the
        // `/NN` modifier to reach into, so the rule was dropped and the desk
        // rendered the same white as the paper on it. `--secondary` is the
        // token for exactly this: one step back from the page.
        //
        // `overflow-auto`, not `overflow-y-auto`: a page zoomed past the pane's
        // width overflows sideways, and a container that only scrolls vertically
        // would clip it with no way to reach the right-hand columns.
        className="dt-reader-scroll h-full overflow-auto overscroll-contain bg-[var(--secondary)] px-6 py-4"
      >
        {!doc ? (
          <div className="flex h-full items-center justify-center gap-2 text-[12px] text-[var(--muted-foreground)]">
            <Loader2 size={14} className="animate-spin" />
            {t("Opening document…")}
          </div>
        ) : (
          // No `items-center`: when a page is wider than the pane, a centred
          // flex item overflows on both sides and the left half becomes
          // unreachable. Each page carries `mx-auto`, whose auto margins resolve
          // to zero once the free space is negative — so the page starts at the
          // left edge and the horizontal scrollbar reaches its far side.
          <div className="flex flex-col" style={{ gap: PAGE_GAP }}>
            {Array.from({ length: unitCount }, (_, index) => index + 1).map(
              (locator) => (
                <PdfPage
                  key={locator}
                  doc={doc}
                  locator={locator}
                  width={pageWidth}
                  fallbackRatio={fallbackRatio}
                  active={isActive(locator)}
                  retain={Math.abs(locator - visibleLocator) <= RETAIN_MARGIN || isActive(locator)}
                  annotations={annotations}
                  highlightedAnnotationId={highlightedAnnotationId}
                  flashRects={
                    activeFlash?.locator === locator
                      ? activeFlash.rects
                      : undefined
                  }
                  onAnnotationClick={onAnnotationClick}
                  cropMargins={cropsPageMargins(zoom)}
                  onCropRatio={reportCropRatio}
                  inkKey={`${materialId}:${locator}`}
                />
              ),
            )}
          </div>
        )}
      </div>


      {doc && (
        <PdfZoomControls
          preference={zoom}
          effectivePercent={zoomPercent}
          visible={controlsVisible}
          onActiveChange={handleControlsActive}
          onZoomIn={() => zoomBy(1)}
          onZoomOut={() => zoomBy(-1)}
          onSelect={applyZoom}
          onReset={() => applyZoom(DEFAULT_PDF_ZOOM)}
        />
      )}
    </div>
  );
}
