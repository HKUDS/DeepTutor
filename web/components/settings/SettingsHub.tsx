"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import { ChevronRight, Rocket, type LucideIcon } from "lucide-react";

import { apiFetch, apiUrl } from "@/lib/api";
import {
  serviceReadiness,
  useSettings,
  type ServiceReadiness,
} from "@/components/settings/SettingsContext";
import SettingsStatusPanel from "@/components/settings/SettingsStatusPanel";
import {
  SETTINGS_CATEGORIES,
  type Lang,
  type SettingsCategory,
} from "@/lib/settings-nav";

/**
 * Settings hub — the landing page of `/settings`.
 *
 * Six category blocks and a resident Status module, nothing else. The blocks
 * are intentionally calmer than the Learning Space tiles (monochrome inline
 * icons, a chevron, a quiet preview line instead of a focal count) so Settings
 * reads as a control surface rather than a dashboard. Categories with several
 * settings (Models, Chat) open a sub-hub; the rest link straight to their leaf.
 */

type NetworkPreview = {
  apiBase: string;
};

export default function SettingsHub() {
  const { i18n } = useTranslation();
  const zh = i18n.language?.toLowerCase().startsWith("zh");
  const tr = useCallback((l: Lang) => (zh ? l.zh : l.en), [zh]);

  const { catalog, catalogEditable, diagnosticsResults, startTour } =
    useSettings();

  // Model preview: how many of the model-service leaves are configured.
  const modelStats = useMemo(() => {
    const cat = SETTINGS_CATEGORIES.find((c) => c.key === "models");
    const services = (cat?.children ?? []).filter((l) => l.service);
    if (catalogEditable !== true) {
      return {
        total: services.length,
        configured: -1,
        passed: 0,
        failed: 0,
        states: [] as ServiceReadiness[],
      };
    }
    const states = services.map((leaf) =>
      serviceReadiness(catalog, leaf.service!, diagnosticsResults),
    );
    return {
      total: services.length,
      configured: states.filter((state) => state !== "not_configured").length,
      passed: states.filter((state) => state === "passed").length,
      failed: states.filter((state) => state === "failed").length,
      states,
    };
  }, [catalog, catalogEditable, diagnosticsResults]);

  // Network preview: a guarded peek at the effective browser API base. Fails
  // quietly (non-admins get 403) → the block falls back to its blurb.
  const [network, setNetwork] = useState<NetworkPreview | null>(null);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await apiFetch(apiUrl("/api/v1/settings/network"));
        if (!res.ok) return;
        const data = (await res.json()) as {
          effective?: { browser_api_base?: string };
        };
        if (cancelled) return;
        setNetwork({ apiBase: data.effective?.browser_api_base || "" });
      } catch {
        /* leave null → block shows its blurb */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div>
      <header className="mb-7 flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="font-serif text-[24px] font-semibold leading-tight tracking-tight text-[var(--foreground)]">
            {tr({ zh: "设置", en: "Settings" })}
          </h1>
          <p className="mt-1.5 max-w-xl text-[13px] leading-relaxed text-[var(--muted-foreground)]">
            {tr({
              zh: "管理外观、模型与服务、知识库、聊天与记忆。",
              en: "Manage appearance, models and services, knowledge base, chat, and memory.",
            })}
          </p>
        </div>
        <button
          type="button"
          onClick={startTour}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-[var(--border)]/60 px-3 py-1.5 text-[12.5px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--border)] hover:text-[var(--foreground)]"
        >
          <Rocket size={13} />
          {tr({ zh: "引导", en: "Tour" })}
        </button>
      </header>

      <SettingsStatusPanel />

      <div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {SETTINGS_CATEGORIES.map((category) => (
          <CategoryBlock
            key={category.key}
            category={category}
            tr={tr}
            modelStats={category.key === "models" ? modelStats : undefined}
            network={category.key === "network" ? network : undefined}
          />
        ))}
      </div>
    </div>
  );
}

function CategoryBlock({
  category,
  tr,
  modelStats,
  network,
}: {
  category: SettingsCategory;
  tr: (l: Lang) => string;
  modelStats?: {
    total: number;
    configured: number;
    passed: number;
    failed: number;
    states: ServiceReadiness[];
  };
  network?: NetworkPreview | null;
}) {
  const Icon: LucideIcon = category.icon;

  return (
    <Link
      href={category.href}
      data-tour={`tour-cat-${category.key}`}
      className="group relative flex min-h-[120px] flex-col justify-between rounded-2xl border border-[var(--border)]/70 bg-[var(--card)] p-5 transition-all duration-150 hover:border-[var(--foreground)]/20 hover:shadow-[0_4px_24px_-16px_rgba(0,0,0,0.3)]"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <Icon
            size={19}
            strokeWidth={1.6}
            className="text-[var(--muted-foreground)] transition-colors group-hover:text-[var(--foreground)]"
          />
          <h3 className="text-[15.5px] font-medium tracking-tight text-[var(--foreground)]">
            {tr(category.label)}
          </h3>
        </div>
        <ChevronRight
          size={16}
          className="mt-0.5 shrink-0 text-[var(--muted-foreground)]/30 transition-all group-hover:translate-x-0.5 group-hover:text-[var(--muted-foreground)]"
        />
      </div>

      <div className="mt-4">
        {modelStats ? (
          <ModelPreview stats={modelStats} blurb={tr(category.blurb)} tr={tr} />
        ) : network !== undefined && network !== null ? (
          <NetworkPreviewRow network={network} tr={tr} />
        ) : (
          <p className="text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
            {tr(category.blurb)}
          </p>
        )}
      </div>
    </Link>
  );
}

function ModelPreview({
  stats,
  blurb,
  tr,
}: {
  stats: {
    total: number;
    configured: number;
    passed: number;
    failed: number;
    states: ServiceReadiness[];
  };
  blurb: string;
  tr: (l: Lang) => string;
}) {
  // Restricted deployments (no editable catalog) can't know — show the blurb.
  if (stats.configured < 0) {
    return (
      <p className="text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
        {blurb}
      </p>
    );
  }
  return (
    <div className="flex items-center gap-2.5">
      <div className="flex items-center gap-1">
        {stats.states.map((state, i) => (
          <span
            key={i}
            className={`h-1.5 w-1.5 rounded-full ${
              state === "passed"
                ? "bg-emerald-500"
                : state === "failed"
                  ? "bg-red-500"
                  : state === "untested"
                    ? "bg-zinc-400 dark:bg-zinc-500"
                    : "bg-zinc-300/60 dark:bg-zinc-700"
            }`}
          />
        ))}
      </div>
      <span className="text-[12px] tabular-nums text-[var(--muted-foreground)]">
        {stats.failed > 0
          ? tr({
              zh: `${stats.configured}/${stats.total} 已配置 · ${stats.failed} 个失败`,
              en: `${stats.configured}/${stats.total} configured · ${stats.failed} failed`,
            })
          : stats.passed > 0
            ? tr({
                zh: `${stats.configured}/${stats.total} 已配置 · ${stats.passed} 个通过`,
                en: `${stats.configured}/${stats.total} configured · ${stats.passed} passed`,
              })
            : tr({
                zh: `${stats.configured}/${stats.total} 已配置`,
                en: `${stats.configured}/${stats.total} configured`,
              })}
      </span>
    </div>
  );
}

function NetworkPreviewRow({
  network,
  tr,
}: {
  network: NetworkPreview;
  tr: (l: Lang) => string;
}) {
  return (
    <div className="flex items-center gap-2 text-[12px] text-[var(--muted-foreground)]">
      <span className="shrink-0 text-[var(--muted-foreground)]/70">
        {tr({ zh: "API", en: "API" })}
      </span>
      <span
        className="truncate font-mono text-[11.5px] text-[var(--foreground)]"
        title={network.apiBase}
      >
        {network.apiBase || tr({ zh: "本地", en: "local" })}
      </span>
    </div>
  );
}
