"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  BookOpen,
  Bot,
  ClipboardList,
  Layers,
  Library,
  MessageSquare,
  Network,
  NotebookPen,
  PenLine,
  Workflow,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { apiFetch, apiUrl } from "@/lib/api";
import { L1View } from "@/components/memory/MemorySection";

type Surface =
  | "chat"
  | "notebook"
  | "quiz"
  | "kb"
  | "book"
  | "partner"
  | "cowriter";

interface NavEntry {
  key: Surface;
  label: string;
  icon: LucideIcon;
}

const L1_NAV: NavEntry[] = [
  { key: "chat", icon: MessageSquare, label: "Chat" },
  { key: "notebook", icon: NotebookPen, label: "Notebook" },
  { key: "quiz", icon: ClipboardList, label: "Quiz" },
  { key: "kb", icon: BookOpen, label: "Knowledge base" },
  { key: "book", icon: Library, label: "Book" },
  { key: "partner", icon: Bot, label: "Partner" },
  { key: "cowriter", icon: PenLine, label: "Co-writer" },
];

interface SnapshotResponse {
  surface: Surface;
  entities: unknown[];
  pending_changes: unknown[];
}

export interface MemoryL1WorkbenchProps {
  initialSurface?: Surface;
  initialFocusRef?: string;
}

export default function MemoryL1Workbench({
  initialSurface,
  initialFocusRef,
}: MemoryL1WorkbenchProps) {
  const { t } = useTranslation();
  // ``initialSurface`` and ``initialFocusRef`` seed the picker + entity
  // highlight on first mount. The URL only drives initial state; once the
  // user clicks around the rail it's all local state again.
  const [surface, setSurface] = useState<Surface>(initialSurface || "notebook");
  const [counts, setCounts] = useState<Record<Surface, number>>(
    {} as Record<Surface, number>,
  );
  const [pending, setPending] = useState<Record<Surface, number>>(
    {} as Record<Surface, number>,
  );
  const [focusRef, setFocusRef] = useState<string | null>(
    initialFocusRef ?? null,
  );
  const [toast, setToast] = useState("");

  // Fetch counts + pending badges for the left rail in parallel.
  const loadCounts = useCallback(async () => {
    const entries = await Promise.all(
      L1_NAV.map(async ({ key }) => {
        try {
          const res = await apiFetch(apiUrl(`/api/v1/memory/snapshot/${key}`));
          const data = (await res.json()) as SnapshotResponse;
          return [
            key,
            data?.entities?.length ?? 0,
            data?.pending_changes?.length ?? 0,
          ] as const;
        } catch {
          return [key, 0, 0] as const;
        }
      }),
    );
    setCounts(
      Object.fromEntries(entries.map(([k, n]) => [k, n])) as Record<
        Surface,
        number
      >,
    );
    setPending(
      Object.fromEntries(entries.map(([k, , p]) => [k, p])) as Record<
        Surface,
        number
      >,
    );
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadCounts();
  }, [loadCounts]);

  // Re-fetch counts when the tab regains focus so the rail stays in sync.
  useEffect(() => {
    const refetch = () => {
      if (typeof document !== "undefined" && document.hidden) return;
      void loadCounts();
    };
    window.addEventListener("focus", refetch);
    document.addEventListener("visibilitychange", refetch);
    return () => {
      window.removeEventListener("focus", refetch);
      document.removeEventListener("visibilitychange", refetch);
    };
  }, [loadCounts]);

  useEffect(() => {
    if (!toast) return;
    const id = setTimeout(() => setToast(""), 2500);
    return () => clearTimeout(id);
  }, [toast]);

  const nicelabel = useMemo(() => {
    const entry = L1_NAV.find((n) => n.key === surface);
    return entry ? t(entry.label) : surface;
  }, [surface, t]);

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 px-6 py-4 md:px-10">
      <div className="flex items-center justify-between gap-3">
        <Breadcrumb label={nicelabel} t={t} />
        <LayerSwitcher t={t} />
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-[180px_minmax(0,1fr)] gap-4">
        {/* Left rail */}
        <aside className="min-h-0 overflow-y-auto rounded-2xl border border-[var(--border)] bg-[var(--card)] p-2">
          <ul className="space-y-0.5">
            {L1_NAV.map(({ key, icon: Icon, label }) => {
              const active = key === surface;
              const c = counts[key];
              const p = pending[key];
              return (
                <li key={key}>
                  <button
                    type="button"
                    onClick={() => {
                      setSurface(key);
                      setFocusRef(null);
                    }}
                    className={
                      "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[12.5px] transition " +
                      (active
                        ? "bg-[var(--muted)] text-[var(--foreground)]"
                        : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]/60 hover:text-[var(--foreground)]")
                    }
                  >
                    <Icon className="h-3.5 w-3.5 shrink-0" />
                    <span className="flex-1 truncate">{t(label)}</span>
                    {p > 0 ? (
                      <span
                        className="rounded-full bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-600 dark:text-amber-400"
                        title={t("{{n}} pending", { n: p })}
                      >
                        {p}
                      </span>
                    ) : typeof c === "number" ? (
                      <span className="rounded-full bg-[var(--background)] px-1.5 py-0.5 text-[10px] text-[var(--muted-foreground)]">
                        {c}
                      </span>
                    ) : null}
                  </button>
                </li>
              );
            })}
          </ul>
        </aside>

        {/* Center: snapshot / changes / kb-queries preview */}
        <section className="min-h-0 overflow-y-auto rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5">
          <L1View
            surface={surface}
            onSurfaceChange={(s) => {
              setSurface(s as Surface);
              setFocusRef(null);
            }}
            focusRef={focusRef}
            onClearFocus={() => setFocusRef(null)}
            onToast={setToast}
            t={t}
            compact
          />
        </section>
      </div>

      {toast && (
        <div className="self-start rounded-md border border-[var(--primary)]/30 bg-[var(--primary)]/10 px-3 py-1 text-[11.5px] text-[var(--primary)]">
          {toast}
        </div>
      )}
    </div>
  );
}

function LayerSwitcher({ t }: { t: (k: string) => string }) {
  // L1 is the current page, so it stays as a non-link pill; L2 + L3
  // link to their respective hubs.
  const entries: {
    key: "L1" | "L2" | "L3";
    href: string;
    icon: LucideIcon;
    label: string;
  }[] = [
    { key: "L1", href: "/memory/l1", icon: Layers, label: t("L1") },
    { key: "L2", href: "/memory/l2", icon: Workflow, label: t("L2") },
    { key: "L3", href: "/memory/l3", icon: Network, label: t("L3") },
  ];
  return (
    <nav className="flex items-center gap-0.5 rounded-full border border-[var(--border)] bg-[var(--card)] p-0.5">
      {entries.map(({ key, href, icon: Icon, label }) => {
        const active = key === "L1";
        if (active) {
          return (
            <span
              key={key}
              className="inline-flex items-center gap-1 rounded-full bg-[var(--muted)] px-2.5 py-0.5 text-[11.5px] font-medium text-[var(--foreground)]"
            >
              <Icon className="h-3 w-3" />
              {label}
            </span>
          );
        }
        return (
          <Link
            key={key}
            href={href}
            className="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11.5px] text-[var(--muted-foreground)] transition hover:bg-[var(--muted)]/60 hover:text-[var(--foreground)]"
          >
            <Icon className="h-3 w-3" />
            {label}
          </Link>
        );
      })}
    </nav>
  );
}

function Breadcrumb({ label, t }: { label: string; t: (k: string) => string }) {
  return (
    <div className="flex items-center gap-2 text-[12.5px]">
      <Link
        href="/memory"
        className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[var(--muted-foreground)] transition hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        {t("Memory")}
      </Link>
      <span className="text-[var(--muted-foreground)]">/</span>
      <span className="inline-flex items-center gap-1.5 text-[var(--foreground)]">
        <Layers className="h-3.5 w-3.5" />
        {t("L1 · Workspace mirror")}
      </span>
      <span className="text-[var(--muted-foreground)]">/</span>
      <span className="text-[var(--foreground)]">{label}</span>
    </div>
  );
}
