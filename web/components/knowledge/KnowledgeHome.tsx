"use client";

import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Check,
  ChevronRight,
  Cloud,
  Cpu,
  Database,
  HardDrive,
  Library,
  Plus,
  Search,
  Server,
  Star,
} from "lucide-react";
import {
  kbDocCount,
  kbHasLiveProgress,
  kbNeedsReindex,
  kbProvider,
  providerConnectionStatus,
  resolveKbStatus,
  type ProviderConnectionStatus,
  type KnowledgeBase,
} from "@/lib/knowledge-helpers";
import type { RagProviderSummary } from "@/features/knowledge/model/types";
import { knowledgeEngineGroup } from "@/lib/knowledge-engine-group";
import KnowledgeEngineIcon, {
  knowledgeSourceIconId,
} from "./KnowledgeEngineIcon";

export type KnowledgeHomeSection = "knowledge-bases" | "knowledge-engines";

interface KnowledgeHomeProps {
  kbs: KnowledgeBase[];
  providers: RagProviderSummary[];
  onOpenKb: (name: string) => void;
  onOpenEngine: (id: string) => void;
  onOpenSource: (id: "obsidian" | "marginnote4") => void;
  onCreate: () => void;
  activeSection: KnowledgeHomeSection;
  onSectionChange: (section: KnowledgeHomeSection) => void;
}

function EngineStatusBadge({ status }: { status: ProviderConnectionStatus }) {
  const { t } = useTranslation();
  if (status === "ready") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300">
        <Check className="h-3 w-3" />
        {t("Ready")}
      </span>
    );
  }
  if (status === "needs_key") {
    return (
      <span className="inline-flex items-center rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-700 dark:bg-amber-950/30 dark:text-amber-300">
        {t("Needs key")}
      </span>
    );
  }
  if (status === "needs_setup") {
    return (
      <span className="inline-flex items-center rounded-full bg-sky-100 px-1.5 py-0.5 text-[10px] font-medium text-sky-700 dark:bg-sky-950/30 dark:text-sky-300">
        {t("Needs setup")}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center rounded-full bg-[var(--muted)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--muted-foreground)]">
      {t("Not installed")}
    </span>
  );
}

function StatusDot({ kb }: { kb: KnowledgeBase }) {
  const status = resolveKbStatus(kb);
  const needsReindex = kbNeedsReindex(kb);
  const isLive = kbHasLiveProgress(kb);
  const tone = needsReindex
    ? "bg-amber-500"
    : status === "error"
      ? "bg-red-500"
      : isLive
        ? "bg-sky-500 animate-pulse"
        : status === "ready"
          ? "bg-emerald-500"
          : "bg-[var(--muted-foreground)]";
  return <span className={`inline-block h-2 w-2 rounded-full ${tone}`} />;
}

export default function KnowledgeHome({
  kbs,
  providers,
  onOpenKb,
  onOpenEngine,
  onOpenSource,
  onCreate,
  activeSection,
  onSectionChange,
}: KnowledgeHomeProps) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const providerName = (id: string) =>
    providers.find((p) => p.id === id)?.name ??
    id.charAt(0).toUpperCase() + id.slice(1);

  const kbCountByProvider = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const kb of kbs)
      counts[kbProvider(kb)] = (counts[kbProvider(kb)] ?? 0) + 1;
    return counts;
  }, [kbs]);

  const filteredKbs = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return kbs;
    return kbs.filter((kb) => kb.name.toLowerCase().includes(q));
  }, [kbs, query]);

  const groupedProviders = useMemo(
    () => ({
      local: providers.filter(
        (provider) => knowledgeEngineGroup(provider) === "local",
      ),
      server: providers.filter(
        (provider) => knowledgeEngineGroup(provider) === "server",
      ),
      cloud: providers.filter(
        (provider) => knowledgeEngineGroup(provider) === "cloud",
      ),
    }),
    [providers],
  );

  const externalSources = useMemo(
    () => [
      {
        id: "obsidian" as const,
        name: t("Obsidian"),
        description: t(
          "A live Obsidian vault — browsed and edited in place, no index.",
        ),
        action: t("Connect vault"),
        count: kbs.filter((kb) => kb.metadata?.type === "obsidian").length,
      },
      {
        id: "marginnote4" as const,
        name: t("MarginNote 4"),
        description: t(
          "Notes, excerpts and cards pushed in by the MarginNote 4 add-on.",
        ),
        action: t("Connect library"),
        count: kbs.filter((kb) => kb.metadata?.type === "marginnote4").length,
      },
    ],
    [kbs, t],
  );

  const renderProvider = (provider: RagProviderSummary) => {
    const status = providerConnectionStatus(provider);
    const count = kbCountByProvider[provider.id] ?? 0;
    return (
      <button
        key={provider.id}
        type="button"
        onClick={() => onOpenEngine(provider.id)}
        className="group flex min-w-0 flex-col gap-2 rounded-2xl border border-[var(--border)] p-3.5 text-left transition-colors hover:border-[var(--ring)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
      >
        <div className="flex items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-2">
            <KnowledgeEngineIcon engine={provider.id} size={24} />
            <span className="truncate text-[13.5px] font-medium text-[var(--foreground)]">
              {provider.name}
            </span>
          </div>
          <EngineStatusBadge status={status} />
        </div>
        <p className="line-clamp-2 text-[11.5px] leading-snug text-[var(--muted-foreground)]">
          {provider.description}
        </p>
        <div className="mt-auto flex items-center gap-2 pt-1 text-[11px] text-[var(--muted-foreground)]">
          {provider.modes &&
            provider.modes.length > 0 &&
            provider.default_mode && (
              <span className="rounded-full border border-[var(--border)] px-1.5 py-0.5 font-mono">
                {provider.default_mode}
              </span>
            )}
          {count > 0 && <span>{t("{{count}} KB", { count })}</span>}
          <ChevronRight className="ml-auto h-3.5 w-3.5 opacity-0 transition-opacity group-hover:opacity-60" />
        </div>
      </button>
    );
  };

  const renderExternalSource = (source: (typeof externalSources)[number]) => (
    <button
      key={source.id}
      type="button"
      onClick={() => onOpenSource(source.id)}
      className="group flex min-w-0 flex-col gap-2 rounded-2xl border border-[var(--border)] p-3.5 text-left transition-colors hover:border-[var(--ring)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
    >
      <div className="flex min-w-0 items-center gap-2.5">
        <KnowledgeEngineIcon engine={source.id} size={26} />
        <span className="truncate text-[13.5px] font-medium text-[var(--foreground)]">
          {source.name}
        </span>
      </div>
      <p className="line-clamp-2 text-[11.5px] leading-snug text-[var(--muted-foreground)]">
        {source.description}
      </p>
      <div className="mt-auto flex items-center gap-2 pt-1 text-[11px] text-[var(--muted-foreground)]">
        <span>{source.action}</span>
        {source.count > 0 && (
          <span>{t("{{count}} connected", { count: source.count })}</span>
        )}
        <ChevronRight className="ml-auto h-3.5 w-3.5 opacity-0 transition-opacity group-hover:opacity-60" />
      </div>
    </button>
  );

  return (
    <div className="min-w-0 flex-1 overflow-y-auto bg-[var(--background)]">
      <div className="mx-auto w-full max-w-5xl px-4 py-6 sm:px-6 sm:py-8">
        {/* Header */}
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-[19px] font-semibold tracking-tight text-[var(--foreground)]">
              {t("Knowledge Center")}
            </h1>
            <p className="mt-1 text-[12.5px] text-[var(--muted-foreground)]">
              {t("Manage your knowledge bases and retrieval engines.")}
            </p>
          </div>
          <button
            type="button"
            onClick={onCreate}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3.5 py-2 text-[12.5px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90"
          >
            <Plus size={14} />
            {t("New knowledge base")}
          </button>
        </div>

        <div
          role="tablist"
          aria-label={t("Knowledge Center")}
          className="mt-6 flex border-b border-[var(--border)]"
        >
          {[
            {
              id: "knowledge-bases" as const,
              label: t("Knowledge bases"),
              count: kbs.length,
              icon: Database,
            },
            {
              id: "knowledge-engines" as const,
              label: t("Knowledge engines"),
              count: providers.length + externalSources.length,
              icon: Cpu,
            },
          ].map((item) => {
            const active = activeSection === item.id;
            const Icon = item.icon;
            return (
              <button
                key={item.id}
                id={`${item.id}-tab`}
                type="button"
                role="tab"
                aria-selected={active}
                aria-controls={`${item.id}-panel`}
                onClick={() => onSectionChange(item.id)}
                className={`relative min-w-0 px-4 py-2.5 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--ring)] ${
                  active
                    ? "text-[var(--primary)]"
                    : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                }`}
              >
                <span className="flex items-center gap-2 text-[13px] font-medium">
                  <Icon className="h-4 w-4 shrink-0" strokeWidth={1.7} />
                  <span className="truncate">{item.label}</span>
                  <span className="rounded-full bg-[var(--muted)] px-1.5 py-0.5 text-[10px] font-normal text-[var(--muted-foreground)]">
                    {item.count}
                  </span>
                </span>
                {active && (
                  <span className="absolute inset-x-0 -bottom-px h-0.5 rounded-full bg-[var(--primary)]" />
                )}
              </button>
            );
          })}
        </div>

        {activeSection === "knowledge-bases" ? (
          <section
            id="knowledge-bases-panel"
            role="tabpanel"
            aria-labelledby="knowledge-bases-tab"
            className="mt-6 pb-2"
          >
            <div className="mb-3 flex items-center justify-between gap-2">
              <h2 className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
                <Database className="h-3.5 w-3.5" />
                {t("Knowledge bases")}
                <span className="rounded-full bg-[var(--muted)] px-1.5 py-0.5 text-[10px] text-[var(--muted-foreground)]">
                  {kbs.length}
                </span>
              </h2>
              {kbs.length > 6 && (
                <div className="relative w-48">
                  <Search
                    className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--muted-foreground)]"
                    aria-hidden
                  />
                  <input
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder={t("Search knowledge bases…")}
                    className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] py-1.5 pl-8 pr-3 text-[12px] text-[var(--foreground)] outline-none transition-colors placeholder:text-[var(--muted-foreground)] focus:border-[var(--foreground)]/25"
                  />
                </div>
              )}
            </div>

            {kbs.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-[var(--border)] px-4 py-12 text-center">
                <Database className="mx-auto mb-2 h-6 w-6 text-[var(--muted-foreground)]" />
                <div className="text-[13px] font-medium text-[var(--foreground)]">
                  {t("No knowledge bases yet")}
                </div>
                <p className="mx-auto mt-1 max-w-sm text-[12px] leading-relaxed text-[var(--muted-foreground)]">
                  {t(
                    "Create one to upload documents and retrieve grounded context in chat.",
                  )}
                </p>
                <button
                  type="button"
                  onClick={onCreate}
                  className="mt-4 inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3.5 py-2 text-[12.5px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90"
                >
                  <Plus size={14} />
                  {t("New knowledge base")}
                </button>
              </div>
            ) : filteredKbs.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-[var(--border)] px-4 py-8 text-center text-[12px] text-[var(--muted-foreground)]">
                {t("No matches")}
              </div>
            ) : (
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                {filteredKbs.map((kb) => {
                  const docs = kbDocCount(kb);
                  return (
                    <button
                      key={kb.name}
                      type="button"
                      onClick={() => onOpenKb(kb.name)}
                      className="group flex flex-col gap-2 rounded-2xl border border-[var(--border)] p-4 text-left transition-colors hover:border-[var(--ring)]"
                    >
                      <div className="flex items-start gap-3">
                        <KnowledgeEngineIcon
                          engine={knowledgeSourceIconId({
                            provider: kbProvider(kb),
                            type: kb.metadata?.type,
                          })}
                          size={32}
                        />
                        <div className="min-w-0 flex-1 pt-0.5">
                          <div className="flex items-center gap-2">
                            <StatusDot kb={kb} />
                            <span className="truncate text-[13.5px] font-medium text-[var(--foreground)]">
                              {kb.name}
                            </span>
                            {kb.is_default && (
                              <Star
                                className="h-3 w-3 shrink-0 text-amber-500"
                                fill="currentColor"
                              />
                            )}
                          </div>
                          <div className="mt-2 flex items-center gap-2 text-[11px] text-[var(--muted-foreground)]">
                            <span className="rounded-full border border-[var(--border)] px-1.5 py-0.5">
                              {providerName(kbProvider(kb))}
                            </span>
                            {docs !== null && (
                              <span>
                                {docs} {t("docs")}
                              </span>
                            )}
                          </div>
                        </div>
                      </div>
                    </button>
                  );
                })}
              </div>
            )}
          </section>
        ) : (
          <div
            id="knowledge-engines-panel"
            role="tabpanel"
            aria-labelledby="knowledge-engines-tab"
            className="mt-6 space-y-8 pb-2"
          >
            <section>
              <div className="mb-3 flex items-start gap-2">
                <HardDrive className="mt-0.5 h-4 w-4 shrink-0 text-[var(--muted-foreground)]" />
                <div>
                  <h2 className="text-[13px] font-medium text-[var(--foreground)]">
                    {t("Local engines")}
                  </h2>
                  <p className="mt-0.5 text-[11.5px] text-[var(--muted-foreground)]">
                    {t("Indexes and retrieves on this device.")}
                  </p>
                </div>
              </div>
              <div className="grid grid-cols-1 items-stretch gap-3 md:grid-cols-2">
                {groupedProviders.local.map(renderProvider)}
              </div>
            </section>

            <section>
              <div className="mb-3 flex items-start gap-2">
                <Server className="mt-0.5 h-4 w-4 shrink-0 text-[var(--muted-foreground)]" />
                <div>
                  <h2 className="text-[13px] font-medium text-[var(--foreground)]">
                    {t("Server engines")}
                  </h2>
                  <p className="mt-0.5 text-[11.5px] text-[var(--muted-foreground)]">
                    {t("Connects to a retrieval server you operate.")}
                  </p>
                </div>
              </div>
              <div className="grid grid-cols-1 items-stretch gap-3 md:grid-cols-2">
                {groupedProviders.server.map(renderProvider)}
              </div>
            </section>

            <section>
              <div className="mb-3 flex items-start gap-2">
                <Cloud className="mt-0.5 h-4 w-4 shrink-0 text-[var(--muted-foreground)]" />
                <div>
                  <h2 className="text-[13px] font-medium text-[var(--foreground)]">
                    {t("Cloud services")}
                  </h2>
                  <p className="mt-0.5 text-[11.5px] text-[var(--muted-foreground)]">
                    {t("Managed providers connected with account credentials.")}
                  </p>
                </div>
              </div>
              <div className="grid grid-cols-1 items-stretch gap-3 md:grid-cols-2">
                {groupedProviders.cloud.map(renderProvider)}
              </div>
            </section>

            <section>
              <div className="mb-3 flex items-start gap-2">
                <Library className="mt-0.5 h-4 w-4 shrink-0 text-[var(--muted-foreground)]" />
                <div>
                  <h2 className="text-[13px] font-medium text-[var(--foreground)]">
                    {t("External knowledge sources")}
                  </h2>
                  <p className="mt-0.5 text-[11.5px] text-[var(--muted-foreground)]">
                    {t(
                      "Connect live libraries and note apps without rebuilding an index.",
                    )}
                  </p>
                </div>
              </div>
              <div className="grid grid-cols-1 items-stretch gap-3 md:grid-cols-2">
                {externalSources.map(renderExternalSource)}
              </div>
            </section>
          </div>
        )}
      </div>
    </div>
  );
}
