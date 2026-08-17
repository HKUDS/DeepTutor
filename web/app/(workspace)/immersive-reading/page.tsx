"use client";

import dynamic from "next/dynamic";
import Image from "next/image";
import { useRouter, useSearchParams } from "next/navigation";
import {
  ArrowLeft,
  BookCheck,
  BookMarked,
  BookOpen,
  BookPlus,
  Check,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  Download,
  FileSpreadsheet,
  FileSearch,
  Layers,
  Languages,
  Library,
  Loader2,
  MessageCircleQuestion,
  MoreHorizontal,
  Plus,
  Network,
  Quote,
  RotateCcw,
  Search,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import {
  Suspense,
  type CSSProperties,
  type MouseEvent as ReactMouseEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import { getCachedTranslation, setCachedTranslation } from "@/lib/dictionary-cache";

import {
  ApiRequestError,
  immersiveReadingApi,
  type DictionaryResult,
  type FocusAttemptRecord,
  type FocusCheckResult,
  type ReadingCapabilities,
  type ReadingCitation,
  type ReadingDocument,
  type ReadingProgress,
  type SearchHit,
  type SearchResponse,
  type VocabEntry,
  bilingualApi,
  type BilingualPairing,
} from "@/lib/immersive-reading-api";
import { defaultReadingView, immersiveReadingPath } from "@/lib/epub-reader";
import DictionaryPanel from "@/components/common/DictionaryPanel";

const MarkdownRenderer = dynamic(
  () => import("@/components/common/MarkdownRenderer"),
  { ssr: false },
);
const Mermaid = dynamic(() => import("@/components/Mermaid"), { ssr: false });
const OriginalEpubReader = dynamic(() => import("./components/OriginalEpubReader"), { ssr: false, loading: () => null });
const BilingualReader = dynamic(
  () => import("@/components/immersive-reading/BilingualReader").then((module) => module.BilingualReader),
  { ssr: false, loading: () => null },
);
const BilingualPairDialog = dynamic(
  () => import("@/components/immersive-reading/BilingualPairDialog").then((module) => module.BilingualPairDialog),
  { ssr: false },
);

type SearchMode = "exact" | "fuzzy" | "description_fast" | "description_fine";
type ShelfView = "library" | "citations" | "focus-history" | "vocabulary";
type SelectionAction = "translate" | "query";
type CharacterScope = "current" | "through_current";

interface SelectionMenuState {
  text: string;
  left: number;
  top: number;
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat().format(value || 0);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function FocusHistoryPanel({ history }: { history: FocusAttemptRecord[] }) {
  const { t } = useTranslation();
  if (history.length === 0) return null;
  return (
    <details className="mt-5 rounded-xl border border-[var(--border)] bg-[var(--background)] p-4 text-left text-sm">
      <summary className="cursor-pointer font-medium">{t("Attempt history ({{count}})", { count: history.length })}</summary>
      <div className="mt-3 max-h-56 space-y-3 overflow-y-auto">
        {[...history].reverse().map((attempt) => (
          <div key={attempt.id} className="rounded-lg bg-[var(--muted)]/45 p-3">
            <div className="flex justify-between gap-3 text-xs text-[var(--muted-foreground)]">
              <span>{t("Attempt {{number}}", { number: attempt.attempt_number })}</span>
              <span>{attempt.score == null ? t("Not graded") : `${attempt.score}/100`}</span>
            </div>
            {(attempt.model || attempt.prompt_version) && (
              <p className="mt-1 text-[11px] text-[var(--muted-foreground)]">
                {[attempt.model, attempt.prompt_version].filter(Boolean).join(" · ")}
              </p>
            )}
            {attempt.answer_recorded ? (
              <>
                <p className="mt-2 whitespace-pre-wrap"><span className="font-medium">{t("Main content")}:</span> {attempt.summary}</p>
                <p className="mt-2 whitespace-pre-wrap"><span className="font-medium">{t("Additional notes")}:</span> {attempt.reflection}</p>
              </>
            ) : <p className="mt-2 text-[var(--muted-foreground)]">{t("Answer text was not stored by the previous version.")}</p>}
            {attempt.feedback && <p className="mt-2 text-[var(--muted-foreground)]">{attempt.feedback}</p>}
            {attempt.error && <p className="mt-2 text-red-500">{attempt.error}</p>}
          </div>
        ))}
      </div>
    </details>
  );
}

async function runDescriptionSearchJob(
  documentId: string,
  query: string,
  mode: "description_fast" | "description_fine",
): Promise<SearchResponse> {
  const started = await immersiveReadingApi.startSearchJob(documentId, query, mode);
  const deadline = Date.now() + 10 * 60 * 1000;
  while (Date.now() < deadline) {
    await new Promise((resolve) => window.setTimeout(resolve, 750));
    const { job } = await immersiveReadingApi.searchJobStatus(documentId, started.job.id);
    if (job.status === "completed") {
      if (!job.result) throw new Error("Search completed without a result.");
      return job.result;
    }
    if (job.status === "failed") {
      throw new Error(job.error || "Description search failed.");
    }
  }
  throw new Error("Description search timed out. Please try again.");
}

function BookCover({ document, compact = false }: { document: ReadingDocument; compact?: boolean }) {
  const initials = document.title.trim().slice(0, 2).toUpperCase() || "IR";
  return (
    <div
      className={`relative overflow-hidden rounded-[10px] border border-black/10 bg-gradient-to-br from-[#cf7956] via-[#9a4d43] to-[#342335] shadow-[0_18px_45px_rgba(0,0,0,0.22)] ${
        compact ? "h-28 w-20" : "aspect-[2/3] w-full"
      }`}
    >
      {document.cover_url ? (
        <Image
          src={document.cover_url}
          alt={document.title}
          fill
          sizes={compact ? "80px" : "320px"}
          unoptimized
          className="object-cover"
        />
      ) : (
        <div className="absolute inset-0 flex flex-col justify-between p-5 text-white">
          <BookMarked size={compact ? 18 : 28} strokeWidth={1.5} className="opacity-80" />
          <div>
            <div className={`${compact ? "text-xl" : "text-4xl"} font-serif tracking-tight`}>{initials}</div>
            {!compact && <div className="mt-2 line-clamp-3 text-xs font-medium leading-relaxed text-white/85">{document.title}</div>}
          </div>
        </div>
      )}
    </div>
  );
}

function ProgressBar({ value }: { value: number }) {
  return (
    <div className="h-1.5 overflow-hidden rounded-full bg-[var(--muted)]">
      <div
        className="h-full rounded-full bg-[var(--primary)] transition-[width] duration-500"
        style={{ width: `${Math.max(0, Math.min(100, value))}%` }}
      />
    </div>
  );
}

function ModalShell({ children, onClose, labelledBy }: { children: React.ReactNode; onClose: () => void; labelledBy: string }) {
  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/55 p-5 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby={labelledBy}
      onMouseDown={(event) => {
        if (event.currentTarget === event.target) onClose();
      }}
    >
      {children}
    </div>
  );
}

function ErrorNotification({
  message,
  closeLabel,
  onClose,
}: {
  message: string;
  closeLabel: string;
  onClose: () => void;
}) {
  return (
    <div
      role="alert"
      className="fixed right-6 top-6 z-[140] flex max-w-md items-start gap-3 rounded-2xl border border-red-500/35 bg-[#2a1717] px-4 py-3.5 text-sm leading-6 text-red-100 shadow-2xl"
    >
      <CircleAlert size={18} className="mt-0.5 shrink-0 text-red-400" />
      <span className="min-w-0 flex-1">{message}</span>
      <button
        type="button"
        aria-label={closeLabel}
        onClick={onClose}
        className="mt-0.5 shrink-0 rounded-md p-0.5 text-red-200/75 transition hover:bg-white/10 hover:text-red-100"
      >
        <X size={15} />
      </button>
    </div>
  );
}

function ImmersiveReadingContent() {
  const { t } = useTranslation();
  const router = useRouter();
  const searchParams = useSearchParams();
  const documentId = searchParams.get("book");
  const pairingId = searchParams.get("pairing");
  const pairingChapterId = searchParams.get("chapter");
  const pairingGroupIndex = Number(searchParams.get("group"));
  const [documents, setDocuments] = useState<ReadingDocument[]>([]);
  const [capabilities, setCapabilities] = useState<ReadingCapabilities | null>(null);
 const [citations, setCitations] = useState<ReadingCitation[]>([]);
  const [shelfView, setShelfView] = useState<ShelfView>("library");
  const [vocabulary, setVocabulary] = useState<VocabEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [errorToast, setErrorToast] = useState<{ id: number; message: string } | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [pairings, setPairings] = useState<BilingualPairing[]>([]);
  const [showPairDialog, setShowPairDialog] = useState(false);

  const refreshLibrary = useCallback(async () => {
    const data = await immersiveReadingApi.list();
    setDocuments(data.documents || []);
  }, []);

 const refreshPairings = useCallback(async () => {
   try {
     const data = await bilingualApi.list();
     setPairings(data.pairings || []);
   } catch { /* pairings endpoint may not exist yet */ }
 }, []);

  const handleDeletePairing = useCallback(
    async (pairing: BilingualPairing, event: ReactMouseEvent) => {
      event.stopPropagation();
      if (!window.confirm(t("Delete this bilingual pairing?"))) return;
      try {
        await bilingualApi.delete(pairing.pairing_id);
        await refreshPairings();
      } catch (cause) {
        setError(errorMessage(cause));
      }
    },
    [refreshPairings, setError, t],
  );

 const refreshCitations = useCallback(async () => {
   const data = await immersiveReadingApi.citations();
   setCitations(data.citations || []);
 }, []);

  const refreshVocabulary = useCallback(async () => {
    const data = await immersiveReadingApi.vocabulary();
    setVocabulary(data.entries || []);
  }, []);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
   Promise.all([
     immersiveReadingApi.list(),
     immersiveReadingApi.capabilities().catch(() => null),
     immersiveReadingApi.citations(),
      immersiveReadingApi.vocabulary(),
     bilingualApi.list().catch(() => ({ pairings: [] })),
   ])
      .then(([library, caps, saved, vocab, bilData]) => {
       if (!mounted) return;
       setDocuments(library.documents || []);
       setCapabilities(caps);
       setCitations(saved.citations || []);
        setVocabulary(vocab.entries || []);
       setPairings(bilData.pairings || []);
     })
      .catch((cause) => mounted && setError(errorMessage(cause)))
      .finally(() => mounted && setLoading(false));
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    void refreshPairings();
  }, [refreshPairings]);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 3200);
    return () => window.clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    if (!errorToast) return;
    const timer = window.setTimeout(() => setErrorToast(null), 3000);
    return () => window.clearTimeout(timer);
  }, [errorToast]);

  useEffect(() => {
    const indexing = documents.some((document) =>
      ["not_started", "building", "stale"].includes(document.fast_search_index?.status),
    );
    if (!indexing) return;
    const timer = window.setInterval(() => {
      void refreshLibrary().catch(() => undefined);
    }, 2500);
    return () => window.clearInterval(timer);
  }, [documents, refreshLibrary]);

  const handleImport = async (files: FileList | null) => {
    const file = files?.[0];
    if (!file) return;
    setImporting(true);
    setError(null);
    try {
      const result = await immersiveReadingApi.import(file);
      await refreshLibrary();
      router.push(`/immersive-reading?book=${encodeURIComponent(result.document.id)}`);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setImporting(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleDeleteDocument = async (document: ReadingDocument, event: ReactMouseEvent) => {
    event.stopPropagation();
    if (!window.confirm(t("Delete this reading book and its progress?"))) return;
    try {
      await immersiveReadingApi.delete(document.id);
      await Promise.all([refreshLibrary(), refreshCitations()]);
    } catch (cause) {
      setError(errorMessage(cause));
    }
  };

  if (pairingId) {
    return (
      <>
        <BilingualReader
          pairingId={pairingId}
          initialChapterId={pairingChapterId || undefined}
          initialGroupIndex={Number.isFinite(pairingGroupIndex) ? Math.max(0, pairingGroupIndex) : 0}
          onVocabularyAdded={() => void refreshVocabulary()}
          onToast={setToast}
          onErrorToast={(message) => setErrorToast({ id: Date.now(), message })}
          onBack={() => {
            router.push("/immersive-reading");
            void refreshPairings();
          }}
        />
        {toast && (
          <div className="fixed bottom-6 left-1/2 z-[120] -translate-x-1/2 rounded-xl bg-[var(--foreground)] px-4 py-2.5 text-sm text-[var(--background)] shadow-xl">
            {toast}
          </div>
        )}
        {errorToast && (
          <ErrorNotification
            message={errorToast.message}
            closeLabel={t("Dismiss error notification")}
            onClose={() => setErrorToast(null)}
          />
        )}
      </>
    );
  }

  if (documentId) {
    return (
      <>
        <Reader
          documentId={documentId}
          capabilities={capabilities}
          onBack={() => {
            router.push("/immersive-reading");
            void refreshLibrary();
          }}
         onCitationAdded={() => void refreshCitations()}
          onVocabularyAdded={() => void refreshVocabulary()}
         onToast={setToast}
          onErrorToast={(message) => setErrorToast({ id: Date.now(), message })}
        />
        {toast && <div className="fixed bottom-6 left-1/2 z-[120] -translate-x-1/2 rounded-xl bg-[var(--foreground)] px-4 py-2.5 text-sm text-[var(--background)] shadow-xl">{toast}</div>}
        {errorToast && (
          <ErrorNotification
            message={errorToast.message}
            closeLabel={t("Dismiss error notification")}
            onClose={() => setErrorToast(null)}
          />
        )}
      </>
    );
  }

  return (
    <div className="relative h-full overflow-y-auto bg-[var(--background)]">
      <header className="sticky top-0 z-20 flex items-center justify-between border-b border-[var(--border)] bg-[var(--background)]/92 px-8 py-5 backdrop-blur-xl">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[var(--primary)]/12 text-[var(--primary)]">
            <BookMarked size={21} />
          </div>
          <div>
            <h1 className="text-xl font-semibold text-[var(--foreground)]">{t("Immersive Reading")}</h1>
            <p className="text-sm text-[var(--muted-foreground)]">{t("Read closely, remember deeply, and keep the passages that matter.")}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setShowPairDialog(true)}
            className="inline-flex items-center gap-2 rounded-xl border border-[var(--border)] bg-[var(--card)] px-4 py-2.5 text-sm font-medium text-[var(--foreground)] shadow-sm transition hover:bg-[var(--muted)]"
          >
            <Languages size={17} />
            {t("Pair Bilingual")}
          </button>
          <button
            type="button"
            disabled={importing}
            onClick={() => fileInputRef.current?.click()}
            className="inline-flex items-center gap-2 rounded-xl bg-[var(--primary)] px-4 py-2.5 text-sm font-medium text-[var(--primary-foreground)] shadow-sm transition hover:brightness-105 disabled:opacity-60"
          >
            {importing ? <Loader2 size={16} className="animate-spin" /> : <Plus size={17} />}
            {importing ? t("Importing…") : t("Import book")}
          </button>
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept=".txt,.text,.md,.markdown,.pdf,.epub,.mobi,.fb2,.xps"
          className="hidden"
          onChange={(event) => void handleImport(event.target.files)}
        />
      </header>

      <main className="mx-auto w-full max-w-[1500px] px-8 py-7">
        <div className="mb-7 flex items-center gap-1 rounded-xl border border-[var(--border)] bg-[var(--card)] p-1.5 w-fit">
          {(["library", "citations", "vocabulary", "focus-history"] as const).map((view) => {
            const attemptCount = documents.reduce(
              (total, document) => total + Object.values(document.progress.focus_history || {}).reduce(
                (subtotal, records) => subtotal + records.length,
                0,
              ),
              0,
            );
            return (
            <button
              key={view}
              type="button"
              onClick={() => setShelfView(view)}
              className={`inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm transition ${
                shelfView === view
                  ? "bg-[var(--foreground)] text-[var(--background)]"
                  : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
              }`}
            >
              {view === "library"
                ? <Library size={15} />
                : view === "citations"
                  ? <Quote size={15} />
                  : view === "vocabulary"
                    ? <BookMarked size={15} />
                    : <BookCheck size={15} />}
              {view === "library" ? t("Library") : view === "citations" ? t("Citations") : view === "vocabulary" ? t("Vocabulary") : t("Answer history")}
             {view === "citations" && citations.length > 0 && (
               <span className="rounded-full bg-current/10 px-1.5 text-[10px]">{citations.length}</span>
             )}
              {view === "vocabulary" && vocabulary.length > 0 && (
                <span className="rounded-full bg-current/10 px-1.5 text-[10px]">{vocabulary.length}</span>
              )}
             {view === "focus-history" && attemptCount > 0 && (
                <span className="rounded-full bg-current/10 px-1.5 text-[10px]">{attemptCount}</span>
              )}
            </button>
          );})}
        </div>

        {error && (
          <div className="mb-6 flex items-start gap-3 rounded-xl border border-red-500/25 bg-red-500/8 px-4 py-3 text-sm text-red-500">
            <CircleAlert size={17} className="mt-0.5 shrink-0" />
            <span className="flex-1">{error}</span>
            <button type="button" onClick={() => setError(null)}><X size={15} /></button>
          </div>
        )}

        {loading ? (
          <div className="flex min-h-[420px] items-center justify-center text-[var(--muted-foreground)]">
            <Loader2 className="animate-spin" />
          </div>
        ) : shelfView === "citations" ? (
          <CitationsView
            citations={citations}
            onOpen={(citation) => router.push(`/immersive-reading?book=${encodeURIComponent(citation.document_id)}&section=${encodeURIComponent(citation.section_id)}`)}
            onDelete={async (citation) => {
              await immersiveReadingApi.deleteCitation(citation.id);
              await refreshCitations();
           }}
          />
        ) : shelfView === "vocabulary" ? (
          <VocabularyView
            entries={vocabulary}
            documents={documents}
            onOpen={(entry) => {
              if (entry.pairing_id) {
                const params = new URLSearchParams({ pairing: entry.pairing_id });
                if (entry.chapter_id) params.set("chapter", entry.chapter_id);
                if (entry.group_index) params.set("group", String(entry.group_index));
                router.push(`/immersive-reading?${params.toString()}`);
                return;
              }
              if (entry.document_id) {
                router.push(`/immersive-reading?book=${encodeURIComponent(entry.document_id)}`);
              }
            }}
            onDelete={async (entry) => {
              await immersiveReadingApi.deleteWord(entry.id);
              await refreshVocabulary();
            }}
          />
        ) : shelfView === "focus-history" ? (
          <FocusHistoryView
            documents={documents}
            onOpen={(bookId, sectionId) => router.push(`/immersive-reading?book=${encodeURIComponent(bookId)}&section=${encodeURIComponent(sectionId)}`)}
          />
        ) : documents.length === 0 ? (
          <div className="flex min-h-[500px] flex-col items-center justify-center rounded-3xl border border-dashed border-[var(--border)] bg-[var(--card)]/35 px-6 text-center">
            <div className="mb-5 flex h-16 w-16 items-center justify-center rounded-2xl bg-[var(--primary)]/10 text-[var(--primary)]">
              <BookMarked size={30} strokeWidth={1.5} />
            </div>
            <h2 className="text-xl font-semibold">{t("No reading books yet")}</h2>
            <p className="mt-2 max-w-md text-sm leading-relaxed text-[var(--muted-foreground)]">
              {t("Import a TXT, PDF, EPUB or another supported ebook. The original text stays intact while DeepTutor tracks your close reading.")}
            </p>
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="mt-6 inline-flex items-center gap-2 rounded-xl bg-[var(--primary)] px-4 py-2.5 text-sm font-medium text-[var(--primary-foreground)]"
            >
              <Plus size={17} /> {t("Import your first book")}
            </button>
          </div>
        ) : (
          <div className={`grid gap-x-10 gap-y-12 ${documents.length <= 3 ? "grid-cols-1 sm:grid-cols-2 max-w-4xl mx-auto" : documents.length <= 6 ? "grid-cols-2 sm:grid-cols-3 lg:grid-cols-3 xl:grid-cols-4" : "grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5"}`}>
            {documents.map((document) => (
              <article
                key={document.id}
                role="button"
                tabIndex={0}
                onClick={() => router.push(`/immersive-reading?book=${encodeURIComponent(document.id)}`)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") router.push(`/immersive-reading?book=${encodeURIComponent(document.id)}`);
                }}
                className="group cursor-pointer outline-none"
              >
                <div className="relative mx-auto max-w-[360px]">
                  <BookCover document={document} />
                  <button
                    type="button"
                    aria-label={t("Delete")}
                    onClick={(event) => void handleDeleteDocument(document, event)}
                    className="absolute right-2 top-2 flex h-8 w-8 items-center justify-center rounded-lg bg-black/65 text-white opacity-0 backdrop-blur transition hover:bg-red-600 group-hover:opacity-100 group-focus-within:opacity-100"
                  >
                    <Trash2 size={15} />
                  </button>
                </div>
                <div className="mx-auto mt-4 max-w-[360px]">
                  <h2 className="line-clamp-2 text-[15px] font-semibold leading-snug text-[var(--foreground)]">{document.title}</h2>
                  <p className="mt-1 truncate text-xs text-[var(--muted-foreground)]">
                    {document.author || document.source_filename}
                  </p>
                  <div className="mt-3"><ProgressBar value={document.progress_percent} /></div>
                  <div className="mt-1.5 flex justify-between text-[11px] text-[var(--muted-foreground)]">
                    <span>{Math.round(document.progress_percent)}%</span>
                    <span>{document.sections.length} {t("sections")}</span>
                  </div>
                  <div className="mt-2 flex items-center gap-1.5 text-[10px] text-[var(--muted-foreground)]">
                    {document.fast_search_index.status === "building" || document.fast_search_index.status === "not_started" || document.fast_search_index.status === "stale" ? (
                      <Loader2 size={11} className="animate-spin text-[var(--primary)]" />
                    ) : document.fast_search_index.status === "ready" ? (
                      <Check size={11} className="text-emerald-500" />
                    ) : (
                      <CircleAlert size={11} className="text-amber-500" />
                    )}
                    <span>
                      {document.fast_search_index.status === "ready"
                        ? t("Fast search index ready")
                        : document.fast_search_index.status === "failed" || document.fast_search_index.status === "partial"
                          ? t("Fast search index needs attention")
                          : t("Building fast search index: {{completed}}/{{total}}", {
                              completed: document.fast_search_index.completed_sections,
                              total: document.fast_search_index.total_sections,
                            })}
                    </span>
                  </div>
                </div>
              </article>
            ))}
          </div>
        )}

        {capabilities && shelfView === "library" && documents.length > 0 && (
          <p className="mt-12 text-center text-xs text-[var(--muted-foreground)]">
            {capabilities.description_search_enabled
              ? t("Description matching is available with {{model}} ({{count}}k context).", { model: capabilities.model, count: Math.round(capabilities.context_window / 1000) })
              : t("Description matching needs a default model with at least 50k context; exact and fuzzy search still work.")}
          </p>
        )}
        {pairings.length > 0 && shelfView === "library" && (
          <section className="mt-12">
            <h2 className="mb-4 flex items-center gap-2 text-lg font-semibold">
              <Languages size={20} className="text-[var(--primary)]" />
              {t("Bilingual Pairings")}
            </h2>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {pairings.map((pairing) => (
                <div
                  key={pairing.pairing_id}
                  role="button"
                  tabIndex={0}
                  onClick={() => router.push(`/immersive-reading?pairing=${encodeURIComponent(pairing.pairing_id)}`)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      router.push(`/immersive-reading?pairing=${encodeURIComponent(pairing.pairing_id)}`);
                    }
                  }}
                  className="group relative flex cursor-pointer items-center gap-3 rounded-xl border border-[var(--border)] bg-[var(--card)] p-4 text-left transition hover:border-[var(--primary)]/30 hover:shadow-md"
                >
                  <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-lg bg-[var(--primary)]/10 text-[var(--primary)]">
                    <Languages size={22} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-semibold">{pairing.en_title}</p>
                    <p className="truncate text-xs text-[var(--muted-foreground)]">{pairing.zh_title}</p>
                    <div className="mt-1 flex items-center gap-2 text-[11px] text-[var(--muted-foreground)]">
                      <span>{pairing.chapter_count} {t("chapters")}</span>
                      {pairing.aligned ? (
                        <span className="flex items-center gap-0.5 text-emerald-500">
                          <Check size={11} /> {t("aligned")}
                        </span>
                      ) : (
                        <span className="text-amber-500">{t("not aligned")}</span>
                      )}
                    </div>
                  </div>
                  <button
                    type="button"
                    aria-label={t("Delete")}
                    onClick={(event) => void handleDeletePairing(pairing, event)}
                    className="absolute right-1.5 top-1.5 rounded-lg p-1.5 text-[var(--muted-foreground)] opacity-0 transition hover:bg-red-500/10 hover:text-red-500 group-hover:opacity-100"
                  >
                    <Trash2 size={15} />
                  </button>
                  <ChevronRight size={16} className="shrink-0 text-[var(--muted-foreground)] group-hover:text-[var(--foreground)]" />
                </div>
              ))}
            </div>
          </section>
        )}
      </main>

      {showPairDialog && (
        <BilingualPairDialog
          isOpen={showPairDialog}
          onClose={() => setShowPairDialog(false)}
          onPaired={() => void refreshPairings()}
        />
      )}

      {toast && <div className="fixed bottom-6 left-1/2 z-[120] -translate-x-1/2 rounded-xl bg-[var(--foreground)] px-4 py-2.5 text-sm text-[var(--background)] shadow-xl">{toast}</div>}
      {errorToast && (
        <ErrorNotification
          message={errorToast.message}
          closeLabel={t("Dismiss error notification")}
          onClose={() => setErrorToast(null)}
        />
      )}
    </div>
  );
}

export default function ImmersiveReadingPage() {
  return (
    <Suspense
      fallback={(
        <div className="flex min-h-[60vh] items-center justify-center text-[var(--muted-foreground)]">
          <Loader2 size={22} className="animate-spin" />
        </div>
      )}
    >
      <ImmersiveReadingContent />
    </Suspense>
  );
}

function CitationsView({
  citations,
  onOpen,
  onDelete,
}: {
  citations: ReadingCitation[];
  onOpen: (citation: ReadingCitation) => void;
  onDelete: (citation: ReadingCitation) => Promise<void>;
}) {
  const { t } = useTranslation();
  if (!citations.length) {
    return (
      <div className="flex min-h-[420px] flex-col items-center justify-center rounded-3xl border border-dashed border-[var(--border)] text-center">
        <Quote size={34} className="mb-4 text-[var(--muted-foreground)]" />
        <h2 className="font-semibold">{t("No citations yet")}</h2>
        <p className="mt-2 max-w-md text-sm text-[var(--muted-foreground)]">{t("Select a meaningful passage while reading and choose Record.")}</p>
      </div>
    );
  }
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {citations.map((citation) => (
        <article key={citation.id} className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 shadow-sm">
          <div className="mb-3 flex items-start justify-between gap-4">
            <button type="button" onClick={() => onOpen(citation)} className="min-w-0 text-left">
              <div className="truncate text-sm font-semibold text-[var(--foreground)]">{citation.document_title}</div>
              <div className="mt-0.5 truncate text-xs text-[var(--muted-foreground)]">{citation.section_title}</div>
            </button>
            <button type="button" aria-label={t("Delete")} onClick={() => void onDelete(citation)} className="rounded-lg p-2 text-[var(--muted-foreground)] hover:bg-red-500/10 hover:text-red-500">
              <Trash2 size={15} />
            </button>
          </div>
          <blockquote className="border-l-2 border-[var(--primary)] pl-4 font-serif text-[15px] leading-7 text-[var(--foreground)]/90">{citation.quote}</blockquote>
          {citation.note && <p className="mt-3 text-sm text-[var(--muted-foreground)]">{citation.note}</p>}
        </article>
      ))}
    </div>
  );
}

function VocabularyView({
  entries,
  documents,
  onOpen,
  onDelete,
}: {
  entries: VocabEntry[];
  documents: ReadingDocument[];
  onOpen: (entry: VocabEntry) => void;
  onDelete: (entry: VocabEntry) => Promise<void>;
}) {
  const { t } = useTranslation();
  const [filterBook, setFilterBook] = useState<string>("all");
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const bookOptions = documents.filter((d) => entries.some((e) => e.document_id === d.id));
  const filtered = filterBook === "all" ? entries : entries.filter((e) => e.document_id === filterBook);

  if (!entries.length) {
    return (
      <div className="flex min-h-[420px] flex-col items-center justify-center rounded-3xl border border-dashed border-[var(--border)] text-center">
        <BookMarked size={34} className="mb-4 text-[var(--muted-foreground)]" />
        <h2 className="font-semibold">{t("No vocabulary yet")}</h2>
        <p className="mt-2 max-w-md text-sm text-[var(--muted-foreground)]">{t("Select a word while reading and choose Vocab to save it here.")}</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-xs text-[var(--muted-foreground)]">{t("{{count}} words", { count: entries.length })}</span>
        <a
          href={immersiveReadingApi.vocabularyExportUrl("csv")}
          download="deeptutor-vocabulary.csv"
          className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs font-medium text-[var(--foreground)] transition hover:bg-[var(--muted)]"
        >
          <FileSpreadsheet size={13} />
          {t("Export CSV")}
        </a>
        <a
          href={immersiveReadingApi.vocabularyExportUrl("apkg")}
          download="deeptutor-vocabulary.apkg"
          className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs font-medium text-[var(--foreground)] transition hover:bg-[var(--muted)]"
        >
          <Layers size={13} />
          {t("Export Anki")}
        </a>
        {bookOptions.length > 1 && (
          <select value={filterBook} onChange={(e) => setFilterBook(e.target.value)} className="rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-1.5 text-xs text-[var(--foreground)]">
            <option value="all">{t("All books")}</option>
            {bookOptions.map((d) => <option key={d.id} value={d.id}>{d.title}</option>)}
          </select>
        )}
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        {filtered.map((entry) => {
          const firstDef = entry.definitions[0];
          const isExpanded = expandedId === entry.id;
          return (
            <article key={entry.id} className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 shadow-sm">
              <div className="mb-3 flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <button type="button" onClick={() => onOpen(entry)} className="text-left">
                    <span className="text-lg font-semibold text-[var(--foreground)]">{entry.word}</span>
                    {entry.phonetic && <span className="ml-2 text-sm text-[var(--muted-foreground)]">{entry.phonetic}</span>}
                  </button>
                  {entry.document_title && (
                    <p className="mt-0.5 truncate text-xs text-[var(--muted-foreground)]">{entry.document_title}{entry.section_title ? ` · ${entry.section_title}` : ""}</p>
                  )}
                  <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[10px] text-[var(--muted-foreground)]">
                    {entry.pairing_id && (
                      <span className="rounded bg-[var(--primary)]/10 px-1.5 py-0.5 text-[var(--primary)]">{t("Bilingual source")}</span>
                    )}
                    {(entry.occurrence_count ?? 1) > 1 && (
                      <span>{t("Seen {{count}} times", { count: entry.occurrence_count })}</span>
                    )}
                  </div>
                </div>
                <button type="button" aria-label={t("Delete")} onClick={() => void onDelete(entry)} className="rounded-lg p-2 text-[var(--muted-foreground)] hover:bg-red-500/10 hover:text-red-500">
                  <Trash2 size={15} />
                </button>
              </div>
              {firstDef ? (
                <div className="text-sm leading-6 text-[var(--foreground)]/90">
                  {firstDef.part_of_speech && <span className="text-xs italic text-[var(--muted-foreground)]">{firstDef.part_of_speech} </span>}
                  {firstDef.definition}
                </div>
              ) : (
                <p className="text-sm text-[var(--muted-foreground)]">{entry.context_note || t("No definition available")}</p>
              )}
              {entry.definitions.length > 1 && (
                <button type="button" onClick={() => setExpandedId(isExpanded ? null : entry.id)} className="mt-2 text-xs text-[var(--primary)] hover:underline">
                  {isExpanded ? t("Show less") : t("{{count}} more definitions", { count: entry.definitions.length - 1 })}
                </button>
              )}
              {isExpanded && (
                <div className="mt-3 space-y-2 border-t border-[var(--border)] pt-3">
                  {entry.definitions.slice(1).map((def, i) => (
                    <div key={i} className="text-sm leading-6 text-[var(--foreground)]/85">
                      {def.part_of_speech && <span className="text-xs italic text-[var(--muted-foreground)]">{def.part_of_speech} </span>}
                      {def.definition}
                      {def.example && <p className="mt-0.5 text-xs italic text-[var(--muted-foreground)]">&ldquo;{def.example}&rdquo;</p>}
                    </div>
                  ))}
                </div>
              )}
            </article>
          );
        })}
      </div>
    </div>
  );
}

function FocusHistoryView({
  documents,
  onOpen,
}: {
  documents: ReadingDocument[];
  onOpen: (documentId: string, sectionId: string) => void;
}) {
  const { t } = useTranslation();
  const [filterBook, setFilterBook] = useState<string>("all");
  const [filterStatus, setFilterStatus] = useState<"all" | "passed" | "failed">("all");
  const attempts = documents
    .flatMap((document) => Object.entries(document.progress.focus_history || {}).flatMap(
      ([sectionId, records]) => {
        const section = document.sections.find((item) => item.id === sectionId);
        return records.map((record) => ({ document, section, record }));
      },
    ))
    .sort((left, right) => right.record.created_at - left.record.created_at);
  const bookOptions = documents.filter((d) => Object.values(d.progress?.focus_history || {}).some((r) => r.length > 0));
  const filtered = attempts.filter(({ document, record }) => {
    if (filterBook !== "all" && document.id !== filterBook) return false;
    if (filterStatus === "passed" && !(record.status === "graded" && record.passed)) return false;
    if (filterStatus === "failed" && !((record.status === "graded" && !record.passed) || record.status === "error")) return false;
    return true;
  });
  const passedCount = attempts.filter((a) => a.record.status === "graded" && a.record.passed).length;
  const failedCount = attempts.filter((a) => a.record.status === "graded" && !a.record.passed).length;
  const errorCount = attempts.filter((a) => a.record.status === "error").length;
  const gradedScores = attempts.filter((a) => a.record.score != null).map((a) => a.record.score as number);
  const avgScore = gradedScores.length ? Math.round(gradedScores.reduce((s, v) => s + v, 0) / gradedScores.length) : null;

  if (!attempts.length) {
    return (
      <div className="flex min-h-[420px] flex-col items-center justify-center rounded-3xl border border-dashed border-[var(--border)] text-center">
        <BookCheck size={34} className="mb-4 text-[var(--muted-foreground)]" />
        <h2 className="font-semibold">{t("No answer history yet")}</h2>
        <p className="mt-2 max-w-md text-sm text-[var(--muted-foreground)]">{t("Optional Focus-Checks will appear here for review and future optimization.")}</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-4 rounded-xl bg-[var(--muted)]/35 px-4 py-3">
        <span className="text-xs text-[var(--muted-foreground)]">{t("{{total}} attempts", { total: attempts.length })}</span>
        <span className="text-xs text-emerald-500">{t("{{n}} passed", { n: passedCount })}</span>
        <span className="text-xs text-amber-500">{t("{{n}} failed", { n: failedCount })}</span>
        {errorCount > 0 && <span className="text-xs text-red-500">{t("{{n}} errors", { n: errorCount })}</span>}
        {avgScore != null && <span className="text-xs text-[var(--muted-foreground)]">{t("avg {{score}}/100", { score: avgScore })}</span>}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        {bookOptions.length > 1 && (
          <select value={filterBook} onChange={(e) => setFilterBook(e.target.value)} className="rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-1.5 text-xs text-[var(--foreground)]">
            <option value="all">{t("All books")}</option>
            {bookOptions.map((d) => <option key={d.id} value={d.id}>{d.title}</option>)}
          </select>
        )}
        <div className="flex items-center gap-1">
          {(["all", "passed", "failed"] as const).map((s) => (
            <button key={s} type="button" onClick={() => setFilterStatus(s)} className={`rounded-lg px-3 py-1.5 text-xs transition-colors ${filterStatus === s ? "bg-[var(--muted)] font-medium text-[var(--foreground)]" : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"}`}>
              {s === "all" ? t("All") : s === "passed" ? t("Passed") : t("Failed")}
            </button>
          ))}
        </div>
      </div>
      {filtered.map(({ document, section, record }) => (
        <article key={record.id} className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 shadow-sm">
          <button type="button" onClick={() => onOpen(document.id, record.section_id)} className="w-full text-left">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <h2 className="truncate text-sm font-semibold">{document.title}</h2>
                <p className="mt-1 truncate text-xs text-[var(--muted-foreground)]">{section?.title || record.section_id} · {t("Attempt {{number}}", { number: record.attempt_number })}</p>
              </div>
              <span className={`rounded-full px-3 py-1 text-xs font-semibold ${record.status === "error" ? "bg-red-500/10 text-red-500" : record.passed ? "bg-emerald-500/10 text-emerald-500" : "bg-amber-500/10 text-amber-500"}`}>
                {record.status === "error" ? t("Grading failed") : record.score == null ? t("Not graded") : `${record.score}/100`}
              </span>
            </div>
          </button>
          {record.answer_recorded ? (
            <div className="mt-4 grid gap-3 lg:grid-cols-2">
              <div className="rounded-xl bg-[var(--muted)]/45 p-3 text-sm leading-6"><span className="font-medium">{t("Main content")}:</span> <span className="whitespace-pre-wrap">{record.summary}</span></div>
              <div className="rounded-xl bg-[var(--muted)]/45 p-3 text-sm leading-6"><span className="font-medium">{t("Additional notes")}:</span> <span className="whitespace-pre-wrap">{record.reflection}</span></div>
            </div>
          ) : <p className="mt-4 rounded-xl bg-[var(--muted)]/45 p-3 text-sm text-[var(--muted-foreground)]">{t("Answer text was not stored by the previous version.")}</p>}
          {(record.feedback || record.error) && <p className={`mt-3 text-sm leading-6 ${record.error ? "text-red-500" : "text-[var(--muted-foreground)]"}`}>{record.error || record.feedback}</p>}
          <p className="mt-3 text-[11px] text-[var(--muted-foreground)]">{[record.model, record.prompt_version].filter(Boolean).join(" · ")}</p>
        </article>
      ))}
    </div>
  );
}

function Reader({
  documentId,
  capabilities,
  onBack,
  onCitationAdded,
  onVocabularyAdded,
  onToast,
  onErrorToast,
}: {
  documentId: string;
  capabilities: ReadingCapabilities | null;
  onBack: () => void;
  onCitationAdded: () => void;
  onVocabularyAdded: () => void;
  onToast: (message: string) => void;
  onErrorToast: (message: string) => void;
}) {
  const { t, i18n } = useTranslation();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [document, setDocument] = useState<ReadingDocument | null>(null);
  const [progress, setProgress] = useState<ReadingProgress | null>(null);
  const [sectionId, setSectionId] = useState<string>(searchParams.get("section") || "");
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadingSection, setLoadingSection] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchMode, setSearchMode] = useState<SearchMode>("exact");
  const [searching, setSearching] = useState(false);
  const [searchHits, setSearchHits] = useState<SearchHit[]>([]);
  const [searchOpen, setSearchOpen] = useState(false);
  const [rebuildingIndex, setRebuildingIndex] = useState(false);
  const [selectionMenu, setSelectionMenu] = useState<SelectionMenuState | null>(null);
  const [selectionAction, setSelectionAction] = useState<SelectionAction | null>(null);
  const [selectionResult, setSelectionResult] = useState("");
  const [selectionQuestion, setSelectionQuestion] = useState("");
  const [selectionBusy, setSelectionBusy] = useState(false);

  // Dictionary popup state
  const [dictPopup, setDictPopup] = useState<{
    word: string;
    anchorRect: DOMRect;
    context: string;
  } | null>(null);
  const [dictResult, setDictResult] = useState<DictionaryResult | null>(null);
  const [dictBusy, setDictBusy] = useState(false);
  const [dictError, setDictError] = useState<string | null>(null);
  const dictAbortRef = useRef<AbortController | null>(null);
  const dictSeqRef = useRef(0);

  const [focusOpen, setFocusOpen] = useState(false);
  const [focusSummary, setFocusSummary] = useState("");
  const [focusReflection, setFocusReflection] = useState("");
  const [focusBusy, setFocusBusy] = useState(false);
  const [focusResult, setFocusResult] = useState<FocusCheckResult | null>(null);
  const [focusValidationError, setFocusValidationError] = useState<string | null>(null);
  const [restartMenu, setRestartMenu] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [, forceSidebarUpdate] = useState(0);
  const [charGraphOpen, setCharGraphOpen] = useState(false);
  const [charGraphScope, setCharGraphScope] = useState<CharacterScope>("current");
  const [charGraphMermaid, setCharGraphMermaid] = useState("");
  const [charGraphNodes, setCharGraphNodes] = useState<
    Array<{ id: string; name: string; aliases: string[]; description: string }>
  >([]);
  const [charGraphLoading, setCharGraphLoading] = useState(false);
  const [charGraphError, setCharGraphError] = useState<string | null>(null);
  const articleRef = useRef<HTMLDivElement>(null);
  const selectionDebounceRef = useRef<number | null>(null);
  const lastProgressSentRef = useRef({ at: 0, value: -1 });
  const progressRef = useRef<ReadingProgress | null>(null);
  const sectionTransitionRef = useRef(false);
  const restoreSavedScrollRef = useRef(true);
  const collapsedParentsRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    progressRef.current = progress;
  }, [progress]);

  const refreshDocument = useCallback(async () => {
    const result = await immersiveReadingApi.get(documentId);
    setDocument(result.document);
    setProgress(result.document.progress);
    setSectionId((current) => current || result.document.progress.current_section_id || result.document.sections[0]?.id || "");
  }, [documentId]);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    immersiveReadingApi
      .get(documentId)
      .then((result) => {
        if (!mounted) return;
        setDocument(result.document);
        setProgress(result.document.progress);
        setSectionId((current) => current || result.document.progress.current_section_id || result.document.sections[0]?.id || "");
      })
      .catch((cause) => mounted && setError(errorMessage(cause)))
      .finally(() => mounted && setLoading(false));
    return () => {
      mounted = false;
    };
  }, [documentId]);

  useEffect(() => {
    if (!sectionId) return;
    let mounted = true;
    sectionTransitionRef.current = true;
    setLoadingSection(true);
    setSelectionMenu(null);
    setSearchOpen(false);
    // Cancel any in-flight dictionary lookup on section change
    dictAbortRef.current?.abort();
    dictSeqRef.current += 1;
    setDictPopup(null);
    setDictResult(null);
    setDictError(null);
    setDictBusy(false);
    immersiveReadingApi
      .section(documentId, sectionId)
      .then((result) => {
        if (!mounted) return;
        setContent(result.content);
        window.requestAnimationFrame(() => {
          const root = scrollRef.current;
          if (!root) {
            sectionTransitionRef.current = false;
            return;
          }
          const snapshot = progressRef.current;
          const isCurrent = snapshot?.current_section_id === sectionId;
          const percent = restoreSavedScrollRef.current && isCurrent
            ? snapshot?.scroll_percent || 0
            : 0;
          root.scrollTop = ((root.scrollHeight - root.clientHeight) * percent) / 100;
          restoreSavedScrollRef.current = true;
          window.requestAnimationFrame(() => {
            sectionTransitionRef.current = false;
          });
        });
      })
      .catch((cause) => {
        sectionTransitionRef.current = false;
        if (mounted) setError(errorMessage(cause));
      })
      .finally(() => mounted && setLoadingSection(false));
    return () => {
      mounted = false;
    };
  }, [documentId, sectionId, t]);

  useEffect(() => {
    const status = document?.fast_search_index.status;
    if (!status || !["not_started", "building", "stale"].includes(status)) return;
    const timer = window.setInterval(() => {
      void refreshDocument().catch(() => undefined);
    }, 2500);
    return () => window.clearInterval(timer);
  }, [document?.fast_search_index.status, refreshDocument]);

  const currentSection = useMemo(
    () => document?.sections.find((section) => section.id === sectionId) || null,
    [document, sectionId],
  );
  const currentIndex = currentSection?.index ?? 0;
  const passedSet = useMemo(() => new Set(progress?.passed_section_ids || []), [progress?.passed_section_ids]);
  const skippedSet = useMemo(() => new Set(progress?.skipped_section_ids || []), [progress?.skipped_section_ids]);
  const currentRequiresFocusCheck = currentSection?.checkpoint_kind !== "none";
  const currentPassed = Boolean(
    currentSection && (!currentRequiresFocusCheck || passedSet.has(currentSection.id)),
  );
  const currentSkipped = Boolean(currentSection && skippedSet.has(currentSection.id));
  const focusSections = useMemo(
    () => document?.sections.filter((section) => section.checkpoint_kind !== "none") || [],
    [document],
  );
  const passedFocusCount = useMemo(
    () => focusSections.filter((section) => passedSet.has(section.id)).length,
    [focusSections, passedSet],
  );
  const focusHistory = currentSection
    ? progress?.focus_history?.[currentSection.id] || []
    : [];

  useEffect(() => {
    if (currentRequiresFocusCheck) return;
    setFocusOpen(false);
    setFocusResult(null);
    setFocusValidationError(null);
  }, [currentRequiresFocusCheck]);

  const openSection = useCallback(
    (nextId: string) => {
      if (!document) return;
      const next = document.sections.find((section) => section.id === nextId);
      if (!next) return;
      sectionTransitionRef.current = true;
      restoreSavedScrollRef.current = false;
      if (scrollRef.current) scrollRef.current.scrollTop = 0;
      setSectionId(next.id);
      setContent("");
    },
    [document],
  );

  const handleScroll = useCallback(() => {
    const root = scrollRef.current;
    if (!root || !currentSection || sectionTransitionRef.current) return;
    const distance = root.scrollHeight - root.clientHeight;
    const percent = distance <= 0 ? 100 : Math.max(0, Math.min(100, (root.scrollTop / distance) * 100));
    const now = Date.now();
    const previous = lastProgressSentRef.current;
    if (Math.abs(percent - previous.value) >= 3 && now - previous.at >= 750) {
      lastProgressSentRef.current = { at: now, value: percent };
      void immersiveReadingApi
        .progress(documentId, currentSection.id, percent)
        .then((result) => setProgress(result.progress))
        .catch(() => undefined);
    }
  }, [currentSection, documentId]);

  const handleSelection = useCallback(() => {
    const selection = window.getSelection();
    const text = selection?.toString().trim() || "";
    if (!selection || !text || selection.rangeCount === 0 || !articleRef.current) {
      setSelectionMenu(null);
      return;
    }
    const anchor = selection.anchorNode;
    if (!anchor || !articleRef.current.contains(anchor)) {
      setSelectionMenu(null);
      return;
    }
    const rect = selection.getRangeAt(0).getBoundingClientRect();
    setSelectionMenu({
      text: text.slice(0, 12_000),
      left: Math.max(12, Math.min(window.innerWidth - 310, rect.left + rect.width / 2 - 150)),
     top: Math.max(12, rect.top - 52),
   });
 }, []);

  useEffect(() => {
    const debouncedCheck = () => {
      if (selectionDebounceRef.current !== null) {
        window.clearTimeout(selectionDebounceRef.current);
      }
      selectionDebounceRef.current = window.setTimeout(() => {
        handleSelection();
        selectionDebounceRef.current = null;
      }, 300);
    };
    window.document.addEventListener("selectionchange", debouncedCheck);
    return () => {
      window.document.removeEventListener("selectionchange", debouncedCheck);
      if (selectionDebounceRef.current !== null) {
        window.clearTimeout(selectionDebounceRef.current);
      }
    };
  }, [handleSelection]);

  const runTranslation = async () => {
    if (!selectionMenu) return;
    dictAbortRef.current?.abort();
    const targetLanguage = "Chinese";
    setSelectionAction("translate");
    setSelectionResult("");
    setSelectionBusy(true);
    let jobId: string | null = null;
    const controller = new AbortController();
    dictAbortRef.current = controller;
    const requestId = ++dictSeqRef.current;

    try {
      const cached = getCachedTranslation(selectionMenu.text, targetLanguage);
      if (cached) {
        setSelectionResult(cached);
        return;
      }

      const job = await immersiveReadingApi.translateJob(
        selectionMenu.text,
        targetLanguage,
        [],
        documentId || "",
        currentSection?.id || "",
        controller.signal,
      );
      jobId = job.job_id;

      let translation = "";
      let jobError: ApiRequestError | null = null;
      await immersiveReadingApi.translateJobStream(
        jobId,
        (event) => {
          if (requestId !== dictSeqRef.current || controller.signal.aborted) return;
          if (event.type === "delta" && event.delta) {
            translation += event.delta;
            setSelectionResult(translation);
            return;
          }
          if (event.type === "completed") {
            translation = event.translation || translation;
            return;
          }
          if (event.type === "failed" || event.type === "cancelled") {
            jobError = new ApiRequestError(
              event.error || "Translation failed.",
              event.type === "failed" ? 500 : 499,
            );
          }
        },
        controller.signal,
      );
      if (jobError) throw jobError;
      if (translation) {
        setCachedTranslation(selectionMenu.text, targetLanguage, translation);
      }
      setSelectionResult(translation || t("Translation failed."));
    } catch (cause) {
      if (dictSeqRef.current !== requestId) return;
      if (cause instanceof DOMException && cause.name === "AbortError" && jobId) {
        void immersiveReadingApi.translateJobCancel(jobId).catch(() => undefined);
        return;
      }
      if (cause instanceof ApiRequestError && cause.status === 503) {
        setSelectionResult(cause.message || t("Local translation service unavailable. Start Ollama to enable translation."));
      } else if (cause instanceof ApiRequestError && cause.status === 504) {
        setSelectionResult(t("Translation timed out. The model may still be loading."));
      } else {
        setSelectionResult(errorMessage(cause));
      }
    } finally {
      setSelectionBusy(false);
      setSelectionMenu(null);
      window.getSelection()?.removeAllRanges();
    }
  };

  const recordSelection = async () => {
    if (!selectionMenu || !currentSection) return;
    try {
      await immersiveReadingApi.cite(documentId, currentSection.id, selectionMenu.text);
      onCitationAdded();
      onToast(t("Saved to Citations"));
    } catch (cause) {
      onToast(errorMessage(cause));
    } finally {
      setSelectionMenu(null);
      window.getSelection()?.removeAllRanges();
    }
 };

 const saveWord = () => {
   if (!selectionMenu || !articleRef.current) return;
   const range = window.getSelection()?.getRangeAt(0);
   const rect = range?.getBoundingClientRect();
   if (!rect) return;
   const word = selectionMenu.text.trim();
   if (!word) return;
   const startIdx = content.indexOf(word);
   const context = content.slice(Math.max(0, startIdx - 200), startIdx + word.length + 200);
   // Cancel any in-flight dictionary lookup
   dictAbortRef.current?.abort();
   dictSeqRef.current += 1;
   setDictResult(null);
   setDictError(null);
   setDictPopup({ word, anchorRect: rect, context });
   setSelectionMenu(null);
   window.getSelection()?.removeAllRanges();
 };

 const lookupDictionary = useCallback(async (word: string, context: string) => {
   const seq = dictSeqRef.current;
   const controller = new AbortController();
   dictAbortRef.current = controller;
   setDictBusy(true);
   setDictError(null);
   setDictResult(null);
   try {
     const result = await immersiveReadingApi.dictionary(word, context, controller.signal);
     // Only update if this is still the latest request
     if (seq === dictSeqRef.current) {
       setDictResult(result);
       setDictBusy(false);
     }
   } catch (cause) {
     if (cause instanceof DOMException && cause.name === "AbortError") return;
     if (seq === dictSeqRef.current) {
       if (cause instanceof ApiRequestError) {
         const status = cause.status;
        if (status === 503) setDictError(cause.message || t("Local dictionary unavailable. Run `ollama serve` then `ollama pull qwen3.5:2b`."));
        else if (status === 504) setDictError(t("Dictionary lookup timed out. The local model may still be loading."));
        else setDictError(cause.message || t("Lookup failed."));
       } else {
         setDictError(errorMessage(cause));
       }
       setDictBusy(false);
     }
   }
 }, [t]);

 // Trigger dictionary lookup when popup opens
 useEffect(() => {
   if (!dictPopup) return;
   void lookupDictionary(dictPopup.word, dictPopup.context);
 }, [dictPopup, lookupDictionary]);

 const saveDictWord = useCallback(async () => {
   if (!dictPopup || !currentSection) return;
   try {
     const { lookup_warning } = await immersiveReadingApi.addWord(
       dictPopup.word,
       dictPopup.context,
       documentId,
       document?.title || "",
       currentSection.title,
     );
     onVocabularyAdded();
     onToast(lookup_warning ? t("Added to vocabulary") + " — " + t("Definition unavailable") : t("Added to vocabulary"));
   } catch (cause) {
     onErrorToast(errorMessage(cause));
   }
   setDictPopup(null);
   setDictResult(null);
   setDictError(null);
 }, [dictPopup, currentSection, documentId, document, onVocabularyAdded, onToast, onErrorToast, t]);

const closeDictPopup = useCallback(() => {
  dictAbortRef.current?.abort();
  dictSeqRef.current += 1;
  setDictPopup(null);
  setDictResult(null);
  setDictError(null);
  setDictBusy(false);
}, []);

 const translateDictWord = useCallback(async () => {
   if (!dictPopup) return;
   const seq = dictSeqRef.current + 1;
   dictSeqRef.current = seq;
   const targetLanguage = "zh";
   setDictBusy(true);
   setDictError(null);
   setDictResult(null);
   const controller = new AbortController();
   dictAbortRef.current = controller;
   let jobId: string | null = null;
   try {
     const cached = getCachedTranslation(dictPopup.word, targetLanguage);
     if (cached) {
       setDictResult({
         word: dictPopup.word,
         phonetic: "",
         definitions: [],
         context_note: cached,
       });
       return;
     }

     const job = await immersiveReadingApi.translateJob(dictPopup.word, targetLanguage, []);
     jobId = job.job_id;
     let translation = "";
     let jobError: ApiRequestError | null = null;

     await immersiveReadingApi.translateJobStream(
       jobId,
       (event) => {
         if (seq !== dictSeqRef.current || controller.signal.aborted) return;
         if (event.type === "delta" && event.delta) {
           translation += event.delta;
           setDictResult({
             word: dictPopup.word,
             phonetic: "",
             definitions: [],
             context_note: translation,
           });
         }
         if (event.type === "completed") {
           translation = event.translation || translation;
         }
         if (event.type === "failed" || event.type === "cancelled") {
           jobError = new ApiRequestError(
             event.error || "Translation failed.",
             event.type === "failed" ? 500 : 499,
           );
         }
       },
       controller.signal,
     );

     if (jobError) throw jobError;
     if (translation) {
       setCachedTranslation(dictPopup.word, targetLanguage, translation);
       setDictResult({
         word: dictPopup.word,
         phonetic: "",
         definitions: [],
         context_note: translation,
       });
       return;
     }
     throw new ApiRequestError("Translation produced no content.", 500);
   } catch (cause) {
     if (seq === dictSeqRef.current) {
       if (cause instanceof DOMException && cause.name === "AbortError" && jobId) {
         void immersiveReadingApi.translateJobCancel(jobId).catch(() => undefined);
         return;
       }
       setDictError(cause instanceof Error ? cause.message : t("Lookup failed."));
     }
   } finally {
     setDictBusy(false);
   }
 }, [dictPopup, t]);

  const openQuery = () => {
    if (selectionMenu?.text) queryTextRef.current = selectionMenu.text;
    setSelectionAction("query");
    setSelectionQuestion("");
    setSelectionResult("");
    setSelectionMenu(null);
  };

  const runQuery = async () => {
    if (!selectionMenu && !selectionAction) return;
    const selectedText = selectionMenu?.text || (window.getSelection()?.toString().trim() ?? "");
    // The selection menu is cleared when the modal opens, so retain the text in a data attribute-like ref.
    const text = selectedText || queryTextRef.current;
    if (!text) return;
    setSelectionBusy(true);
    try {
      const result = await immersiveReadingApi.query(
        text,
        selectionQuestion,
        i18n.language.startsWith("zh") ? "zh" : "en",
      );
      setSelectionResult(result.answer);
    } catch (cause) {
      setSelectionResult(errorMessage(cause));
    } finally {
      setSelectionBusy(false);
    }
  };
  const queryTextRef = useRef("");
  useEffect(() => {
    if (selectionMenu?.text) queryTextRef.current = selectionMenu.text;
  }, [selectionMenu]);

  const runSearch = async () => {
    if (!searchQuery.trim()) {
      setSearchHits([]);
      return;
    }
    setSearching(true);
    setSearchOpen(true);
    try {
      const result = searchMode === "description_fast" || searchMode === "description_fine"
        ? await runDescriptionSearchJob(documentId, searchQuery, searchMode)
        : await immersiveReadingApi.search(documentId, searchQuery, searchMode);
      setSearchHits(result.hits || []);
      if (result.fallback_used) {
        onToast(t("Quick search confidence was low, so Fine search was used automatically."));
      }
      if (result.warnings?.length) {
        onErrorToast(t("Some candidate chapters could not be searched; available results are shown."));
      }
    } catch (cause) {
      setSearchHits([]);
      onErrorToast(errorMessage(cause));
    } finally {
      setSearching(false);
    }
  };

  const rebuildFastIndex = async () => {
    setRebuildingIndex(true);
    try {
      const result = await immersiveReadingApi.rebuildFastIndex(documentId);
      setDocument((current) => current ? { ...current, fast_search_index: result.index } : current);
      onToast(t("Fast search index rebuild started."));
    } catch (cause) {
      onErrorToast(errorMessage(cause));
    } finally {
      setRebuildingIndex(false);
    }
  };

  const submitFocusCheck = async () => {
    if (!currentSection) return;
    if (focusSummary.trim().length < 20) {
      setFocusValidationError(
        t("Write at least {{count}} characters for the main content.", { count: 20 }),
      );
      return;
    }
    setFocusValidationError(null);
    setFocusBusy(true);
    try {
      const result = await immersiveReadingApi.focusCheck(documentId, {
        section_id: currentSection.id,
        summary: focusSummary,
        reflection: focusReflection,
        language: i18n.language.startsWith("zh") ? "zh" : "en",
      });
      setFocusResult(result);
      setProgress(result.progress);
      if (result.passed) await refreshDocument();
    } catch (cause) {
      const detail = errorMessage(cause);
      const invalidModelResponse = /(?:empty|invalid) Focus-Check/i.test(detail);
      onErrorToast(
        invalidModelResponse
          ? t("The model returned an empty or invalid Focus-Check response. Your score was not changed; please try again.")
          : detail,
      );
      await refreshDocument().catch(() => undefined);
    } finally {
      setFocusBusy(false);
    }
  };

  // --- Character Graph ---
  const fetchCharGraph = useCallback(
    async (scope: CharacterScope, force = false) => {
      if (!currentSection) return;
      setCharGraphLoading(true);
      setCharGraphError(null);
      try {
        const result = await immersiveReadingApi.characterGraph(
          documentId,
          currentSection.id,
          scope,
          force,
        );
        setCharGraphMermaid(result.mermaid);
        setCharGraphNodes(result.graph.nodes);
      } catch (err) {
        setCharGraphError(
          err instanceof Error ? err.message : String(t("Failed to generate graph")),
        );
      } finally {
        setCharGraphLoading(false);
      }
    },
    [currentSection, documentId, t],
  );

  useEffect(() => {
    if (charGraphOpen && currentSection) {
      void fetchCharGraph(charGraphScope);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [charGraphOpen, charGraphScope, currentSection?.id]);

  const handleCharGraphRefresh = async () => {
    if (!currentSection) return;
    setCharGraphLoading(true);
    setCharGraphError(null);
    try {
      const result = await immersiveReadingApi.characterGraph(
        documentId,
        currentSection.id,
        charGraphScope,
        true,
      );
      setCharGraphMermaid(result.mermaid);
      setCharGraphNodes(result.graph.nodes);
    } catch (err) {
      setCharGraphError(
        err instanceof Error ? err.message : String(t("Failed to generate graph")),
      );
    } finally {
      setCharGraphLoading(false);
    }
  };

  const continueAfterFocus = () => {
    if (!document || !currentSection) return;
    const next = document.sections[currentSection.index + 1];
    setFocusOpen(false);
    setFocusSummary("");
    setFocusReflection("");
    setFocusResult(null);
    setFocusValidationError(null);
    if (next) openSection(next.id);
    else onToast(t("You completed this immersive reading run."));
  };

  const skipCurrentSection = async () => {
    if (!document || !currentSection) return;
    try {
      const result = await immersiveReadingApi.skipSection(documentId, currentSection.id);
      setProgress(result.progress);
      setFocusOpen(false);
      setFocusResult(null);
      setFocusValidationError(null);
      const nextSection = document.sections[currentSection.index + 1];
      if (nextSection) openSection(nextSection.id);
      else onToast(t("Section skipped. You can return to it at any time."));
    } catch (cause) {
      onErrorToast(errorMessage(cause));
    }
  };

  const restart = async (resetFocusChecks: boolean) => {
    if (resetFocusChecks && !window.confirm(t("Start a new immersive reading run? All Focus-Checks will be required again."))) return;
    const result = await immersiveReadingApi.restart(documentId, resetFocusChecks);
    setProgress(result.progress);
    setRestartMenu(false);
    const first = document?.sections[0];
    if (first) setSectionId(first.id);
    if (scrollRef.current) scrollRef.current.scrollTop = 0;
    onToast(resetFocusChecks ? t("New immersive reading run started") : t("Returned to the beginning; passed Focus-Checks stay passed."));
  };

  if (loading || !document || !progress) {
    return <div className="flex h-full items-center justify-center text-[var(--muted-foreground)]">{error ? error : <Loader2 className="animate-spin" />}</div>;
  }

  const readingView = defaultReadingView({
    sourceFormat: document.source_format,
    viewParam: searchParams.get("view"),
    experienceMode: document.experience_mode,
  });
  if (readingView === "original") {
    return (
      <OriginalEpubReader
        document={document}
        progress={progress}
        requestedSectionId={sectionId}
        onBack={onBack}
        onOpenStudy={(nextSectionId) => {
          setSectionId(nextSectionId);
          router.replace(immersiveReadingPath(documentId, { view: "study", section: nextSectionId }));
        }}
        onProgress={setProgress}
      />
    );
  }

  const previous = document.sections[currentIndex - 1];
  const next = document.sections[currentIndex + 1];
  const overallProgress = document.sections.length
    ? ((progress.current_section_index + progress.scroll_percent / 100) / document.sections.length) * 100
    : 0;
  const fastIndex = document.fast_search_index;
  const fastIndexReady = fastIndex.status === "ready";

  return (
    <div className="relative flex h-full min-w-0 bg-[var(--background)]">
      <aside className="flex w-[286px] shrink-0 flex-col border-r border-[var(--border)] bg-[var(--card)]/55">
        <div className="border-b border-[var(--border)] p-4">
          <button type="button" onClick={onBack} className="mb-4 inline-flex items-center gap-2 text-xs text-[var(--muted-foreground)] hover:text-[var(--foreground)]">
            <ArrowLeft size={14} /> {t("Back to library")}
          </button>
          <div className="flex gap-3">
            <BookCover document={document} compact />
            <div className="min-w-0 flex-1 pt-1">
              <h1 className="line-clamp-3 text-sm font-semibold leading-snug">{document.title}</h1>
              <p className="mt-1 truncate text-[11px] text-[var(--muted-foreground)]">{document.author || document.source_filename}</p>
              <div className="mt-3"><ProgressBar value={overallProgress} /></div>
              <p className="mt-1 text-[10px] text-[var(--muted-foreground)]">{Math.round(overallProgress)}% · {formatNumber(document.total_words)} {t("words")}</p>
            </div>
          </div>
        </div>
        <div className="flex items-center justify-between px-4 pb-2 pt-4">
          <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-[var(--muted-foreground)]">{document.reading_mode === "chapters" ? t("Chapters") : t("Reading checkpoints")}</span>
          <span className="text-[10px] text-[var(--muted-foreground)]">{passedFocusCount}/{focusSections.length}</span>
        </div>
        <nav className="min-h-0 flex-1 overflow-y-auto px-2 pb-4">
         {(() => {
           const parentIds = new Set(document.sections.filter((s) => s.parent_id).map((s) => s.parent_id!));
           const collapsedParents = collapsedParentsRef;
           const toggleParent = (pid: string) => {
              collapsedParents.current = new Set(collapsedParents.current);
              if (collapsedParents.current.has(pid)) collapsedParents.current.delete(pid);
              else collapsedParents.current.add(pid);
              forceSidebarUpdate((n) => n + 1);
            };
            return document.sections.map((section) => {
            const hasChildren = parentIds.has(section.id);
            const isChild = !!section.parent_id;
            if (isChild && collapsedParents.current.has(section.parent_id!)) return null;
            const requiresFocusCheck = section.checkpoint_kind !== "none";
            const passed = !requiresFocusCheck || passedSet.has(section.id);
            const skipped = skippedSet.has(section.id);
            const active = section.id === sectionId;
            const statusMark = !requiresFocusCheck ? (
              <BookMarked size={11} />
            ) : passed ? (
              <Check size={12} className="text-emerald-500" />
            ) : skipped ? (
              <span title={t("Skipped")}>—</span>
            ) : (
              section.index + 1
            );
            return (
              <div key={section.id}>
              <button
                type="button"
                onClick={() => {
                  if (hasChildren) { toggleParent(section.id); return; }
                  openSection(section.id);
                  router.replace(immersiveReadingPath(documentId, {
                    view: document.source_format === "epub" ? "study" : null,
                    section: section.id,
                  }));
                }}
                className={`mb-1 flex w-full items-start gap-2.5 rounded-xl px-3 py-2.5 text-left transition ${
                  active ? "bg-[var(--primary)]/12 text-[var(--foreground)]" : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]/60 hover:text-[var(--foreground)]"
                } ${isChild ? "ml-4" : ""}`}
              >
                <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-current/20 text-[10px]">
                  {hasChildren ? (collapsedParents.current.has(section.id) ? "+" : "−") : statusMark}
                </span>
                <span className="line-clamp-2 text-xs leading-5">{section.title}</span>
              </button>
              </div>
            );
            });
          })()}
        </nav>
        <div className="border-t border-[var(--border)] px-4 py-3">
          <div className="flex items-center justify-between gap-3 text-[11px]">
            <span className="font-medium text-[var(--foreground)]">{t("Fast search index")}</span>
            <button
              type="button"
              disabled={rebuildingIndex || fastIndex.status === "building"}
              onClick={() => void rebuildFastIndex()}
              className="inline-flex items-center gap-1 text-[var(--primary)] disabled:opacity-40"
            >
              <RotateCcw size={11} className={rebuildingIndex ? "animate-spin" : ""} />
              {t("Rebuild")}
            </button>
          </div>
          <div className="mt-2 flex items-center gap-2 text-[10px] text-[var(--muted-foreground)]">
            {fastIndex.status === "building" || fastIndex.status === "not_started" || fastIndex.status === "stale" ? (
              <Loader2 size={11} className="animate-spin text-[var(--primary)]" />
            ) : fastIndexReady ? (
              <Check size={11} className="text-emerald-500" />
            ) : (
              <CircleAlert size={11} className="text-amber-500" />
            )}
            <span>
              {fastIndexReady
                ? t("Ready — {{count}} chapters", { count: fastIndex.completed_sections })
                : fastIndex.status === "failed" || fastIndex.status === "partial"
                  ? t("{{completed}}/{{total}} chapters indexed; rebuild to retry", {
                      completed: fastIndex.completed_sections,
                      total: fastIndex.total_sections,
                    })
                  : t("Indexing {{completed}}/{{total}} chapters", {
                      completed: fastIndex.completed_sections,
                      total: fastIndex.total_sections,
                    })}
            </span>
          </div>
        </div>
        <div className="relative border-t border-[var(--border)] p-3">
          <button type="button" onClick={() => setRestartMenu((value) => !value)} className="flex w-full items-center justify-between rounded-xl px-3 py-2 text-xs text-[var(--muted-foreground)] hover:bg-[var(--muted)]/60 hover:text-[var(--foreground)]">
            <span className="inline-flex items-center gap-2"><RotateCcw size={14} /> {t("Reading options")}</span>
            <MoreHorizontal size={14} />
          </button>
          {restartMenu && (
            <div className="absolute bottom-14 left-3 right-3 z-30 overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--popover)] p-1 shadow-xl">
              <button type="button" onClick={() => void restart(false)} className="w-full rounded-lg px-3 py-2 text-left text-xs hover:bg-[var(--muted)]">{t("Read from the beginning")}</button>
              <button type="button" onClick={() => void restart(true)} className="w-full rounded-lg px-3 py-2 text-left text-xs text-[var(--primary)] hover:bg-[var(--muted)]">{t("Read Immersively Again")}</button>
              <a href={`/api/v1/immersive-reading/documents/${encodeURIComponent(documentId)}/original`} className="flex items-center gap-2 rounded-lg px-3 py-2 text-xs hover:bg-[var(--muted)]"><Download size={13} /> {t("Download original")}</a>
            </div>
          )}
        </div>
      </aside>

      <section className="flex min-w-0 flex-1 flex-col">
        <header className="relative z-30 flex h-[68px] shrink-0 items-center gap-3 border-b border-[var(--border)] bg-[var(--background)]/92 px-5 backdrop-blur-xl">
          <div className="relative flex min-w-0 flex-1 items-center">
            <Search size={16} className="pointer-events-none absolute left-3 text-[var(--muted-foreground)]" />
            <input
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              onFocus={() => searchHits.length && setSearchOpen(true)}
              onKeyDown={(event) => {
                if (event.key === "Enter") void runSearch();
                if (event.key === "Escape") setSearchOpen(false);
              }}
              placeholder={t("Search the full book…")}
              className="h-10 w-full rounded-xl border border-[var(--border)] bg-[var(--card)] pl-10 pr-24 text-sm outline-none transition focus:border-[var(--primary)]"
            />
            <button type="button" onClick={() => void runSearch()} className="absolute right-1.5 rounded-lg bg-[var(--primary)] px-3 py-1.5 text-xs font-medium text-[var(--primary-foreground)]">
              {searching ? <Loader2 size={14} className="animate-spin" /> : t("Search")}
            </button>
          </div>
          <div className="flex shrink-0 rounded-xl border border-[var(--border)] bg-[var(--card)] p-1">
            {(["exact", "fuzzy", "description_fast", "description_fine"] as SearchMode[]).map((mode) => {
              const descriptionMode = mode === "description_fast" || mode === "description_fine";
              const contextUnavailable = descriptionMode && !capabilities?.description_search_enabled;
              const indexUnavailable = mode === "description_fast" && !fastIndexReady;
              const disabled = Boolean(contextUnavailable || indexUnavailable);
              const title = contextUnavailable
                ? t("Requires a default model context window of at least 50k tokens.")
                : indexUnavailable
                  ? t("Fast search becomes available when the chapter index is ready.")
                  : undefined;
              return (
                <button
                  key={mode}
                  type="button"
                  disabled={disabled}
                  title={title}
                  onClick={() => setSearchMode(mode)}
                  className={`rounded-lg px-3 py-1.5 text-xs transition ${searchMode === mode ? "bg-[var(--foreground)] text-[var(--background)]" : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"} disabled:cursor-not-allowed disabled:opacity-35`}
                >
                  {mode === "exact"
                    ? t("Exact")
                    : mode === "fuzzy"
                      ? t("Fuzzy")
                      : mode === "description_fast"
                        ? t("Description · Fast")
                        : t("Description · Fine")}
                </button>
              );
            })}
         </div>
          <button
            type="button"
            onClick={() => setCharGraphOpen((v) => !v)}
            className={`inline-flex shrink-0 items-center gap-1.5 rounded-xl border border-[var(--border)] px-3 py-2 text-xs font-medium transition ${charGraphOpen ? "bg-[var(--primary)] text-[var(--primary-foreground)]" : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"}`}
            title={t("Character relationships")}
          >
            <Network size={15} />
            {t("Characters")}
          </button>
          {document.source_format === "epub" && (
            <button
              type="button"
              onClick={() => router.replace(immersiveReadingPath(documentId, { view: "original", section: sectionId }))}
              className="inline-flex shrink-0 items-center gap-1.5 rounded-xl border border-[var(--border)] px-3 py-2 text-xs font-medium text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
            >
              <BookOpen size={15} />
              {t("Original reading")}
            </button>
          )}
          {searchOpen && (
            <div className="absolute left-5 right-5 top-[58px] max-h-[430px] overflow-y-auto rounded-2xl border border-[var(--border)] bg-[var(--popover)] p-2 shadow-2xl">
              {searching ? (
                <div className="flex items-center justify-center gap-2 py-10 text-sm text-[var(--muted-foreground)]"><Loader2 size={16} className="animate-spin" /> {t("Searching the book…")}</div>
              ) : searchHits.length ? searchHits.map((hit, index) => (
                <button
                  key={`${hit.section_id}-${index}`}
                  type="button"
                  onClick={() => {
                    openSection(hit.section_id);
                    setSearchOpen(false);
                  }}
                  className="block w-full rounded-xl px-3 py-3 text-left hover:bg-[var(--muted)]/70"
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-xs font-semibold">{hit.section_title}</span>
                    {searchMode !== "exact" && <span className="text-[10px] text-[var(--muted-foreground)]">{Math.round(hit.score * 100)}%</span>}
                  </div>
                  <p className="mt-1.5 line-clamp-3 text-xs leading-5 text-[var(--muted-foreground)]">{hit.excerpt}</p>
                  {hit.reason && <p className="mt-1 text-[11px] text-[var(--primary)]">{hit.reason}</p>}
                </button>
              )) : (
                <div className="py-10 text-center text-sm text-[var(--muted-foreground)]">{t("No matching passages")}</div>
              )}
            </div>
          )}
        </header>

        {error && (
          <div className="mx-6 mt-4 flex items-start gap-3 rounded-xl border border-red-500/25 bg-red-500/8 px-4 py-3 text-sm text-red-500">
            <CircleAlert size={17} className="mt-0.5 shrink-0" />
            <span className="flex-1">{error}</span>
            <button type="button" onClick={() => setError(null)}><X size={15} /></button>
          </div>
        )}

        <div ref={scrollRef} onScroll={handleScroll} className="min-h-0 flex-1 overflow-y-auto" style={{ scrollBehavior: "smooth" }}>
          <article
            ref={articleRef}
            onMouseUp={handleSelection}
            className="mx-auto w-full max-w-[860px] px-10 pb-24 pt-12"
            style={{ WebkitTouchCallout: "none", userSelect: "text" } as CSSProperties}
          >
            <div className="mb-10 border-b border-[var(--border)] pb-8 text-center">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[var(--primary)]">{t("Section {{current}} of {{total}}", { current: currentIndex + 1, total: document.sections.length })}</p>
              <h2 className="mt-3 font-serif text-3xl font-semibold leading-tight text-[var(--foreground)]">{currentSection?.title}</h2>
              <p className="mt-3 text-xs text-[var(--muted-foreground)]">
                {formatNumber(currentSection?.char_count || 0)} {t("characters")} · {currentRequiresFocusCheck
                  ? currentPassed ? t("Focus-Check passed") : t("Focus-Check required at the end")
                  : t("No Focus-Check for reference matter")}
              </p>
            </div>
            {loadingSection ? (
              <div className="flex min-h-[360px] items-center justify-center"><Loader2 className="animate-spin text-[var(--muted-foreground)]" /></div>
            ) : (
              <div className="immersive-reading-prose select-text font-serif text-[18px] leading-[2.05] text-[var(--foreground)]/92">
                <MarkdownRenderer content={content} variant="prose" />
              </div>
            )}
            <div className="mt-16 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 text-center">
              {!currentRequiresFocusCheck ? (
                <>
                  <BookMarked className="mx-auto text-[var(--primary)]" size={25} />
                  <p className="mt-2 text-sm font-medium">{t("Reference matter does not require a Focus-Check.")}</p>
                  {next && <button type="button" onClick={() => openSection(next.id)} className="mt-4 inline-flex items-center gap-2 rounded-xl bg-[var(--primary)] px-4 py-2 text-sm font-medium text-[var(--primary-foreground)]">{t("Continue reading")} <ChevronRight size={15} /></button>}
                  <FocusHistoryPanel history={focusHistory} />
                </>
              ) : currentPassed ? (
                <>
                  <BookCheck className="mx-auto text-emerald-500" size={26} />
                  <p className="mt-2 text-sm font-medium">{t("You already passed this section's Focus-Check.")}</p>
                  <div className="mt-4 flex flex-wrap justify-center gap-2">
                    <button type="button" onClick={() => { setFocusResult(null); setFocusValidationError(null); setFocusOpen(true); }} className="rounded-xl border border-[var(--border)] px-4 py-2 text-sm font-medium">{t("Try Focus-Check again")}</button>
                    {next && <button type="button" onClick={() => openSection(next.id)} className="inline-flex items-center gap-2 rounded-xl bg-[var(--primary)] px-4 py-2 text-sm font-medium text-[var(--primary-foreground)]">{t("Continue reading")} <ChevronRight size={15} /></button>}
                  </div>
                  <FocusHistoryPanel history={focusHistory} />
                </>
              ) : (
                <>
                  <Sparkles className="mx-auto text-[var(--primary)]" size={24} />
                  <p className="mt-2 text-sm font-medium">{currentSkipped ? t("You skipped this section.") : t("Want to check your understanding?")}</p>
                  <p className="mt-1 text-xs text-[var(--muted-foreground)]">{t("Focus-Check is optional. Technical books can be read in any order.")}</p>
                  <div className="mt-4 flex flex-wrap justify-center gap-2">
                    <button type="button" onClick={() => { setFocusResult(null); setFocusValidationError(null); setFocusOpen(true); }} className="rounded-xl bg-[var(--primary)] px-4 py-2 text-sm font-medium text-[var(--primary-foreground)]">{focusHistory.length ? t("Try Focus-Check again") : t("Start Focus-Check")}</button>
                    {!currentSkipped && <button type="button" onClick={() => void skipCurrentSection()} className="rounded-xl border border-[var(--border)] px-4 py-2 text-sm font-medium">{t("Skip section")}</button>}
                    {next && <button type="button" onClick={() => openSection(next.id)} className="rounded-xl border border-[var(--border)] px-4 py-2 text-sm font-medium">{t("Continue without a check")}</button>}
                  </div>
                </>
              )}
            </div>
            <div className="mt-8 flex items-center justify-between">
              <button type="button" disabled={!previous} onClick={() => previous && openSection(previous.id)} className="inline-flex items-center gap-2 rounded-xl border border-[var(--border)] px-4 py-2 text-sm disabled:opacity-30"><ChevronLeft size={16} /> {t("Previous section")}</button>
              <button type="button" disabled={!next} onClick={() => next && openSection(next.id)} className="inline-flex items-center gap-2 rounded-xl border border-[var(--border)] px-4 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-30">{t("Next section")} <ChevronRight size={16} /></button>
            </div>
          </article>
        </div>
     </section>

      {charGraphOpen && (
        <aside className="flex h-full w-[400px] shrink-0 flex-col border-l border-[var(--border)] bg-[var(--card)]/40 backdrop-blur">
          <header className="flex items-center justify-between border-b border-[var(--border)] px-4 py-3">
            <div className="flex items-center gap-2 text-sm font-medium">
              <Network className="h-4 w-4 text-[var(--primary)]" />
              {t("Character Relationships")}
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                disabled={charGraphLoading}
                onClick={() => void handleCharGraphRefresh()}
                className="rounded-lg p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
                title={t("Refresh")}
              >
                {charGraphLoading ? <Loader2 size={14} className="animate-spin" /> : <RotateCcw size={14} />}
              </button>
              <button
                type="button"
                onClick={() => setCharGraphOpen(false)}
                className="rounded-lg p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
              >
                <X size={16} />
              </button>
            </div>
          </header>

          <div className="flex gap-1 border-b border-[var(--border)] px-3 py-2">
            <button
              type="button"
              onClick={() => setCharGraphScope("current")}
              className={`rounded-lg px-3 py-1.5 text-xs transition ${charGraphScope === "current" ? "bg-[var(--primary)] text-[var(--primary-foreground)]" : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"}`}
            >
              {t("This chapter")}
            </button>
            <button
              type="button"
              onClick={() => setCharGraphScope("through_current")}
              className={`rounded-lg px-3 py-1.5 text-xs transition ${charGraphScope === "through_current" ? "bg-[var(--primary)] text-[var(--primary-foreground)]" : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"}`}
            >
              {t("All chapters so far")}
            </button>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto p-4">
            {charGraphError ? (
              <div className="flex items-start gap-2 rounded-xl border border-red-500/25 bg-red-500/8 p-3 text-sm text-red-500">
                <CircleAlert size={15} className="mt-0.5 shrink-0" />
                <span>{charGraphError}</span>
              </div>
            ) : charGraphLoading && !charGraphMermaid ? (
              <div className="flex items-center justify-center gap-2 py-12 text-sm text-[var(--muted-foreground)]">
                <Loader2 size={16} className="animate-spin" /> {t("Generating character map…")}
              </div>
            ) : (
              <>
                {charGraphMermaid && (
                  <div className="mb-4 overflow-x-auto rounded-xl border border-[var(--border)] bg-[var(--background)] p-3">
                    <Mermaid chart={charGraphMermaid} />
                  </div>
                )}
                {charGraphNodes.length > 0 && (
                  <div>
                    <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-[var(--muted-foreground)]">
                      {t("Characters")} ({charGraphNodes.length})
                    </p>
                    <div className="space-y-2">
                      {charGraphNodes.map((node) => (
                        <div key={node.id} className="rounded-lg border border-[var(--border)] bg-[var(--background)] p-3">
                          <div className="text-sm font-medium">{node.name}</div>
                          {node.aliases.length > 0 && (
                            <div className="mt-0.5 text-[11px] text-[var(--muted-foreground)]">
                              {t("Also known as")}: {node.aliases.join(", ")}
                            </div>
                          )}
                          {node.description && (
                            <p className="mt-1 text-xs leading-5 text-[var(--muted-foreground)]">{node.description}</p>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </aside>
      )}

      {selectionMenu && (
        <div
          className="fixed z-[90] flex items-center gap-1 rounded-xl border border-white/10 bg-[#171513] p-1.5 text-white shadow-2xl"
          style={{ left: selectionMenu.left, top: selectionMenu.top } as CSSProperties}
          onMouseDown={(event) => event.preventDefault()}
        >
          <button type="button" onClick={() => void runTranslation()} className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs hover:bg-white/10"><Languages size={14} /> {t("Translate")}</button>
          <button type="button" onClick={() => void recordSelection()} className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs hover:bg-white/10"><Quote size={14} /> {t("Record")}</button>
          <button type="button" disabled={selectionBusy} onClick={() => void saveWord()} className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs hover:bg-white/10 disabled:opacity-50">{selectionBusy ? <Loader2 size={14} className="animate-spin" /> : <BookPlus size={14} />} {t("Vocab")}</button>
          <button type="button" onClick={openQuery} className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs hover:bg-white/10"><MessageCircleQuestion size={14} /> {t("Query")}</button>
          <button type="button" onClick={() => setSelectionMenu(null)} className="rounded-lg p-1.5 hover:bg-white/10"><X size={13} /></button>
        </div>
      )}

      {dictPopup && (
        <DictionaryPanel
          word={dictPopup.word}
          anchor={{
            left: dictPopup.anchorRect.left,
            right: dictPopup.anchorRect.right,
            top: dictPopup.anchorRect.top,
            bottom: dictPopup.anchorRect.bottom,
          }}
          loading={dictBusy}
          result={dictResult}
          error={dictError}
          onLookup={() => void lookupDictionary(dictPopup.word, dictPopup.context)}
          onTranslate={() => void translateDictWord()}
          onClose={closeDictPopup}
          onSaveToVocabulary={() => void saveDictWord()}
        />
      )}

      {selectionAction && (
        <ModalShell labelledBy="selection-action-title" onClose={() => { if (!selectionBusy) setSelectionAction(null); }}>
          <div className="w-full max-w-2xl rounded-2xl border border-[var(--border)] bg-[var(--card)] p-6 shadow-2xl">
            <div className="flex items-center justify-between">
              <h2 id="selection-action-title" className="flex items-center gap-2 text-lg font-semibold">
                {selectionAction === "translate" ? <Languages size={19} /> : <FileSearch size={19} />}
                {selectionAction === "translate" ? t("Translation") : t("Query with LLM + Search")}
              </h2>
              <button type="button" disabled={selectionBusy} onClick={() => setSelectionAction(null)} className="rounded-lg p-2 hover:bg-[var(--muted)]"><X size={17} /></button>
            </div>
            {selectionAction === "query" && !selectionResult && (
              <>
                <p className="mt-4 line-clamp-4 rounded-xl bg-[var(--muted)]/55 p-3 font-serif text-sm leading-6">{queryTextRef.current}</p>
                <label className="mt-4 block text-xs font-medium text-[var(--muted-foreground)]">{t("What do you want to know about this passage?")}</label>
                <textarea value={selectionQuestion} onChange={(event) => setSelectionQuestion(event.target.value)} placeholder={t("Explain, verify, add context, or investigate a detail…")} className="mt-2 min-h-24 w-full resize-y rounded-xl border border-[var(--border)] bg-[var(--background)] p-3 text-sm outline-none focus:border-[var(--primary)]" />
                <button type="button" disabled={selectionBusy} onClick={() => void runQuery()} className="mt-4 inline-flex items-center gap-2 rounded-xl bg-[var(--primary)] px-4 py-2 text-sm font-medium text-[var(--primary-foreground)] disabled:opacity-60">{selectionBusy && <Loader2 size={15} className="animate-spin" />} {t("Search and explain")}</button>
              </>
            )}
            {(selectionResult || selectionBusy) && (
              <div className="mt-5 max-h-[55vh] overflow-y-auto rounded-xl border border-[var(--border)] bg-[var(--background)] p-4 text-sm leading-7">
                {selectionBusy ? <div className="flex items-center gap-2 text-[var(--muted-foreground)]"><Loader2 size={16} className="animate-spin" /> {t("Thinking…")}</div> : <MarkdownRenderer content={selectionResult} variant="prose" />}
              </div>
            )}
          </div>
        </ModalShell>
      )}

      {focusOpen && currentSection && currentRequiresFocusCheck && (
        <ModalShell labelledBy="focus-check-title" onClose={() => { if (!focusBusy) setFocusOpen(false); }}>
          <div className="w-full max-w-2xl rounded-3xl border border-[var(--border)] bg-[var(--card)] p-7 shadow-2xl">
            <div className="flex items-start gap-4">
              <div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl ${focusResult?.passed ? "bg-emerald-500/12 text-emerald-500" : focusResult && !focusResult.passed ? "bg-amber-500/12 text-amber-500" : "bg-[var(--primary)]/12 text-[var(--primary)]"}`}>
                {focusResult?.passed ? <BookCheck size={23} /> : <Sparkles size={22} />}
              </div>
              <div>
                <h2 id="focus-check-title" className="text-xl font-semibold">{t("Focus-Check")}</h2>
                <p className="mt-1 text-sm text-[var(--muted-foreground)]">{currentSection.title}</p>
              </div>
            </div>

            {!focusResult ? (
              <>
                <p className="mt-6 text-sm leading-6 text-[var(--muted-foreground)]">{t("Summarize the key points in your own words.")}</p>
                <label className="mt-5 block text-sm font-medium">{t("What are the main ideas or takeaways?")}</label>
                <textarea value={focusSummary} onChange={(event) => { setFocusSummary(event.target.value); setFocusValidationError(null); }} className="mt-2 min-h-28 w-full resize-y rounded-xl border border-[var(--border)] bg-[var(--background)] p-3 text-sm leading-6 outline-none focus:border-[var(--primary)]" />
                <p className="mt-1 text-right text-[11px] text-[var(--muted-foreground)]">{focusSummary.trim().length}/20 {t("characters minimum")}</p>
                <label className="mt-4 block text-sm font-medium">{t("Additional notes (optional)")}</label>
                <textarea value={focusReflection} onChange={(event) => { setFocusReflection(event.target.value); setFocusValidationError(null); }} className="mt-2 min-h-24 w-full resize-y rounded-xl border border-[var(--border)] bg-[var(--background)] p-3 text-sm leading-6 outline-none focus:border-[var(--primary)]" />
                <p className="mt-1 text-right text-[11px] text-[var(--muted-foreground)]">{t("optional")}</p>
                <div className="mt-5 flex items-center justify-between gap-4">
                  <div>
                    <p className="text-xs text-red-500">{focusValidationError}</p>
                    {focusHistory.length > 0 && <p className="mt-1 text-xs text-[var(--muted-foreground)]">{t("{{count}} previous attempts are saved.", { count: focusHistory.length })}</p>}
                  </div>
                  <div className="flex shrink-0 gap-2">
                    <button type="button" disabled={focusBusy} onClick={() => void skipCurrentSection()} className="rounded-xl border border-[var(--border)] px-4 py-2.5 text-sm font-medium disabled:opacity-45">{t("Skip section")}</button>
                    <button type="button" disabled={focusBusy} onClick={() => void submitFocusCheck()} className="inline-flex items-center gap-2 rounded-xl bg-[var(--primary)] px-5 py-2.5 text-sm font-medium text-[var(--primary-foreground)] disabled:opacity-45">{focusBusy && <Loader2 size={15} className="animate-spin" />} {focusBusy ? t("Checking…") : t("Submit Focus-Check")}</button>
                  </div>
                </div>
              </>
            ) : (
              <div className="mt-6">
                <div className={`rounded-2xl border p-5 ${focusResult.passed ? "border-emerald-500/25 bg-emerald-500/8" : "border-amber-500/25 bg-amber-500/8"}`}>
                  <div className="flex items-center justify-between gap-3">
                    <span className="font-semibold">{focusResult.passed ? t("Passed — continue reading") : t("Not yet — reread this section")}</span>
                    <span className="rounded-full bg-[var(--background)] px-3 py-1 text-xs font-semibold">{focusResult.score}/100</span>
                  </div>
                  <p className="mt-3 text-sm leading-6">{focusResult.feedback}</p>
                  {focusResult.missing_points.length > 0 && (
                    <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-[var(--muted-foreground)]">
                      {focusResult.missing_points.map((point) => <li key={point}>{point}</li>)}
                    </ul>
                  )}
                  {focusResult.prompts.length > 0 && (
                    <details className="mt-3">
                      <summary className="cursor-pointer text-xs text-[var(--muted-foreground)]">{t("Guiding questions")}</summary>
                      <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-[var(--muted-foreground)]">
                        {focusResult.prompts.map((p) => <li key={p}>{p}</li>)}
                      </ul>
                    </details>
                  )}
                </div>
                <div className="mt-6 flex flex-wrap justify-end gap-2">
                  {!focusResult.passed && <button type="button" onClick={() => { setFocusResult(null); setFocusValidationError(null); }} className="inline-flex items-center gap-2 rounded-xl border border-[var(--border)] px-4 py-2.5 text-sm font-medium"><RotateCcw size={15} /> {t("Edit and try again")}</button>}
                  {!focusResult.passed && <button type="button" onClick={() => void skipCurrentSection()} className="rounded-xl border border-[var(--border)] px-4 py-2.5 text-sm font-medium">{t("Skip section")}</button>}
                  <button type="button" onClick={continueAfterFocus} className="inline-flex items-center gap-2 rounded-xl bg-[var(--primary)] px-5 py-2.5 text-sm font-medium text-[var(--primary-foreground)]">
                    {t("Continue reading")} <ChevronRight size={16} />
                  </button>
                </div>
                <FocusHistoryPanel history={focusHistory} />
              </div>
            )}
          </div>
        </ModalShell>
      )}
    </div>
  );
}
