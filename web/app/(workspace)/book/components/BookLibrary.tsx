"use client";

import { useMemo, useState } from "react";
import {
  BookOpen,
  Clock3,
  FileText,
  GraduationCap,
  Layers,
  Library,
  Loader2,
  Plus,
  Search,
  Sparkles,
  Trash2,
} from "lucide-react";
import type { CSSProperties } from "react";
import { useTranslation } from "react-i18next";

import type { Book, BookStatus } from "@/lib/book-types";

const STATUS_STYLES: Record<
  BookStatus,
  { label: string; className: string; dot: string }
> = {
  draft: {
    label: "Draft",
    className:
      "bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300",
    dot: "bg-amber-500",
  },
  spine_ready: {
    label: "Outline",
    className: "bg-sky-50 text-sky-700 dark:bg-sky-500/10 dark:text-sky-300",
    dot: "bg-sky-500",
  },
  compiling: {
    label: "Compiling",
    className:
      "bg-violet-50 text-violet-700 dark:bg-violet-500/10 dark:text-violet-300",
    dot: "bg-violet-500 animate-pulse",
  },
  ready: {
    label: "Ready",
    className:
      "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300",
    dot: "bg-emerald-500",
  },
  error: {
    label: "Error",
    className:
      "bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300",
    dot: "bg-rose-500",
  },
  archived: {
    label: "Archived",
    className:
      "bg-zinc-100 text-zinc-600 dark:bg-zinc-500/10 dark:text-zinc-400",
    dot: "bg-zinc-400",
  },
};

function relativeTime(
  seconds: number,
  t: (key: string, options?: Record<string, unknown>) => string,
): string {
  if (!seconds || Number.isNaN(seconds)) return "";
  const diff = Date.now() / 1000 - seconds;
  if (diff < 60) return t("just now");
  const mins = Math.floor(diff / 60);
  if (mins < 60) return t("{{count}}m ago", { count: mins });
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return t("{{count}}h ago", { count: hrs });
  const days = Math.floor(hrs / 24);
  if (days < 30) return t("{{count}}d ago", { count: days });
  const months = Math.floor(days / 30);
  if (months < 12) return t("{{count}}mo ago", { count: months });
  return t("{{count}}y ago", { count: Math.floor(months / 12) });
}

// Stable, deterministic palette per book id so each cover feels distinct
// without resorting to placeholder letters.
const COVER_PALETTES: Array<{
  base: string;
  accent: string;
  spine: string;
  glow: string;
}> = [
  {
    base: "linear-gradient(135deg, #fdf3e7 0%, #f6dcc1 55%, #e9b88a 100%)",
    accent: "#c97a3f",
    spine: "rgba(168, 87, 35, 0.55)",
    glow: "rgba(255, 198, 140, 0.6)",
  },
  {
    base: "linear-gradient(135deg, #eef5ff 0%, #cfe1f7 55%, #9ec0e8 100%)",
    accent: "#3b6fb6",
    spine: "rgba(43, 89, 156, 0.55)",
    glow: "rgba(150, 196, 255, 0.55)",
  },
  {
    base: "linear-gradient(135deg, #f6efff 0%, #e2cff8 55%, #c2a3ec 100%)",
    accent: "#8254cf",
    spine: "rgba(96, 56, 159, 0.55)",
    glow: "rgba(204, 162, 255, 0.55)",
  },
  {
    base: "linear-gradient(135deg, #ecf8f0 0%, #c8eddc 55%, #93d6b6 100%)",
    accent: "#3a9c72",
    spine: "rgba(36, 117, 80, 0.55)",
    glow: "rgba(160, 232, 199, 0.55)",
  },
  {
    base: "linear-gradient(135deg, #fff4e9 0%, #fcd9b7 55%, #f4ad7d 100%)",
    accent: "#d2683a",
    spine: "rgba(178, 75, 35, 0.55)",
    glow: "rgba(255, 195, 145, 0.6)",
  },
  {
    base: "linear-gradient(135deg, #f1efff 0%, #d6d2f6 55%, #a7a1e6 100%)",
    accent: "#5d54c6",
    spine: "rgba(64, 56, 158, 0.55)",
    glow: "rgba(189, 184, 255, 0.55)",
  },
];

function paletteFor(id: string) {
  let hash = 0;
  for (let i = 0; i < id.length; i++) {
    hash = (hash * 31 + id.charCodeAt(i)) >>> 0;
  }
  return COVER_PALETTES[hash % COVER_PALETTES.length];
}

export interface BookLibraryProps {
  books: Book[];
  loading: boolean;
  onNewBook: () => void;
  onSelectBook: (id: string) => void;
  onDeleteBook: (id: string) => void;
  onLearn?: (book: Book) => void;
}

export default function BookLibrary({
  books,
  loading,
  onNewBook,
  onSelectBook,
  onDeleteBook,
  onLearn,
}: BookLibraryProps) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return books;
    return books.filter((b) => {
      const t = (b.title || "").toLowerCase();
      const d = (b.description || "").toLowerCase();
      return t.includes(q) || d.includes(q);
    });
  }, [books, query]);

  const stats = useMemo(() => {
    const total = books.length;
    const ready = books.filter((b) => b.status === "ready").length;
    const inProgress = books.filter(
      (b) =>
        b.status === "compiling" ||
        b.status === "spine_ready" ||
        b.status === "draft",
    ).length;
    const chapters = books.reduce((acc, b) => acc + (b.chapter_count || 0), 0);
    return { total, ready, inProgress, chapters };
  }, [books]);

  return (
    <div className="flex h-full min-h-full flex-col overflow-hidden bg-[var(--background)]">
      {/* Header bar */}
      <header className="flex shrink-0 items-center justify-between border-b border-[var(--border)] px-6 py-3">
        <div className="flex items-center gap-3">
          <Library size={18} className="text-[var(--muted-foreground)]" />
          <div>
            <div className="text-sm font-semibold text-[var(--foreground)]">
              {t("Books")}
            </div>
            <div className="text-xs text-[var(--muted-foreground)]">
              {t("Generate, browse and study your AI-authored books.")}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative hidden items-center sm:flex">
            <Search
              size={13}
              className="pointer-events-none absolute left-2.5 text-[var(--muted-foreground)]/70"
            />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t("Search books")}
              className="h-8 w-56 rounded-md border border-[var(--border)] bg-[var(--secondary)]/30 pl-7 pr-2.5 text-xs text-[var(--foreground)] placeholder:text-[var(--muted-foreground)]/60 focus:border-[var(--primary)]/40 focus:outline-none"
            />
          </div>
          <button
            type="button"
            onClick={onNewBook}
            className="inline-flex items-center gap-1.5 rounded-md bg-[var(--primary)] px-3 py-1.5 text-xs font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90"
          >
            <Plus size={13} />
            {t("New book")}
          </button>
        </div>
      </header>

      <main className="flex-1 overflow-y-auto px-6 py-6">
        {/* Stats row */}
        <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatCard
            icon={<BookOpen size={14} />}
            label={t("Total books")}
            value={stats.total}
          />
          <StatCard
            icon={<Sparkles size={14} />}
            label={t("Ready")}
            value={stats.ready}
            accent="text-emerald-600 dark:text-emerald-400"
          />
          <StatCard
            icon={<Loader2 size={14} />}
            label={t("In progress")}
            value={stats.inProgress}
            accent="text-violet-600 dark:text-violet-400"
          />
          <StatCard
            icon={<Layers size={14} />}
            label={t("Chapters")}
            value={stats.chapters}
          />
        </div>

        {/* Section heading */}
        <div className="mb-3 flex items-end justify-between">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--muted-foreground)]">
              {t("My library")}
            </div>
            <div className="text-xs text-[var(--muted-foreground)]/80">
              {t("{{shown}} of {{total}} books", {
                shown: filtered.length,
                total: books.length,
              })}
              {query ? ` · ${t("matching “{{query}}”", { query })}` : ""}
            </div>
          </div>
        </div>

        {loading ? (
          <div className="flex items-center justify-center gap-2 py-20 text-sm text-[var(--muted-foreground)]">
            <Loader2 size={16} className="animate-spin" />
            {t("Loading books…")}
          </div>
        ) : books.length === 0 ? (
          <EmptyState onNewBook={onNewBook} />
        ) : filtered.length === 0 ? (
          <div className="rounded-xl border border-dashed border-[var(--border)] bg-[var(--secondary)]/30 px-6 py-12 text-center text-sm text-[var(--muted-foreground)]">
            {t("No books match “{{query}}”.", { query })}
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {filtered.map((book) => {
              const isPendingDelete = pendingDeleteId === book.id;
              const status = STATUS_STYLES[book.status] || STATUS_STYLES.draft;
              const palette = paletteFor(book.id);
              const coverStyle: CSSProperties = { background: palette.base };
              const glowStyle: CSSProperties = {
                background: `radial-gradient(circle at 80% 25%, ${palette.glow} 0%, transparent 60%)`,
              };

              return (
                <div
                  key={book.id}
                  role="button"
                  tabIndex={0}
                  onClick={() => onSelectBook(book.id)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      onSelectBook(book.id);
                    }
                  }}
                  className="group relative flex cursor-pointer flex-col overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--card)]/70 transition-all hover:-translate-y-0.5 hover:border-[var(--primary)]/40 hover:shadow-md"
                >
                  {/* Cover */}
                  <div
                    className="relative h-28 w-full overflow-hidden"
                    style={coverStyle}
                  >
                    {/* Soft glow accent */}
                    <div
                      className="pointer-events-none absolute inset-0"
                      style={glowStyle}
                    />
                    {/* Stylized "book spine" stripes on the left edge */}
                    <div
                      className="pointer-events-none absolute inset-y-0 left-0 w-2"
                      style={{
                        background: `linear-gradient(180deg, ${palette.spine} 0%, transparent 100%)`,
                      }}
                    />
                    <div
                      className="pointer-events-none absolute inset-y-3 left-3.5 w-px"
                      style={{ background: palette.spine, opacity: 0.45 }}
                    />
                    {/* Decorative diagonal line pattern */}
                    <svg
                      className="pointer-events-none absolute inset-0 h-full w-full opacity-[0.07]"
                      xmlns="http://www.w3.org/2000/svg"
                      aria-hidden
                    >
                      <defs>
                        <pattern
                          id={`diag-${book.id}`}
                          width="14"
                          height="14"
                          patternUnits="userSpaceOnUse"
                          patternTransform="rotate(35)"
                        >
                          <line
                            x1="0"
                            y1="0"
                            x2="0"
                            y2="14"
                            stroke="currentColor"
                            strokeWidth="1"
                          />
                        </pattern>
                      </defs>
                      <rect
                        width="100%"
                        height="100%"
                        fill={`url(#diag-${book.id})`}
                      />
                    </svg>
                    <BookOpen
                      size={20}
                      className="absolute bottom-3 right-3 opacity-50"
                      style={{ color: palette.accent }}
                    />

                    <span
                      className={`absolute left-4 top-3 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider ${status.className}`}
                    >
                      <span
                        className={`h-1.5 w-1.5 rounded-full ${status.dot}`}
                      />
                      {t(status.label)}
                    </span>
                    <button
                      type="button"
                      onClick={(event) => {
                        event.stopPropagation();
                        if (isPendingDelete) {
                          onDeleteBook(book.id);
                          setPendingDeleteId(null);
                        } else {
                          setPendingDeleteId(book.id);
                        }
                      }}
                      title={
                        isPendingDelete
                          ? t("Click again to confirm")
                          : t("Delete book")
                      }
                      className={`absolute right-2 top-2 rounded-md p-1.5 transition-colors ${
                        isPendingDelete
                          ? "bg-rose-500/15 text-rose-600 dark:text-rose-400"
                          : "bg-white/60 text-[var(--muted-foreground)] opacity-0 backdrop-blur-sm hover:bg-rose-500/10 hover:text-rose-600 group-hover:opacity-100 dark:bg-black/30 dark:hover:text-rose-400"
                      }`}
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>

                  {/* Body */}
                  <div className="flex flex-1 flex-col gap-2 p-4">
                    <div
                      className="line-clamp-2 text-sm font-semibold text-[var(--foreground)]"
                      title={book.title || t("Untitled book")}
                    >
                      {book.title || t("Untitled book")}
                    </div>
                    <p className="line-clamp-3 flex-1 text-xs leading-relaxed text-[var(--muted-foreground)]">
                      {book.description ||
                        t(
                          "No description yet. Open the book to view its outline.",
                        )}
                    </p>
                    <div className="mt-auto flex items-center justify-between text-[10px] text-[var(--muted-foreground)]/80">
                      <div className="flex items-center gap-3">
                        <span className="inline-flex items-center gap-1">
                          <Layers size={11} />
                          {t("{{count}} ch", {
                            count: book.chapter_count || 0,
                          })}
                        </span>
                        <span className="inline-flex items-center gap-1">
                          <FileText size={11} />
                          {t("{{count}} pages", {
                            count: book.page_count || 0,
                          })}
                        </span>
                      </div>
                      <span className="inline-flex items-center gap-1">
                        <Clock3 size={11} />
                        {relativeTime(book.updated_at, t) || "—"}
                      </span>
                    </div>
                    {onLearn && book.status === "ready" && (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          onLearn(book);
                        }}
                        className="mt-2 inline-flex items-center gap-1 rounded-md bg-[var(--primary)] px-3 py-1.5 text-xs font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90"
                      >
                        <GraduationCap size={13} />
                        {t("Start learning")}
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </main>
    </div>
  );
}

function StatCard({
  icon,
  label,
  value,
  accent,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
  accent?: string;
}) {
  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--secondary)]/40 px-4 py-3">
      <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-[var(--muted-foreground)]">
        <span className={accent || "text-[var(--muted-foreground)]"}>
          {icon}
        </span>
        {label}
      </div>
      <div
        className={`mt-1 text-xl font-semibold ${accent || "text-[var(--foreground)]"}`}
      >
        {value}
      </div>
    </div>
  );
}

function EmptyState({ onNewBook }: { onNewBook: () => void }) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col items-center justify-center gap-4 rounded-xl border border-dashed border-[var(--border)] bg-[var(--secondary)]/30 px-8 py-16 text-center">
      <BookOpen size={28} className="text-[var(--muted-foreground)]/50" />
      <div>
        <p className="text-base font-medium text-[var(--foreground)]">
          {t("No books yet")}
        </p>
        <p className="mt-1 text-sm text-[var(--muted-foreground)]">
          {t(
            "Create your first AI-generated book from a knowledge base, chat selections or simply a topic.",
          )}
        </p>
      </div>
      <button
        type="button"
        onClick={onNewBook}
        className="inline-flex items-center gap-1.5 rounded-md bg-[var(--primary)] px-3 py-1.5 text-sm font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90"
      >
        <Plus size={14} />
        {t("New book")}
      </button>
    </div>
  );
}
