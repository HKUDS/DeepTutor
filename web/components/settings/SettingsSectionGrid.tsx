"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import { ArrowUpRight } from "lucide-react";

import { fetchAuthStatus } from "@/lib/auth";
import {
  serviceReadiness,
  useSettings,
} from "@/components/settings/SettingsContext";
import {
  SETTINGS_CATEGORIES,
  type Lang,
  type SettingsLeaf,
} from "@/lib/settings-nav";

/**
 * Second-level grid for a sub-hub category (Models, Chat). Lists the
 * category's leaves as tiles — colored icon, configured chip for model
 * services, and a blurb — the focused view the user reaches by clicking the
 * hub block.
 */
export default function SettingsSectionGrid({
  categoryKey,
}: {
  categoryKey: string;
}) {
  const { i18n } = useTranslation();
  const zh = i18n.language?.toLowerCase().startsWith("zh");
  const tr = useCallback((l: Lang) => (zh ? l.zh : l.en), [zh]);

  const { catalog, catalogEditable, diagnosticsResults } = useSettings();

  const category = SETTINGS_CATEGORIES.find((c) => c.key === categoryKey);

  const [hideAdminOnly, setHideAdminOnly] = useState(false);
  useEffect(() => {
    let cancelled = false;
    fetchAuthStatus().then((authStatus) => {
      if (cancelled || !authStatus) return;
      setHideAdminOnly(Boolean(authStatus.enabled) && !authStatus.is_admin);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const chipFor = useCallback(
    (
      leaf: SettingsLeaf,
    ): { label: Lang; tone: "ok" | "bad" | "neutral"; dot: boolean } | null => {
      if (!leaf.service) return null;
      if (catalogEditable !== true) return null;
      const readiness = serviceReadiness(
        catalog,
        leaf.service,
        diagnosticsResults,
      );
      if (readiness === "failed") {
        return {
          tone: "bad",
          dot: true,
          label: { zh: "测试失败", en: "Test failed" },
        };
      }
      if (readiness === "passed") {
        return {
          tone: "ok",
          dot: true,
          label: { zh: "测试通过", en: "Test passed" },
        };
      }
      if (readiness === "untested") {
        return {
          tone: "neutral",
          dot: true,
          label: { zh: "已配置", en: "Configured" },
        };
      }
      return {
        tone: "neutral",
        dot: false,
        label: { zh: "未配置", en: "Not set" },
      };
    },
    [catalog, catalogEditable, diagnosticsResults],
  );

  if (!category?.children) return null;

  const leaves = category.children.filter(
    (leaf) => !(leaf.adminOnly && hideAdminOnly),
  );

  return (
    <div>
      <header className="mb-6">
        <h1 className="font-serif text-[22px] font-semibold tracking-tight text-[var(--foreground)]">
          {tr(category.label)}
        </h1>
        <p className="mt-1.5 text-[13px] leading-relaxed text-[var(--muted-foreground)]">
          {tr(category.blurb)}
        </p>
      </header>

      <div className="grid gap-3 sm:grid-cols-2">
        {leaves.map((leaf) => (
          <LeafCard key={leaf.key} leaf={leaf} chip={chipFor(leaf)} tr={tr} />
        ))}
      </div>
    </div>
  );
}

function LeafCard({
  leaf,
  chip,
  tr,
}: {
  leaf: SettingsLeaf;
  chip: { label: Lang; tone: "ok" | "bad" | "neutral"; dot: boolean } | null;
  tr: (l: Lang) => string;
}) {
  const Icon = leaf.icon;
  const tone = chip?.tone ?? "neutral";
  return (
    <Link
      href={leaf.href}
      className="group relative flex flex-col rounded-xl border border-[var(--border)] bg-[var(--card)] p-4 transition-all duration-150 hover:-translate-y-0.5 hover:border-[var(--foreground)]/20 hover:shadow-[0_6px_20px_-12px_rgba(0,0,0,0.25)]"
    >
      <div className="flex items-start gap-3">
        <span
          aria-hidden
          className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${leaf.tile}`}
        >
          <Icon size={18} strokeWidth={1.7} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h3 className="truncate text-[14.5px] font-medium leading-tight tracking-tight text-[var(--foreground)]">
              {tr(leaf.label)}
            </h3>
            {chip && (
              <span
                className={`inline-flex shrink-0 items-center gap-1 text-[10.5px] font-medium ${
                  chip.dot
                    ? `rounded-full px-1.5 py-0.5 ${
                        tone === "bad"
                          ? "bg-red-500/10 text-red-600 dark:text-red-400"
                          : tone === "ok"
                            ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                            : "bg-zinc-500/10 text-zinc-600 dark:text-zinc-300"
                      }`
                    : "text-[var(--muted-foreground)]"
                }`}
              >
                {chip.dot && (
                  <span
                    className={`h-1.5 w-1.5 rounded-full ${
                      tone === "bad"
                        ? "bg-red-500"
                        : tone === "ok"
                          ? "bg-emerald-500"
                          : "bg-zinc-400 dark:bg-zinc-500"
                    }`}
                  />
                )}
                {tr(chip.label)}
              </span>
            )}
          </div>
        </div>
        <ArrowUpRight
          size={16}
          className="shrink-0 text-[var(--muted-foreground)]/40 transition-colors group-hover:text-[var(--foreground)]"
        />
      </div>
      <p className="mt-3 text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
        {tr(leaf.blurb)}
      </p>
    </Link>
  );
}
