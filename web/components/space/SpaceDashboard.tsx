"use client";

import { PageHeader, PAGE_SECTION_TITLE_CLASS, pageGridClass } from '@/components/layout/FeaturePage'
import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import { useUiLayoutLabel } from "@/features/ui-layout/tokens";
import { useCapabilityFilter } from "@/features/capabilities/useCapabilityCatalog";
import {
  ArrowUpRight,
  Github,
  Library,
} from "lucide-react";
import {
  DASHBOARD_GROUPS,
  visibleGroups,
  type DashboardGroup,
  type DashboardItem,
  type Lang,
  type DashKey,
} from "@/components/space/dashboard-groups";

import { scopedUrl } from "@/lib/workspace-scope";

/**
 * Learning Space dashboard — the hub of `/space`.
 *
 * Replaces the old "land directly in a section behind a side list" flow with a
 * single overview the learner enters from. Each tile is a real entry point that
 * shows a live count so the space feels inhabited, then routes into the full
 * section page (which keeps the mini-nav for lateral movement).
 */


export default function SpaceDashboard({
  title,
  description,
  icon = Library,
  groups: shelves = DASHBOARD_GROUPS,
  onNavigate,
}: {
  title?: string;
  description?: string;
  icon?: typeof Library;
  /** The shelves this hub opens onto; the workspace's materials by default. */
  groups?: DashboardGroup[];
  onNavigate?: (href: string) => void;
} = {}) {
  const { i18n } = useTranslation();
  const spaceLabel = useUiLayoutLabel("space");
  const zh = i18n.language?.toLowerCase().startsWith("zh");
  const tr = useCallback((l: Lang) => (zh ? l.zh : l.en), [zh]);

  const [counts, setCounts] = useState<Partial<Record<DashKey, number>>>({});

  const capabilityAvailable = useCapabilityFilter();
  const groups = useMemo(
    () => visibleGroups(shelves, capabilityAvailable),
    [shelves, capabilityAvailable]
  );

  useEffect(() => {
    let cancelled = false;
    // Each tile loads independently so one slow/failed endpoint never blanks
    // the whole dashboard.
    for (const item of shelves.flatMap(group => group.items)) {
      if (!item.load) continue;
      item
        .load()
        .then(n => {
          if (!cancelled) setCounts(prev => ({ ...prev, [item.key]: n }));
        })
        .catch(() => {
          /* leave undefined → tile just omits the count */
        });
    }
    return () => {
      cancelled = true;
    };
  }, [shelves]);

  return (
    <div>
      <PageHeader
        icon={icon}
        title={title ?? spaceLabel}
        description={description ?? tr({
            zh: "你的对话、智能体、笔记与题目，集中在一处 —— 从这里进入。",
            en: "Your conversations, agents, notebooks, and questions in one place — enter from here.",
          })}
      />

      <div className="space-y-9">
        {groups.map(group => (
          <section key={group.label.en}>
            <h2 className={`mb-3 ${PAGE_SECTION_TITLE_CLASS}`}>
              {tr(group.label)}
            </h2>
            <div className={pageGridClass(2)}>
              {group.items.map(item => (
                <DashboardCard
                  key={item.key}
                  item={item}
                  count={counts[item.key]}
                  onNavigate={onNavigate}
                  tr={tr}
                />
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}

function DashboardCard({
  item,
  count,
  tr,
  onNavigate,
}: {
  item: DashboardItem;
  count: number | undefined;
  onNavigate?: (href: string) => void;
  tr: (l: Lang) => string;
}) {
  const Icon = item.icon;
  const loaded = count !== undefined;
  const formatted = useMemo(
    () => (loaded ? count.toLocaleString() : ""),
    [loaded, count]
  );

  return (
    <Link
      href={onNavigate ? `/preview#resource/${encodeURIComponent(item.href)}` : item.key === "journal" ? scopedUrl(item.href) : item.href}
      onClick={onNavigate ? event => {
        event.preventDefault();
        onNavigate(item.href);
      } : undefined}
      className="group relative flex flex-col rounded-xl border border-[var(--border)] bg-[var(--card)] p-4 transition-all duration-150 hover:-translate-y-0.5 hover:border-[var(--foreground)]/20 hover:shadow-[0_6px_20px_-12px_rgba(0,0,0,0.25)]"
    >
      <div className="flex items-start gap-3">
        <span
          aria-hidden
          className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${item.tile}`}
        >
          <Icon size={18} strokeWidth={1.7} />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-[14.5px] font-medium leading-tight tracking-tight text-[var(--foreground)]">
            {tr(item.title)}
          </h3>
          {item.unit ? (
            <div className="mt-1 flex items-baseline gap-1.5">
              {loaded ? (
                <>
                  <span className="text-[20px] font-semibold leading-none tabular-nums text-[var(--foreground)]">
                    {formatted}
                  </span>
                  <span className="text-[12px] text-[var(--muted-foreground)]">
                    {tr(item.unit)}
                  </span>
                </>
              ) : (
                <span className="my-[3px] h-3.5 w-12 animate-pulse rounded bg-[var(--muted)]" />
              )}
            </div>
          ) : null}
        </div>
        <ArrowUpRight
          size={16}
          className="shrink-0 text-[var(--muted-foreground)]/40 transition-colors group-hover:text-[var(--foreground)]"
        />
      </div>
      <p className="mt-3 text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
        {tr(item.blurb)}
      </p>
      {item.credit ? (
        <span className="mt-2.5 inline-flex items-center gap-1 self-start text-[11px] leading-none text-[var(--muted-foreground)] opacity-60">
          <Github size={11} strokeWidth={1.8} aria-hidden />
          {item.credit}
        </span>
      ) : null}
    </Link>
  );
}
