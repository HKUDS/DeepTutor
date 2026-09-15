"use client";

import { ChevronLeft, ChevronRight, Loader2 } from "lucide-react";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { useTranslation } from "react-i18next";

import { apiFetch } from "@/lib/api";
import {
  getReadingPosition,
  rawMaterialUrl,
  saveReadingPosition,
  type AnnotationItem,
  type UnitReference,
} from "@/lib/reading-api";
import {
  allowsEpubPageTurn,
  bufferEpubPageTurn,
  canStartEpubPageTurn,
  directionForEpubLayout,
  epubEdgeTapDirection,
  epubPageTurnDirectionForDelta,
  epubPageTurnProgress,
  epubPageTurnSettleDuration,
  epubSpreadModeForWidth,
  isEpubPageTurnGesture,
  locatorForEpubHref,
  resolveEpubPageTurnRelease,
  type EpubPageTurnDirection,
  type EpubSpreadMode,
} from "@/lib/epub-page-turn";
import { extractEpubHeadings, type ReaderHeading } from "@/lib/reading-outline";
import { cleanQuote } from "@/lib/reading-selection";
import type { JumpRequest, SelectionPayload } from "./PdfDocumentView";

type EpubLocation = {
  start?: {
    cfi?: string;
    href?: string;
    percentage?: number;
    displayed?: { page?: number; total?: number };
  };
  end?: { displayed?: { page?: number; total?: number } };
  atStart?: boolean;
  atEnd?: boolean;
};

type EpubContents = {
  document?: Document;
  window?: Window;
};

type EpubAnnotationLayer = {
  highlight: (
    cfi: string,
    data?: Record<string, string>,
    callback?: () => void,
    className?: string,
    styles?: Record<string, string>,
  ) => void;
  remove: (cfi: string, type?: string) => void;
};

type EpubRendition = {
  display: (target?: string) => Promise<unknown>;
  next: () => Promise<unknown>;
  prev: () => Promise<unknown>;
  resize: (width: number, height: number) => void;
  spread: (spread: "none" | "always" | "auto", min?: number) => void;
  destroy: () => void;
  on: (event: string, callback: (...args: unknown[]) => void) => void;
  off: (event: string, callback: (...args: unknown[]) => void) => void;
  annotations: EpubAnnotationLayer;
  hooks: {
    content: {
      register: (callback: (contents: EpubContents) => void) => void;
    };
  };
  themes: {
    register: (
      name: string,
      rules: Record<string, Record<string, string>>,
    ) => void;
    select: (name: string) => void;
  };
};

type EpubSection = {
  href?: string;
  load: (loader: (path: string) => Promise<unknown>) => Promise<unknown>;
  find: (query: string) => Array<{ cfi: string }>;
};

type EpubBook = {
  open: (input: ArrayBuffer) => Promise<unknown>;
  ready: Promise<unknown>;
  package?: { metadata?: { direction?: string } };
  load: (path: string) => Promise<unknown>;
  spine: { get: (target: string | number) => EpubSection | undefined };
  locations?: { percentageFromCfi?: (cfi: string) => number };
  renderTo: (
    element: Element,
    options: Record<string, unknown>,
  ) => EpubRendition;
  destroy: () => void;
};

const HIGHLIGHT_COLORS: Record<string, string> = {
  yellow: "rgba(250, 220, 90, 0.55)",
  green: "rgba(140, 219, 148, 0.55)",
  blue: "rgba(122, 192, 250, 0.55)",
  pink: "rgba(250, 161, 199, 0.55)",
  purple: "rgba(199, 174, 250, 0.55)",
};

const EPUB_RELOCATION_TIMEOUT_MS = 1200;

type EpubPageState = {
  start: number;
  end: number;
  total: number;
  atStart: boolean;
  atEnd: boolean;
};

type EpubTurnVisual = {
  direction: EpubPageTurnDirection;
  phase: "dragging" | "settling" | "committing" | "boundary";
  progress: number;
  duration: number;
};

const INITIAL_PAGE_STATE: EpubPageState = {
  start: 1,
  end: 1,
  total: 1,
  atStart: true,
  atEnd: false,
};

function waitForTurnFrame(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

function nextPaint(): Promise<void> {
  return new Promise((resolve) =>
    window.requestAnimationFrame(() =>
      window.requestAnimationFrame(() => resolve()),
    ),
  );
}

export interface EpubDocumentViewProps {
  materialId: string;
  unitCount: number;
  unitRefs: UnitReference[];
  annotations: AnnotationItem[];
  jump: JumpRequest | null;
  highlightedAnnotationId?: string | null;
  onSelection: (payload: SelectionPayload | null) => void;
  onAnnotationClick?: (annotation: AnnotationItem) => void;
  onVisibleLocatorChange?: (locator: number) => void;
  onHeadingsChange?: (headings: ReaderHeading[]) => void;
  headingJump?: {
    id: string;
    nonce: number;
    locator?: number;
    sourceHref?: string;
  } | null;
  onError?: (message: string) => void;
}

/** Source-faithful, paginated EPUB renderer aligned to server locators. */
export function EpubDocumentView({
  materialId,
  unitCount,
  unitRefs,
  annotations,
  jump,
  highlightedAnnotationId,
  onSelection,
  onAnnotationClick,
  onVisibleLocatorChange,
  onHeadingsChange,
  headingJump,
  onError,
}: EpubDocumentViewProps) {
  const { t } = useTranslation();
  const hostRef = useRef<HTMLDivElement | null>(null);
  const bookRef = useRef<EpubBook | null>(null);
  const renditionRef = useRef<EpubRendition | null>(null);
  const renditionReadyRef = useRef(false);
  const isRtlRef = useRef(false);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const renderedAnchorsRef = useRef<string[]>([]);
  const refsRef = useRef(unitRefs);
  const annotationClickRef = useRef(onAnnotationClick);
  const visibleChangeRef = useRef(onVisibleLocatorChange);
  const headingsChangeRef = useRef(onHeadingsChange);
  const headingsByLocatorRef = useRef<Map<number, ReaderHeading[]>>(new Map());
  const errorRef = useRef(onError);
  const locatorRef = useRef(1);
  const pageStateRef = useRef<EpubPageState>(INITIAL_PAGE_STATE);
  const turningRef = useRef(false);
  const activeTurnRef = useRef<EpubPageTurnDirection | null>(null);
  const bufferedTurnRef = useRef<EpubPageTurnDirection | null>(null);
  const relocationResolveRef = useRef<(() => void) | null>(null);
  const turnPageRef = useRef<
    (direction: EpubPageTurnDirection, initialProgress?: number) => void
  >(() => undefined);
  const cancelGestureRef = useRef<(() => void) | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [spreadMode, setSpreadMode] = useState<EpubSpreadMode>("single");
  const [pageState, setPageState] = useState<EpubPageState>(INITIAL_PAGE_STATE);
  const [turnVisual, setTurnVisual] = useState<EpubTurnVisual | null>(null);
  const [turnBusy, setTurnBusy] = useState(false);
  const [turnError, setTurnError] = useState("");

  useEffect(() => {
    refsRef.current = unitRefs;
  }, [unitRefs]);
  useEffect(() => {
    annotationClickRef.current = onAnnotationClick;
  }, [onAnnotationClick]);
  useEffect(() => {
    visibleChangeRef.current = onVisibleLocatorChange;
  }, [onVisibleLocatorChange]);
  useEffect(() => {
    headingsChangeRef.current = onHeadingsChange;
  }, [onHeadingsChange]);
  useEffect(() => {
    headingsByLocatorRef.current.clear();
    headingsChangeRef.current?.([]);
  }, [materialId]);
  useEffect(() => {
    errorRef.current = onError;
  }, [onError]);

  const syncRenditionSize = useCallback(() => {
    cancelGestureRef.current?.();
    const host = hostRef.current;
    if (!host) return;
    const width = Math.floor(host.clientWidth);
    const height = Math.floor(host.clientHeight);
    if (width < 1 || height < 1) return;
    const nextMode = epubSpreadModeForWidth(width);
    setSpreadMode((current) => (current === nextMode ? current : nextMode));
    const rendition = renditionRef.current;
    if (!rendition || !renditionReadyRef.current) return;
    rendition.spread(nextMode === "double" ? "always" : "none", 900);
    rendition.resize(width, height);
  }, []);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    let frame = 0;
    const observer = new ResizeObserver(() => {
      if (frame) window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(syncRenditionSize);
    });
    observer.observe(host);
    syncRenditionSize();
    return () => {
      observer.disconnect();
      if (frame) window.cancelAnimationFrame(frame);
    };
  }, [syncRenditionSize]);

  const animateTurn = useCallback(
    async (
      visual: Omit<EpubTurnVisual, "duration">,
      duration: number,
    ): Promise<void> => {
      setTurnVisual({ ...visual, duration });
      await waitForTurnFrame(duration);
    },
    [],
  );

  const nudgeBoundary = useCallback(
    async (direction: EpubPageTurnDirection) => {
      const physical = directionForEpubLayout(direction, isRtlRef.current);
      setTurnVisual({
        direction: physical,
        phase: "boundary",
        progress: 0,
        duration: 0,
      });
      await nextPaint();
      await animateTurn(
        { direction: physical, phase: "boundary", progress: 0.045 },
        80,
      );
      await animateTurn(
        { direction: physical, phase: "settling", progress: 0 },
        140,
      );
      setTurnVisual(null);
    },
    [animateTurn],
  );

  const turnPage = useCallback(
    async (direction: EpubPageTurnDirection, initialProgress = 0) => {
      const rendition = renditionRef.current;
      if (!rendition) return;
      if (turningRef.current) {
        if (activeTurnRef.current) {
          bufferedTurnRef.current = bufferEpubPageTurn(
            activeTurnRef.current,
            bufferedTurnRef.current,
            direction,
          );
        }
        return;
      }
      if (!canStartEpubPageTurn(direction, false, pageStateRef.current)) {
        const reduceMotion = window.matchMedia(
          "(prefers-reduced-motion: reduce)",
        ).matches;
        if (!reduceMotion) {
          turningRef.current = true;
          activeTurnRef.current = direction;
          setTurnBusy(true);
          void nudgeBoundary(direction).finally(() => {
            turningRef.current = false;
            activeTurnRef.current = null;
            bufferedTurnRef.current = null;
            setTurnBusy(false);
          });
        } else {
          setTurnVisual(null);
          setTurnBusy(false);
        }
        return;
      }
      const physical = directionForEpubLayout(direction, isRtlRef.current);
      turningRef.current = true;
      activeTurnRef.current = direction;
      setTurnBusy(true);
      setTurnError("");
      const reduceMotion = window.matchMedia(
        "(prefers-reduced-motion: reduce)",
      ).matches;
      try {
        if (!reduceMotion) {
          const startingProgress = Math.min(0.49, initialProgress);
          setTurnVisual({
            direction: physical,
            phase: "dragging",
            progress: startingProgress,
            duration: 0,
          });
          if (startingProgress === 0) await nextPaint();
          const midpointDuration = Math.max(
            60,
            Math.round(
              epubPageTurnSettleDuration(startingProgress) *
                ((0.5 - startingProgress) /
                  Math.max(0.5, 1 - startingProgress)),
            ),
          );
          await animateTurn(
            { direction: physical, phase: "committing", progress: 0.5 },
            midpointDuration,
          );
        }

        let relocationTimer = 0;
        const relocated = new Promise<void>((resolve) => {
          const finish = () => {
            if (relocationTimer) window.clearTimeout(relocationTimer);
            if (relocationResolveRef.current === finish) {
              relocationResolveRef.current = null;
            }
            resolve();
          };
          relocationResolveRef.current = finish;
          relocationTimer = window.setTimeout(
            finish,
            EPUB_RELOCATION_TIMEOUT_MS,
          );
        });
        await (physical === "next" ? rendition.next() : rendition.prev());
        await relocated;

        if (!reduceMotion) {
          await animateTurn(
            { direction: physical, phase: "committing", progress: 1 },
            epubPageTurnSettleDuration(Math.max(0.5, initialProgress)),
          );
        }
      } catch {
        setTurnError(t("Could not turn the page."));
      } finally {
        relocationResolveRef.current?.();
        relocationResolveRef.current = null;
        setTurnVisual(null);
        turningRef.current = false;
        activeTurnRef.current = null;
        setTurnBusy(false);
        const buffered = bufferedTurnRef.current;
        bufferedTurnRef.current = null;
        if (buffered) window.setTimeout(() => turnPageRef.current(buffered), 0);
      }
    },
    [animateTurn, nudgeBoundary, t],
  );

  useEffect(() => {
    turnPageRef.current = (direction, initialProgress) => {
      void turnPage(direction, initialProgress);
    };
  }, [turnPage]);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    let cancelled = false;
    let rendition: EpubRendition | null = null;
    let book: EpubBook | null = null;

    const onRelocated = (raw: unknown) => {
      relocationResolveRef.current?.();
      const location = raw as EpubLocation;
      const href = location.start?.href ?? "";
      const nextLocator = locatorForEpubHref(href, refsRef.current) || 1;
      const cfi = location.start?.cfi ?? "";
      const displayedStart = Math.max(
        1,
        Number(location.start?.displayed?.page ?? 1),
      );
      const displayedEnd = Math.max(
        displayedStart,
        Number(location.end?.displayed?.page ?? displayedStart),
      );
      const displayedTotal = Math.max(
        displayedEnd,
        Number(
          location.end?.displayed?.total ??
            location.start?.displayed?.total ??
            displayedEnd,
        ),
      );
      const nextPageState = {
        start: displayedStart,
        end: displayedEnd,
        total: displayedTotal,
        atStart: Boolean(location.atStart),
        atEnd: Boolean(location.atEnd),
      };
      pageStateRef.current = nextPageState;
      setPageState(nextPageState);
      const percentage = Math.min(
        1,
        Math.max(
          0,
          Number(
            location.start?.percentage ??
              book?.locations?.percentageFromCfi?.(cfi) ??
              (unitCount > 1 ? (nextLocator - 1) / (unitCount - 1) : 0),
          ),
        ),
      );
      locatorRef.current = nextLocator;
      visibleChangeRef.current?.(nextLocator);
      headingsChangeRef.current?.(
        headingsByLocatorRef.current.get(nextLocator) ?? [],
      );
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
      saveTimerRef.current = setTimeout(() => {
        void saveReadingPosition(materialId, {
          locator: nextLocator,
          source_anchor: cfi,
          percentage,
        }).catch(() => {
          // Reading must continue when a background progress write fails.
        });
      }, 350);
    };

    const onSelected = (rawCfi: unknown, rawContents: unknown) => {
      const cfi = String(rawCfi || "");
      const contents = rawContents as EpubContents;
      const selection = contents.window?.getSelection?.();
      const quote = cleanQuote(selection?.toString() ?? "");
      if (!quote || !cfi) return;
      const rect = selection?.rangeCount
        ? selection.getRangeAt(0).getBoundingClientRect()
        : null;
      onSelection({
        locator:
          locatorForEpubHref(
            (contents.document?.location?.pathname ?? "").replace(/^\//, ""),
            refsRef.current,
          ) || locatorRef.current,
        quote,
        rects: [],
        sourceAnchor: cfi,
        anchor: rect
          ? { x: rect.left + rect.width / 2, y: rect.top }
          : { x: 0, y: 0 },
      });
    };

    const onRenditionKey = (rawEvent: unknown) => {
      const event = rawEvent as KeyboardEvent;
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      if (event.metaKey || event.ctrlKey || event.altKey || event.shiftKey)
        return;
      if (!allowsEpubPageTurn(event.target)) return;
      event.preventDefault();
      void turnPage(event.key === "ArrowLeft" ? "previous" : "next");
    };

    const installContentSafety = (rawContents: unknown) => {
      const contents = rawContents as EpubContents;
      const doc = contents.document;
      if (!doc?.body || doc.body.dataset.dtReaderReady === "true") return;
      doc.body.dataset.dtReaderReady = "true";
      const href = (doc.location?.pathname ?? "").replace(/^\//, "");
      const locator =
        locatorForEpubHref(href, refsRef.current) || locatorRef.current;
      const sourceHref = bookRef.current?.spine.get(locator - 1)?.href || href;
      const headingElements = Array.from(
        doc.querySelectorAll<HTMLElement>("h1,h2,h3,h4,h5,h6"),
      ).filter((element) => (element.textContent ?? "").trim());
      const headings = extractEpubHeadings(
        headingElements,
        locator,
        sourceHref,
      );
      headingElements.forEach((element, index) => {
        element.id = headings[index].id;
      });
      headingsByLocatorRef.current.set(locator, headings);
      if (locator === locatorRef.current) headingsChangeRef.current?.(headings);
      type PointerGesture = {
        pointerId: number;
        startX: number;
        startY: number;
        sampleX: number;
        sampleAt: number;
        direction: EpubPageTurnDirection | null;
        progress: number;
        active: boolean;
      };
      let gesture: PointerGesture | null = null;
      let suppressClickUntil = 0;

      const clearGesture = () => {
        gesture = null;
        doc.documentElement.style.removeProperty("user-select");
        doc.body.style.removeProperty("user-select");
      };
      cancelGestureRef.current = () => {
        clearGesture();
        if (!turningRef.current) {
          setTurnVisual(null);
          setTurnBusy(false);
        }
      };

      doc.addEventListener("pointerdown", (event) => {
        gesture = null;
        if (
          !event.isPrimary ||
          (event.pointerType !== "touch" && event.pointerType !== "pen") ||
          !allowsEpubPageTurn(event.target) ||
          (doc.getSelection?.()?.toString() ?? "").trim()
        )
          return;
        gesture = {
          pointerId: event.pointerId,
          startX: event.clientX,
          startY: event.clientY,
          sampleX: event.clientX,
          sampleAt: event.timeStamp,
          direction: null,
          progress: 0,
          active: false,
        };
        (event.target as Element | null)?.setPointerCapture?.(event.pointerId);
      });

      doc.addEventListener(
        "pointermove",
        (event) => {
          const current = gesture;
          if (!current || event.pointerId !== current.pointerId) return;
          const dx = event.clientX - current.startX;
          const dy = event.clientY - current.startY;
          if (!current.active) {
            if (Math.abs(dy) >= 10 && Math.abs(dy) >= Math.abs(dx) * 1.2) {
              clearGesture();
              return;
            }
            if (!isEpubPageTurnGesture(dx, dy)) return;
            current.active = true;
            current.direction = epubPageTurnDirectionForDelta(
              dx,
              isRtlRef.current,
            );
            setTurnBusy(true);
            doc.documentElement.style.userSelect = "none";
            doc.body.style.userSelect = "none";
          }
          if (!current.direction) return;
          const nextDirection = epubPageTurnDirectionForDelta(
            dx,
            isRtlRef.current,
          );
          if (nextDirection !== current.direction) {
            current.progress = 0;
          } else {
            const hostWidth = hostRef.current?.clientWidth ?? 1;
            const leafWidth =
              epubSpreadModeForWidth(hostWidth) === "double"
                ? hostWidth / 2
                : hostWidth;
            current.progress = epubPageTurnProgress(dx, leafWidth);
          }
          const physical = directionForEpubLayout(
            current.direction,
            isRtlRef.current,
          );
          if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
            setTurnVisual({
              direction: physical,
              phase: "dragging",
              progress: current.progress,
              duration: 0,
            });
          }
          if (event.timeStamp - current.sampleAt >= 24) {
            current.sampleX = event.clientX;
            current.sampleAt = event.timeStamp;
          }
          event.preventDefault();
        },
        { passive: false },
      );

      const finishPointer = (
        event: PointerEvent,
        cancelledByBrowser: boolean,
      ) => {
        const current = gesture;
        if (!current || event.pointerId !== current.pointerId) return;
        const wasActive = current.active;
        const dx = event.clientX - current.startX;
        const sampleElapsed = Math.max(1, event.timeStamp - current.sampleAt);
        const velocityX = (event.clientX - current.sampleX) / sampleElapsed;
        const selection = (doc.getSelection?.()?.toString() ?? "").trim();
        clearGesture();
        if (!wasActive || !current.direction) return;
        suppressClickUntil = performance.now() + 450;
        event.preventDefault();
        const releaseAction = resolveEpubPageTurnRelease({
          cancelled: cancelledByBrowser,
          hasSelection: Boolean(selection),
          directionMatches:
            epubPageTurnDirectionForDelta(dx, isRtlRef.current) ===
            current.direction,
          reducedMotion: window.matchMedia("(prefers-reduced-motion: reduce)")
            .matches,
          progress: current.progress,
          velocityX,
          distanceX: dx,
        });
        if (releaseAction === "commit") {
          void turnPage(current.direction, current.progress);
          return;
        }
        if (releaseAction === "idle") {
          setTurnVisual(null);
          setTurnBusy(false);
          return;
        }
        const physical = directionForEpubLayout(
          current.direction,
          isRtlRef.current,
        );
        void animateTurn(
          { direction: physical, phase: "settling", progress: 0 },
          epubPageTurnSettleDuration(current.progress),
        ).finally(() => {
          if (!turningRef.current) setTurnVisual(null);
          if (!turningRef.current) setTurnBusy(false);
        });
      };
      doc.addEventListener("pointerup", (event) => finishPointer(event, false));
      doc.addEventListener("pointercancel", (event) =>
        finishPointer(event, true),
      );
      doc.addEventListener("click", (event) => {
        const anchor = (event.target as Element | null)?.closest?.("a[href]");
        const href = anchor?.getAttribute("href") ?? "";
        if (/^https?:\/\//i.test(href)) {
          event.preventDefault();
          window.open(href, "_blank", "noopener,noreferrer");
          return;
        }
        if (
          anchor ||
          performance.now() < suppressClickUntil ||
          !allowsEpubPageTurn(event.target) ||
          (doc.getSelection?.()?.toString() ?? "").trim()
        )
          return;
        const frame = contents.window?.frameElement as HTMLElement | null;
        const host = hostRef.current;
        if (!frame || !host) return;
        const x =
          frame.getBoundingClientRect().left +
          (event as MouseEvent).clientX -
          host.getBoundingClientRect().left;
        const direction = epubEdgeTapDirection(
          x,
          host.clientWidth,
          isRtlRef.current,
        );
        if (!direction) return;
        event.preventDefault();
        void turnPage(direction);
      });
    };

    void (async () => {
      try {
        setLoading(true);
        setLoadError("");
        const [module, response, position] = await Promise.all([
          import("epubjs"),
          apiFetch(rawMaterialUrl(materialId), { cache: "no-store" }),
          getReadingPosition(materialId).catch(() => null),
        ]);
        if (!response.ok) throw new Error(t("Could not load this section."));
        const bytes = await response.arrayBuffer();
        if (cancelled) return;
        const createBook = module.default as unknown as (
          input?: ArrayBuffer,
        ) => EpubBook;
        // Calling epubjs with bytes in its constructor swallows open errors and
        // leaves `ready` pending forever. Open explicitly so damaged packages
        // reach the reader's error state instead of an endless skeleton.
        book = createBook();
        bookRef.current = book;
        await book.open(bytes);
        await book.ready;
        if (cancelled) return;
        isRtlRef.current = book.package?.metadata?.direction === "rtl";
        const initialSpread = epubSpreadModeForWidth(host.clientWidth);
        setSpreadMode(initialSpread);
        rendition = book.renderTo(host, {
          width: "100%",
          height: "100%",
          flow: "paginated",
          spread: initialSpread === "double" ? "always" : "none",
          minSpreadWidth: 900,
          allowScriptedContent: false,
        });
        renditionRef.current = rendition;
        rendition.themes.register("deeptutor", {
          html: {
            "font-family":
              "ui-serif, Georgia, 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', serif",
          },
          body: {
            overflow: "hidden",
            "touch-action": "pan-y pinch-zoom",
          },
          img: { "max-width": "100%", "max-height": "100%", height: "auto" },
        });
        rendition.themes.select("deeptutor");
        rendition.on("relocated", onRelocated);
        rendition.on("selected", onSelected);
        rendition.on("keydown", onRenditionKey);
        rendition.hooks.content.register(installContentSafety);
        const fallbackHref =
          book.spine.get((position?.locator ?? 1) - 1)?.href ??
          refsRef.current.find(
            (ref) => ref.locator === (position?.locator ?? 1),
          )?.source_href;
        try {
          await rendition.display(
            position?.source_anchor || fallbackHref || undefined,
          );
        } catch {
          await rendition.display(
            fallbackHref ??
              book.spine.get(0)?.href ??
              refsRef.current[0]?.source_href,
          );
        }
        if (!cancelled) {
          renditionReadyRef.current = true;
          syncRenditionSize();
          setLoading(false);
        }
      } catch (error) {
        if (cancelled) return;
        const message =
          error instanceof Error
            ? error.message
            : t("Could not load this section.");
        setLoadError(message);
        errorRef.current?.(message);
        setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
      if (rendition) {
        rendition.off("relocated", onRelocated);
        rendition.off("selected", onSelected);
        rendition.off("keydown", onRenditionKey);
        rendition.destroy();
      }
      book?.destroy();
      renditionRef.current = null;
      renditionReadyRef.current = false;
      bookRef.current = null;
      turningRef.current = false;
      activeTurnRef.current = null;
      bufferedTurnRef.current = null;
      relocationResolveRef.current?.();
      relocationResolveRef.current = null;
      cancelGestureRef.current?.();
      cancelGestureRef.current = null;
      setTurnVisual(null);
      setTurnBusy(false);
      host.replaceChildren();
    };
  }, [
    animateTurn,
    materialId,
    unitCount,
    onSelection,
    t,
    turnPage,
    syncRenditionSize,
  ]);

  useEffect(() => {
    if (!headingJump || !renditionRef.current || !bookRef.current) return;
    const section = bookRef.current.spine.get(
      (headingJump.locator ?? locatorRef.current) - 1,
    );
    const sourceHref = headingJump.sourceHref || section?.href;
    if (!sourceHref) return;
    void renditionRef.current
      .display(`${sourceHref}#${headingJump.id}`)
      .catch(() => {
        // A damaged publisher anchor leaves the reader on the current page.
      });
  }, [headingJump]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      if (event.metaKey || event.ctrlKey || event.altKey || event.shiftKey)
        return;
      if (!allowsEpubPageTurn(event.target)) return;
      event.preventDefault();
      void turnPage(event.key === "ArrowLeft" ? "previous" : "next");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [turnPage]);

  useEffect(() => {
    const rendition = renditionRef.current;
    const book = bookRef.current;
    if (!rendition || !book) return;
    let cancelled = false;
    for (const anchor of renderedAnchorsRef.current) {
      rendition.annotations.remove(anchor, "highlight");
    }
    renderedAnchorsRef.current = [];
    void (async () => {
      for (const annotation of annotations) {
        let anchor = annotation.source_anchor;
        if (!anchor && annotation.quote) {
          const section = book.spine.get(annotation.locator - 1);
          if (section) {
            try {
              await section.load(book.load.bind(book));
              const matches = section.find(annotation.quote);
              if (matches.length === 1) anchor = matches[0].cfi;
            } catch {
              // An ambiguous legacy quote stays in the list without fake ink.
            }
          }
        }
        if (!anchor || cancelled) continue;
        renderedAnchorsRef.current.push(anchor);
        rendition.annotations.highlight(
          anchor,
          { annotationId: annotation.annotation_id },
          () => annotationClickRef.current?.(annotation),
          `dt-epub-annotation-${annotation.annotation_id}`,
          {
            fill: HIGHLIGHT_COLORS[annotation.color] ?? HIGHLIGHT_COLORS.yellow,
            "fill-opacity":
              annotation.annotation_id === highlightedAnnotationId
                ? "0.8"
                : "0.55",
          },
        );
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [annotations, highlightedAnnotationId, unitRefs]);

  useEffect(() => {
    if (!jump || !renditionRef.current) return;
    const sectionTarget = bookRef.current?.spine.get(jump.locator - 1);
    const ref = unitRefs.find((row) => row.locator === jump.locator);
    const target = sectionTarget?.href ?? ref?.source_href;
    if (!target) return;
    void renditionRef.current.display(target).then(async () => {
      if (!jump.quote || !bookRef.current || !renditionRef.current) return;
      const section = bookRef.current.spine.get(jump.locator - 1);
      if (!section) return;
      try {
        await section.load(bookRef.current.load.bind(bookRef.current));
        const matches = section.find(jump.quote);
        if (matches.length !== 1) return;
        renditionRef.current.annotations.highlight(
          matches[0].cfi,
          {},
          undefined,
          "dt-epub-jump",
          {
            fill: "rgba(99, 102, 241, 0.35)",
          },
        );
        window.setTimeout(() => {
          renditionRef.current?.annotations.remove(matches[0].cfi, "highlight");
        }, 2200);
      } catch {
        // Reaching the requested locator is still useful if quote search fails.
      }
    });
  }, [jump, unitRefs]);

  const pageLabel =
    pageState.start === pageState.end
      ? t("Page {{start}} of {{total}} in this chapter", {
          start: pageState.start,
          total: pageState.total,
        })
      : t("Pages {{start}}–{{end}} of {{total}} in this chapter", {
          start: pageState.start,
          end: pageState.end,
          total: pageState.total,
        });

  const turnParallax = turnVisual
    ? `${
        (turnVisual.direction === "next" ? -1 : 1) *
        Math.sin(Math.PI * turnVisual.progress) *
        4
      }px`
    : "0px";

  return (
    <div className="dt-epub-stage h-full min-h-0 pb-[env(safe-area-inset-bottom)]">
      <div className="dt-epub-book-area">
        <div
          className="dt-epub-book"
          data-spread={spreadMode}
          aria-busy={turnBusy}
        >
          <div
            ref={hostRef}
            className="dt-epub-rendition"
            style={
              {
                "--dt-epub-parallax": turnParallax,
                "--dt-epub-turn-duration": `${turnVisual?.duration ?? 0}ms`,
              } as CSSProperties
            }
            aria-label={t("Immersive reading")}
          />
          {spreadMode === "double" && <div className="dt-epub-spine" />}
          {turnVisual && (
            <div
              className="dt-epub-turn-sheet"
              data-direction={turnVisual.direction}
              data-phase={turnVisual.phase}
              data-spread={spreadMode}
              style={
                {
                  "--dt-epub-turn-progress": turnVisual.progress,
                  "--dt-epub-turn-duration": `${turnVisual.duration}ms`,
                } as CSSProperties
              }
              aria-hidden="true"
            />
          )}
          {loading && (
            <div className="absolute inset-0 z-30 flex items-center justify-center gap-2 bg-[#fffdf8] text-xs text-neutral-500">
              <Loader2 size={15} className="animate-spin" />
              {t("Opening document…")}
            </div>
          )}
          {!loading && loadError && (
            <div
              role="alert"
              className="absolute inset-0 z-30 grid place-items-center bg-[#fffdf8] p-8 text-center text-sm text-[var(--destructive)]"
            >
              {loadError}
            </div>
          )}
        </div>

        {!loadError && (
          <>
            <button
              type="button"
              onClick={() => void turnPage("previous")}
              disabled={pageState.atStart || turnBusy}
              className="dt-epub-turn-button left-1 sm:left-2"
              aria-label={t("Previous")}
            >
              <ChevronLeft size={20} />
            </button>
            <button
              type="button"
              onClick={() => void turnPage("next")}
              disabled={pageState.atEnd || turnBusy}
              className="dt-epub-turn-button right-1 sm:right-2"
              aria-label={t("Next")}
            >
              <ChevronRight size={20} />
            </button>
          </>
        )}
      </div>
      {!loading && !loadError && (
        <div
          className="dt-epub-page-label"
          data-error={turnError ? "true" : undefined}
          aria-live="polite"
        >
          {turnError || pageLabel}
        </div>
      )}
    </div>
  );
}
