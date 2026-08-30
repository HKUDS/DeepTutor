"use client";

import Link from "next/link";
import { Plus } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import {
  listReadingLibraryMaterials,
  listReadingWorkspaces,
} from "@/lib/reading-workspace-api";

/**
 * Header shared by the two reading views. Immersive Reading has exactly two
 * places to be — the collections you read in, and the library of everything
 * you have uploaded — so they sit under one title as two tabs rather than
 * behind a second sidebar.
 */
export function LibraryShell({
  view,
  collectionCount,
  materialCount,
  actionLabel,
  onAction,
  scopeChip,
  children,
}: {
  view: "collections" | "materials";
  collectionCount?: number;
  materialCount?: number;
  actionLabel: string;
  onAction: () => void;
  /** Rendered beside the title when this visit belongs to one course. */
  scopeChip?: ReactNode;
  children: ReactNode;
}) {
  const { t } = useTranslation();
  // Each view knows its own count; the other one is fetched once so the tabs
  // never show a blank where a number belongs.
  const [otherCount, setOtherCount] = useState<number | null>(null);

  useEffect(() => {
    let alive = true;
    const missing = view === "collections" ? materialCount : collectionCount;
    if (missing !== undefined) return;
    void (async () => {
      try {
        const value =
          view === "collections"
            ? (await listReadingLibraryMaterials()).materials.length
            : (await listReadingWorkspaces()).length;
        if (alive) setOtherCount(value);
      } catch {
        // A missing tab count is not worth an error state; the tab still works.
      }
    })();
    return () => {
      alive = false;
    };
  }, [collectionCount, materialCount, view]);

  const collections =
    collectionCount ??
    (view === "materials" ? (otherCount ?? undefined) : undefined);
  const materials =
    materialCount ??
    (view === "collections" ? (otherCount ?? undefined) : undefined);

  return (
    <main className="reading-v2 h-full min-h-0 overflow-y-auto bg-[var(--background)] text-[var(--foreground)]">
      <div className="mx-auto w-full max-w-[1180px] px-6 py-7 md:px-9 lg:py-9">
        <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2.5">
              <h1 className="font-serif text-[27px] font-semibold tracking-[-0.02em] md:text-[30px]">
                {t("Immersive Reading")}
              </h1>
              {scopeChip}
            </div>
            <p className="mt-1.5 max-w-2xl text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
              {t(
                "Put PDFs, web pages and lectures into one collection and read them with an AI companion that can always point back to the source.",
              )}
            </p>
          </div>
          <button
            type="button"
            onClick={onAction}
            className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3 text-[12px] font-semibold text-[var(--primary-foreground)] transition hover:opacity-90"
          >
            <Plus size={14} />
            {actionLabel}
          </button>
        </header>

        <nav className="mt-5 flex gap-1 border-b border-[var(--border)]">
          <ViewTab
            href="/reading"
            label={t("Collections")}
            count={collections}
            active={view === "collections"}
          />
          <ViewTab
            href="/reading/materials"
            label={t("Material library")}
            count={materials}
            active={view === "materials"}
          />
        </nav>

        {children}
      </div>
    </main>
  );
}

function ViewTab({
  href,
  label,
  count,
  active,
}: {
  href: string;
  label: string;
  count?: number;
  active: boolean;
}) {
  return (
    <Link
      href={href}
      className={`-mb-px flex items-center gap-1.5 border-b-2 px-3 pb-2.5 pt-2 text-[12.5px] transition ${
        active
          ? "border-[var(--primary)] font-semibold text-[var(--foreground)]"
          : "border-transparent text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
      }`}
    >
      {label}
      {typeof count === "number" && (
        <span className="text-[10.5px] tabular-nums text-[var(--muted-foreground)]">
          {count}
        </span>
      )}
    </Link>
  );
}
