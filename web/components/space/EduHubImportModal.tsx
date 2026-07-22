"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { useTranslation } from "react-i18next";
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  Download,
  ExternalLink,
  Loader2,
  RefreshCw,
  Search,
  Star,
  Store,
  Wand2,
  X,
} from "lucide-react";

import {
  fetchHubCatalog,
  fetchHubSkillDetail,
  installSkillFromHub,
  type HubSkillDetail,
  type HubSkillListing,
} from "@/lib/skills-api";

// Where the EduHub site lives, for "view on EduHub" links. The catalog
// response carries the authoritative origin; this only backstops a failed load.
const EDUHUB_FALLBACK = "https://eduhub.deeptutor.info";

// Lazy-load the markdown renderer so the heavier deps only ship when a user
// opens a skill's detail view (matches the Skills viewer in SkillsSection).
const SkillMarkdown = dynamic(
  () => import("@/components/common/SimpleMarkdownRenderer"),
  { ssr: false },
);

/** Drop the YAML frontmatter block so the detail view shows just the playbook. */
function stripFrontmatter(md: string): string {
  const match = md.match(/^---\s*\n[\s\S]*?\n---\s*\n?/);
  return match ? md.slice(match[0].length) : md;
}

type InstallState =
  | { kind: "installing" }
  | { kind: "done"; verdict: string }
  | { kind: "error"; message: string };

export default function EduHubImportModal({
  onClose,
  onInstalled,
  installedNames,
}: {
  onClose: () => void;
  onInstalled: () => void;
  /** Names of skills already installed locally — shown as "已导入". */
  installedNames?: Set<string>;
}) {
  const { i18n } = useTranslation();
  const zh = i18n.language?.toLowerCase().startsWith("zh");
  const tr = useCallback((cn: string, en: string) => (zh ? cn : en), [zh]);

  const [skills, setSkills] = useState<HubSkillListing[] | null>(null);
  const [webUrl, setWebUrl] = useState<string>(EDUHUB_FALLBACK);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  const [selected, setSelected] = useState<HubSkillListing | null>(null);
  const [detail, setDetail] = useState<HubSkillDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  const [installState, setInstallState] = useState<
    Record<string, InstallState>
  >({});
  // Slugs imported during this session, merged with the names passed from the
  // Skills list, so freshly-downloaded skills flip to "已导入" without a reload.
  const [installedLocal, setInstalledLocal] = useState<Set<string>>(
    () => new Set(installedNames ?? []),
  );

  const loadCatalog = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const catalog = await fetchHubCatalog({ limit: 100 });
      setSkills(catalog.skills);
      if (catalog.webUrl) setWebUrl(catalog.webUrl);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadCatalog();
  }, [loadCatalog]);

  // Escape closes (the detail view first, then the modal).
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key !== "Escape") return;
      if (selected) setSelected(null);
      else onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, selected]);

  const filtered = useMemo(() => {
    if (!skills) return [];
    const q = query.trim().toLowerCase();
    if (!q) return skills;
    return skills.filter(
      (s) =>
        s.name.toLowerCase().includes(q) ||
        s.slug.toLowerCase().includes(q) ||
        s.summary.toLowerCase().includes(q),
    );
  }, [skills, query]);

  const openDetail = useCallback(async (skill: HubSkillListing) => {
    setSelected(skill);
    setDetail(null);
    setDetailError(null);
    setDetailLoading(true);
    try {
      setDetail(await fetchHubSkillDetail(skill.slug));
    } catch (err) {
      setDetailError(err instanceof Error ? err.message : String(err));
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const install = useCallback(
    async (slug: string, opts?: { force?: boolean }) => {
      setInstallState((s) => ({ ...s, [slug]: { kind: "installing" } }));
      try {
        // The `eduhub:` hub is hardcoded so the install can never be redirected
        // to another registry, and the slug comes from our own proxied catalog.
        const result = await installSkillFromHub(`eduhub:${slug}`, {
          force: opts?.force,
        });
        setInstallState((s) => ({
          ...s,
          [slug]: { kind: "done", verdict: result.verdict.status },
        }));
        setInstalledLocal((prev) => new Set(prev).add(slug));
        onInstalled();
      } catch (err) {
        setInstallState((s) => ({
          ...s,
          [slug]: {
            kind: "error",
            message: err instanceof Error ? err.message : String(err),
          },
        }));
      }
    },
    [onInstalled],
  );

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay)] p-4"
      role="dialog"
      aria-modal="true"
      onClick={onClose}
    >
      <div
        className="flex h-[88vh] w-full max-w-5xl flex-col overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--background)] shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between gap-3 border-b border-[var(--border)] px-5 py-3">
          <div className="flex min-w-0 items-center gap-2">
            <Store
              size={15}
              className="shrink-0 text-[var(--muted-foreground)]"
            />
            <h3 className="truncate text-[14px] font-semibold text-[var(--foreground)]">
              {tr("从 EduHub 导入技能", "Import skills from EduHub")}
            </h3>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <a
              href={`${webUrl}/skills`}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[12px] text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            >
              <ExternalLink size={13} />
              {tr("在 EduHub 打开", "Open EduHub")}
            </a>
            <button
              onClick={onClose}
              aria-label={tr("关闭", "Close")}
              className="rounded-md p-1.5 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            >
              <X size={16} />
            </button>
          </div>
        </div>

        {selected ? (
          <DetailView
            skill={selected}
            detail={detail}
            loading={detailLoading}
            error={detailError}
            installState={installState[selected.slug]}
            installed={installedLocal.has(selected.slug)}
            webUrl={webUrl}
            tr={tr}
            onBack={() => setSelected(null)}
            onInstall={install}
          />
        ) : (
          <ListView
            skills={filtered}
            total={skills?.length ?? 0}
            loading={loading}
            error={error}
            query={query}
            installState={installState}
            installedLocal={installedLocal}
            tr={tr}
            onQueryChange={setQuery}
            onRetry={loadCatalog}
            onOpen={openDetail}
            onInstall={install}
          />
        )}
      </div>
    </div>
  );
}

// ── list view ──────────────────────────────────────────────────────────────

function ListView({
  skills,
  total,
  loading,
  error,
  query,
  installState,
  installedLocal,
  tr,
  onQueryChange,
  onRetry,
  onOpen,
  onInstall,
}: {
  skills: HubSkillListing[];
  total: number;
  loading: boolean;
  error: string | null;
  query: string;
  installState: Record<string, InstallState>;
  installedLocal: Set<string>;
  tr: (cn: string, en: string) => string;
  onQueryChange: (q: string) => void;
  onRetry: () => void;
  onOpen: (skill: HubSkillListing) => void;
  onInstall: (slug: string, opts?: { force?: boolean }) => void;
}) {
  return (
    <>
      {/* Search */}
      <div className="border-b border-[var(--border)] px-5 py-3">
        <div className="relative">
          <Search
            size={14}
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--muted-foreground)]"
          />
          <input
            value={query}
            onChange={(e) => onQueryChange(e.target.value)}
            placeholder={tr("搜索技能名称或描述…", "Search skills…")}
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--card)] py-2 pl-9 pr-3 text-[13px] text-[var(--foreground)] outline-none transition-colors placeholder:text-[var(--muted-foreground)]/70 focus:border-[var(--foreground)]/30"
          />
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        {loading ? (
          <div className="flex items-center justify-center py-16 text-[var(--muted-foreground)]">
            <Loader2 size={20} className="animate-spin" />
          </div>
        ) : error ? (
          <div className="mx-auto max-w-md rounded-lg border border-amber-500/20 bg-amber-500/10 px-4 py-3 text-center text-[12.5px] text-amber-700 dark:text-amber-400">
            <AlertTriangle size={16} className="mx-auto mb-1.5" />
            <p>{tr("无法连接 EduHub。", "Couldn't reach EduHub.")}</p>
            <p className="mt-0.5 break-words text-[11.5px] opacity-80">
              {error}
            </p>
            <button
              onClick={onRetry}
              className="mt-2.5 inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--card)] px-3 py-1 text-[12px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)]"
            >
              <RefreshCw size={12} />
              {tr("重试", "Retry")}
            </button>
          </div>
        ) : skills.length === 0 ? (
          <div className="py-16 text-center text-[13px] text-[var(--muted-foreground)]">
            {total === 0
              ? tr("EduHub 上暂时还没有技能。", "No skills on EduHub yet.")
              : tr("没有匹配的技能。", "No skills match your search.")}
          </div>
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2">
            {skills.map((skill) => (
              <SkillCard
                key={skill.slug}
                skill={skill}
                state={installState[skill.slug]}
                installed={installedLocal.has(skill.slug)}
                tr={tr}
                onOpen={() => onOpen(skill)}
                onInstall={onInstall}
              />
            ))}
          </ul>
        )}
      </div>
    </>
  );
}

function SkillCard({
  skill,
  state,
  installed,
  tr,
  onOpen,
  onInstall,
}: {
  skill: HubSkillListing;
  state?: InstallState;
  installed: boolean;
  tr: (cn: string, en: string) => string;
  onOpen: () => void;
  onInstall: (slug: string, opts?: { force?: boolean }) => void;
}) {
  return (
    <li
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen();
        }
      }}
      title={tr("查看详情", "View details")}
      className="group relative flex cursor-pointer flex-col rounded-xl border border-[var(--border)] bg-[var(--card)] p-4 shadow-sm transition-all hover:border-[var(--foreground)]/30 hover:shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]/40"
    >
      <div className="flex items-start gap-2.5">
        <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-[var(--border)]/60 bg-[var(--background)] text-[var(--muted-foreground)]">
          <Wand2 size={13} strokeWidth={1.6} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="truncate text-[14px] font-semibold tracking-tight text-[var(--foreground)]">
              {skill.name}
            </span>
            {installed ? (
              <span className="inline-flex shrink-0 items-center gap-1 rounded-md bg-emerald-500/12 px-1.5 py-0.5 text-[10px] font-medium text-emerald-600 dark:text-emerald-400">
                <CheckCircle2 size={9} />
                {tr("已导入", "Installed")}
              </span>
            ) : null}
          </div>
          {skill.summary ? (
            <p className="mt-0.5 line-clamp-2 text-[12px] leading-relaxed text-[var(--muted-foreground)]">
              {skill.summary}
            </p>
          ) : (
            <p className="mt-0.5 text-[12px] italic text-[var(--muted-foreground)]/60">
              {tr("暂无描述。", "No description.")}
            </p>
          )}
        </div>
      </div>

      <div className="mt-3 flex items-center justify-between gap-2 pt-2">
        <div className="flex min-w-0 items-center gap-2.5 text-[11px] text-[var(--muted-foreground)]">
          <span className="inline-flex items-center gap-1">
            <Download size={11} />
            {skill.downloads}
          </span>
          <span className="inline-flex items-center gap-1">
            <Star size={11} />
            {skill.stars}
          </span>
          {skill.owner ? (
            <span className="truncate">· {skill.owner}</span>
          ) : null}
        </div>
        <InstallButton
          state={state}
          installed={installed}
          tr={tr}
          onClick={(force) => onInstall(skill.slug, { force })}
        />
      </div>

      {state?.kind === "error" ? (
        <p className="mt-2 line-clamp-2 text-[11px] text-amber-700 dark:text-amber-400">
          {state.message}
        </p>
      ) : null}
    </li>
  );
}

// ── detail view ──────────────────────────────────────────────────────────────

function DetailView({
  skill,
  detail,
  loading,
  error,
  installState,
  installed,
  webUrl,
  tr,
  onBack,
  onInstall,
}: {
  skill: HubSkillListing;
  detail: HubSkillDetail | null;
  loading: boolean;
  error: string | null;
  installState?: InstallState;
  installed: boolean;
  webUrl: string;
  tr: (cn: string, en: string) => string;
  onBack: () => void;
  onInstall: (slug: string, opts?: { force?: boolean }) => void;
}) {
  const version = detail?.version || skill.version;
  return (
    <>
      <div className="flex items-center justify-between gap-3 border-b border-[var(--border)] px-5 py-2.5">
        <button
          onClick={onBack}
          className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[12.5px] text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
        >
          <ArrowLeft size={13} />
          {tr("返回", "Back")}
        </button>
        <div className="flex items-center gap-1.5">
          <a
            href={detail?.webUrl || `${webUrl}/skills/${skill.slug}`}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[12px] text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
          >
            <ExternalLink size={13} />
            {tr("在 EduHub 查看", "View on EduHub")}
          </a>
          <InstallButton
            state={installState}
            installed={installed}
            tr={tr}
            onClick={(force) => onInstall(skill.slug, { force })}
          />
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
        <div className="mb-1 flex items-center gap-2">
          <h2 className="text-[18px] font-semibold tracking-tight text-[var(--foreground)]">
            {skill.name}
          </h2>
          {version ? (
            <span className="rounded-md bg-[var(--muted)] px-1.5 py-0.5 text-[10.5px] font-medium text-[var(--muted-foreground)]">
              v{version}
            </span>
          ) : null}
        </div>
        <div className="mb-4 flex flex-wrap items-center gap-3 text-[11.5px] text-[var(--muted-foreground)]">
          <span className="inline-flex items-center gap-1">
            <Download size={12} />
            {skill.downloads} {tr("次下载", "downloads")}
          </span>
          <span className="inline-flex items-center gap-1">
            <Star size={12} />
            {skill.stars}
          </span>
          {skill.owner ? <span>· {skill.owner}</span> : null}
        </div>

        {detail?.tags && detail.tags.length > 0 ? (
          <div className="mb-4 flex flex-wrap gap-1.5">
            {detail.tags.map((tag) => (
              <span
                key={tag}
                className="inline-flex items-center rounded-full border border-[var(--border)]/60 bg-[var(--muted)]/40 px-2 py-0.5 text-[10.5px] font-medium text-[var(--muted-foreground)]"
              >
                {tag}
              </span>
            ))}
          </div>
        ) : null}

        {installState?.kind === "error" ? (
          <div className="mb-4 rounded-lg border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-[12px] text-amber-700 dark:text-amber-400">
            {tr("导入失败：", "Import failed: ")}
            {installState.message}
          </div>
        ) : null}

        {loading ? (
          <div className="flex items-center justify-center py-12 text-[var(--muted-foreground)]">
            <Loader2 size={18} className="animate-spin" />
          </div>
        ) : error ? (
          <div className="rounded-lg border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-[12.5px] text-amber-700 dark:text-amber-400">
            {error}
          </div>
        ) : detail ? (
          <div className="prose-skill text-[13.5px] leading-relaxed text-[var(--foreground)]">
            <SkillMarkdown content={stripFrontmatter(detail.content)} />
          </div>
        ) : null}
      </div>
    </>
  );
}

// ── shared install button ───────────────────────────────────────────────────

function InstallButton({
  state,
  installed,
  tr,
  onClick,
}: {
  state?: InstallState;
  installed: boolean;
  tr: (cn: string, en: string) => string;
  onClick: (force: boolean) => void;
}) {
  if (state?.kind === "installing") {
    return (
      <span className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-[var(--muted)] px-3 py-1.5 text-[12px] font-medium text-[var(--muted-foreground)]">
        <Loader2 size={12} className="animate-spin" />
        {tr("下载中…", "Downloading…")}
      </span>
    );
  }

  const label =
    state?.kind === "error"
      ? tr("重试", "Retry")
      : installed
        ? tr("重新下载", "Re-download")
        : tr("下载", "Download");
  const Icon = installed ? RefreshCw : Download;

  return (
    <button
      onClick={(e) => {
        e.stopPropagation();
        onClick(installed);
      }}
      className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-1.5 text-[12px] font-medium text-[var(--foreground)] shadow-sm transition-colors hover:bg-[var(--muted)]/60"
    >
      <Icon size={12} strokeWidth={2} />
      {label}
    </button>
  );
}
