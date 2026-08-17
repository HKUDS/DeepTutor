"use client";

import dynamic from "next/dynamic";
import {
  ArrowLeft,
  BookMarked,
  ChevronLeft,
  ChevronRight,
  List,
  Loader2,
  Rows3,
  SquareStack,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { NavItem, Rendition } from "epubjs";
import type { Location } from "epubjs/types/rendition";
import { ReactReaderStyle, type IReactReaderStyle } from "react-reader";

import {
  immersiveReadingApi,
  type ReadingDocument,
  type ReadingProgress,
} from "@/lib/immersive-reading-api";
import {
  epubHrefsMatch,
  epubReaderOptions,
  epubScrollPercent,
  loadEpubLayoutPreference,
  originalDocumentUrl,
  resolveStudySectionId,
  saveEpubLayoutPreference,
  type EpubLayoutMode,
} from "@/lib/epub-reader";

const ReactReader = dynamic(
  () => import("react-reader").then((module) => module.ReactReader),
  { ssr: false, loading: () => null },
);

interface Props {
  document: ReadingDocument;
  progress: ReadingProgress;
  requestedSectionId?: string;
  onBack: () => void;
  onOpenStudy: (sectionId: string) => void;
  onProgress: (progress: ReadingProgress) => void;
}

const readerStyles: IReactReaderStyle = {
  ...ReactReaderStyle,
  readerArea: {
    ...ReactReaderStyle.readerArea,
    backgroundColor: "var(--background)",
  },
  reader: {
    ...ReactReaderStyle.reader,
    top: 8,
    right: 8,
    bottom: 8,
    left: 8,
  },
  titleArea: { display: "none" },
  arrow: { display: "none" },
  arrowHover: { display: "none" },
  tocButton: { display: "none" },
};

function flattenToc(items: NavItem[], depth = 0): Array<NavItem & { depth: number }> {
  const rows: Array<NavItem & { depth: number }> = [];
  for (const item of items) {
    rows.push({ ...item, depth });
    if (item.subitems?.length) {
      rows.push(...flattenToc(item.subitems, depth + 1));
    }
  }
  return rows;
}

function initialReaderPosition(
  doc: ReadingDocument,
  progress: ReadingProgress,
  requestedSectionId?: string,
): { location: string | null; href: string } {
  const requested = doc.sections.find((section) => section.id === requestedSectionId);
  const requestedHref = requested?.source_href || "";
  const savedHref = progress.section_href || "";
  const savedCfi = progress.epub_cfi || "";
  if (requestedHref && savedCfi && (!savedHref || epubHrefsMatch(savedHref, requestedHref))) {
    return { location: savedCfi, href: requestedHref };
  }
  if (requestedHref) {
    return { location: requestedHref, href: requestedHref };
  }
  if (savedCfi) {
    return { location: savedCfi, href: savedHref };
  }
  return { location: null, href: "" };
}

export default function OriginalEpubReader({
  document: doc,
  progress,
  requestedSectionId,
  onBack,
  onOpenStudy,
  onProgress,
}: Props) {
  const { t } = useTranslation();
  const start = initialReaderPosition(doc, progress, requestedSectionId);
  const [layout, setLayout] = useState<EpubLayoutMode>(() => loadEpubLayoutPreference());
  const [location, setLocation] = useState<string | null>(start.location);
  const [toc, setToc] = useState<NavItem[]>([]);
  const [currentHref, setCurrentHref] = useState(start.href);
  const [tocOpen, setTocOpen] = useState(false);
  const [fixedLayout, setFixedLayout] = useState(false);
  const renditionRef = useRef<Rendition | null>(null);
  const saveTimerRef = useRef<number | null>(null);
  const hrefRef = useRef(start.href);

  const persistProgress = useCallback(
    (cfi: string, href: string, scrollPercent: number) => {
      if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current);
      saveTimerRef.current = window.setTimeout(() => {
        void immersiveReadingApi
          .epubProgress(doc.id, {
            epub_cfi: cfi,
            section_href: href,
            scroll_percent: scrollPercent,
          })
          .then((result) => onProgress(result.progress))
          .catch(() => undefined);
      }, 800);
    },
    [doc.id, onProgress],
  );

  useEffect(() => {
    return () => {
      if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current);
    };
  }, []);

  const handleLocationChange = useCallback(
    (next: string) => {
      setLocation(next);
      persistProgress(next, hrefRef.current, 0);
    },
    [persistProgress],
  );

  const handleGetRendition = useCallback((rendition: Rendition) => {
    renditionRef.current = rendition;
    const layoutName = String(
      (rendition.book as { packaging?: { metadata?: { layout?: string } } })?.packaging?.metadata
        ?.layout || "",
    ).toLowerCase();
    if (layoutName.includes("pre-paginated")) {
      setFixedLayout(true);
    }
    rendition.on("relocated", (loc: Location) => {
      const href = loc?.start?.href || "";
      hrefRef.current = href;
      setCurrentHref(href);
      const percent = epubScrollPercent(
        loc?.start?.percentage || 0,
        loc?.start?.displayed?.page,
        loc?.start?.displayed?.total,
      );
      const cfi = loc?.start?.cfi || "";
      if (cfi) persistProgress(cfi, href, percent);
    });
  }, [persistProgress]);

  const changeLayout = useCallback(
    (next: EpubLayoutMode) => {
      if (next === layout) return;
      setLayout(next);
      saveEpubLayoutPreference(next);
    },
    [layout],
  );

  const activeHref = currentHref || progress.section_href || "";
  const tocRows = useMemo(() => flattenToc(toc), [toc]);
  const readerOptions = epubReaderOptions(fixedLayout ? "paginated" : layout);

  const goStudy = () => {
    const sectionId = resolveStudySectionId(
      doc.sections,
      activeHref,
      requestedSectionId || progress.current_section_id,
    );
    onOpenStudy(sectionId);
  };

  return (
    <div className="relative flex h-full min-w-0 bg-[var(--background)]">
      <aside
        className={`${
          tocOpen ? "flex" : "hidden"
        } absolute inset-y-0 left-0 z-30 w-[min(86vw,286px)] flex-col border-r border-[var(--border)] bg-[var(--card)] shadow-xl md:static md:z-0 md:flex md:w-[286px] md:shadow-none`}
      >
        <div className="border-b border-[var(--border)] p-4">
          <button
            type="button"
            onClick={onBack}
            className="mb-4 inline-flex items-center gap-2 text-xs text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
          >
            <ArrowLeft size={14} /> {t("Back to library")}
          </button>
          <h1 className="line-clamp-3 text-sm font-semibold leading-snug">{doc.title}</h1>
          <p className="mt-1 truncate text-[11px] text-[var(--muted-foreground)]">
            {doc.author || doc.source_filename}
          </p>
        </div>
        <div className="flex items-center justify-between px-4 pb-2 pt-4">
          <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-[var(--muted-foreground)]">
            {t("Contents")}
          </span>
         <button
           type="button"
           className="rounded-lg p-2 text-[var(--muted-foreground)] md:hidden"
           onClick={() => setTocOpen(false)}
           aria-label={t("Close")}
         >
           <X size={20} />
         </button>
       </div>
        <nav className="min-h-0 flex-1 overflow-y-auto px-2 pb-4">
          {tocRows.map((item) => {
            const active = epubHrefsMatch(item.href, activeHref);
            return (
              <button
                key={`${item.id || item.href}-${item.depth}`}
                type="button"
                onClick={() => {
                  renditionRef.current?.display(item.href);
                  setTocOpen(false);
                }}
                className={`mb-1 block w-full rounded-xl px-3 py-2 text-left text-xs leading-5 transition ${
                  active
                    ? "bg-[var(--primary)]/12 text-[var(--foreground)]"
                    : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]/60 hover:text-[var(--foreground)]"
                }`}
                style={{ paddingLeft: 12 + item.depth * 12 }}
              >
                {item.label.trim() || item.href}
              </button>
            );
          })}
        </nav>
      </aside>
     {tocOpen && (
       <button
         type="button"
         className="absolute inset-0 z-20 bg-black/40 md:hidden"
         onClick={() => setTocOpen(false)}
         aria-label={t("Close")}
       />
     )}

     <section className="flex min-w-0 flex-1 flex-col">
       <header className="relative z-[31] flex h-[68px] shrink-0 items-center gap-2 border-b border-[var(--border)] bg-[var(--background)]/92 px-3 backdrop-blur-xl md:px-5">
          <button
            type="button"
            onClick={() => setTocOpen((open) => !open)}
            className="inline-flex h-10 w-10 items-center justify-center rounded-xl border border-[var(--border)] text-[var(--muted-foreground)] md:hidden"
            aria-label={t("Contents")}
          >
            <List size={16} />
          </button>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">{doc.title}</p>
            <p className="truncate text-[11px] text-[var(--muted-foreground)]">
              {t("Original reading")}
            </p>
          </div>
          <div className="flex shrink-0 rounded-xl border border-[var(--border)] bg-[var(--card)] p-1">
            <button
              type="button"
              onClick={() => changeLayout("paginated")}
              className={`inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs ${
                readerOptions.flow === "paginated"
                  ? "bg-[var(--foreground)] text-[var(--background)]"
                  : "text-[var(--muted-foreground)]"
              }`}
            >
              <SquareStack size={13} /> {t("Paginated")}
            </button>
            <button
              type="button"
              disabled={fixedLayout}
              title={fixedLayout ? t("Fixed layout") : undefined}
              onClick={() => changeLayout("scrolled")}
              className={`inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs disabled:opacity-35 ${
                readerOptions.flow === "scrolled"
                  ? "bg-[var(--foreground)] text-[var(--background)]"
                  : "text-[var(--muted-foreground)]"
              }`}
            >
              <Rows3 size={13} /> {t("Scrolled")}
            </button>
          </div>
          <button
            type="button"
            onClick={goStudy}
            className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--border)] px-3 py-2 text-xs font-medium text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
          >
            <BookMarked size={15} /> {t("Study view")}
          </button>
        </header>

       <div className={`relative min-h-0 flex-1${tocOpen ? " pointer-events-none md:pointer-events-auto" : ""}`}>
          <ReactReader
            key={`${doc.id}:${readerOptions.manager}:${readerOptions.flow}`}
            url={originalDocumentUrl(doc.id)}
            location={location}
            locationChanged={handleLocationChange}
            tocChanged={setToc}
            getRendition={handleGetRendition}
            showToc={false}
            readerStyles={readerStyles}
            epubInitOptions={{ openAs: "epub" }}
            epubOptions={{
              allowPopups: false,
              allowScriptedContent: false,
              manager: readerOptions.manager,
              flow: readerOptions.flow,
            }}
            loadingView={
              <div className="flex h-full items-center justify-center gap-2 text-sm text-[var(--muted-foreground)]">
                <Loader2 size={16} className="animate-spin" /> {t("Loading the book…")}
              </div>
            }
            errorView={
              <div className="flex h-full items-center justify-center px-6 text-center text-sm text-red-500">
                {t("Could not open this EPUB.")}
              </div>
            }
          />
          <button
            type="button"
            onClick={() => renditionRef.current?.prev()}
            className="absolute bottom-5 left-3 z-10 flex h-11 w-11 items-center justify-center rounded-full border border-[var(--border)] bg-[var(--card)] text-[var(--foreground)] shadow-sm"
            aria-label={t("Previous page")}
          >
            <ChevronLeft size={20} />
          </button>
          <button
            type="button"
            onClick={() => renditionRef.current?.next()}
            className="absolute bottom-5 right-3 z-10 flex h-11 w-11 items-center justify-center rounded-full border border-[var(--border)] bg-[var(--card)] text-[var(--foreground)] shadow-sm"
            aria-label={t("Next page")}
          >
            <ChevronRight size={20} />
          </button>
        </div>
      </section>
    </div>
  );
}
