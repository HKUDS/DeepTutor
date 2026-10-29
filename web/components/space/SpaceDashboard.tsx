"use client";

import { PageHeader, PAGE_SECTION_TITLE_CLASS, pageGridClass } from '@/components/layout/FeaturePage'
import { useCallback, useEffect, useMemo, useState, type CSSProperties } from "react";
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


const COVERS: Record<DashKey, { paper: string; ink: string; label: string }> = {
  agents: { paper: "#eaf0f6", ink: "#2f4a68", label: "智能体" },
  chat_history: { paper: "#e7eef5", ink: "#2c4664", label: "历史" },
  notebooks: { paper: "#f6eee6", ink: "#684632", label: "笔记" },
  journal: { paper: "#e6f1eb", ink: "#2d5644", label: "日志" },
  question_bank: { paper: "#e8f0e4", ink: "#35562f", label: "题库" },
  knowledge: { paper: "#e8eaf3", ink: "#30385a", label: "知识" },
  personas: { paper: "#f6e9ed", ink: "#683c4a", label: "角色" },
  skills: { paper: "#eee9f5", ink: "#3d3664", label: "技能" },
  mcp: { paper: "#e6eef3", ink: "#2a485c", label: "服务" },
  cli_apps: { paper: "#f1eee8", ink: "#3e3a34", label: "命令" },
  memory: { paper: "#f6e9eb", ink: "#663e48", label: "记忆" },
  whisper: { paper: "#efeaf4", ink: "#4a3c60", label: "密语" },
};

function EntryCover({ id }: { id: DashKey }) {
  const cover = COVERS[id];
  return (
    <svg className="dt-entry-cover" viewBox="0 0 200 72" aria-hidden>
      <rect width="200" height="72" rx="8" fill={cover.paper} />
      <text
        x="16"
        y="44"
        fill={cover.ink}
        fontSize="18"
        fontWeight="500"
        fontFamily="ui-sans-serif, system-ui, sans-serif"
      >
        {cover.label}
      </text>
    </svg>
  );
}

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
      className="dt-entry-card group relative flex flex-col rounded-xl border border-[var(--border)] bg-[var(--card)] p-4 transition-all duration-150 hover:-translate-y-0.5 hover:border-[var(--foreground)]/20 hover:shadow-[0_6px_20px_-12px_rgba(0,0,0,0.25)]"
      style={{ "--dt-entry-ink": COVERS[item.key].ink } as CSSProperties}
    >
      <EntryCover id={item.key} />
      <div className="dt-entry-row flex items-start gap-3">
        <span
          aria-hidden
          className={`dt-entry-mark flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${item.tile}`}
        >
          <Icon size={18} strokeWidth={1.7} />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="dt-entry-title truncate text-[14.5px] font-medium leading-tight tracking-tight text-[var(--foreground)]">
            {tr(item.title)}
          </h3>
          {item.unit ? (
            <div className="dt-entry-count mt-1 flex items-baseline gap-1.5">
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
          className="dt-entry-go shrink-0 text-[var(--muted-foreground)]/40 transition-colors group-hover:text-[var(--foreground)]"
        />
      </div>
      <p className="dt-entry-blurb mt-3 text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
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
