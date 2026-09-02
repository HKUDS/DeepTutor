"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowUpRight, Check } from "lucide-react";
import { useTranslation } from "react-i18next";

import ProviderIcon from "@/components/common/ProviderIcon";
import { apiFetch, apiUrl } from "@/lib/api";
import SettingsStatusPanel from "@/components/settings/SettingsStatusPanel";
import { setPendingPrompt } from "@/lib/pending-prompt";
import {
  SETTINGS_CATEGORIES,
  settingsAnchorHref,
  type Lang,
  type SettingsLeaf,
} from "@/features/settings/navigation/settings-nav";
import {
  getActiveModel,
  getActiveProfile,
  serviceReadiness,
  useSettings,
  type ServiceReadiness,
} from "@/features/settings/store/SettingsStore";

/**
 * The settings landing page.
 *
 * It used to be a grid of seven cards whose only job was to link to the seven
 * categories — a directory, now that the navigator lists every page anyway.
 * What it could not answer, and what a landing page is for, is "what state am
 * I actually in": which services are set up, which failed their last test, and
 * whether something is sitting in a draft waiting to be applied.
 */
export default function SettingsOverview() {
  const { t, i18n } = useTranslation();
  const zh = i18n.language?.toLowerCase().startsWith("zh");
  const tr = useCallback((value: Lang) => (zh ? value.zh : value.en), [zh]);
  const {
    catalog,
    catalogEditable,
    diagnosticsResults,
    draftState,
    storedDraft,
    startTour,
  } = useSettings();

  const modelLeaves = useMemo(
    () =>
      (
        SETTINGS_CATEGORIES.find((category) => category.key === "models")
          ?.children ?? []
      ).filter(
        (
          leaf,
        ): leaf is SettingsLeaf & {
          service: NonNullable<SettingsLeaf["service"]>;
        } => Boolean(leaf.service),
      ),
    [],
  );

  const states = useMemo(
    () =>
      catalogEditable !== true
        ? []
        : modelLeaves.map((leaf) => ({
            leaf,
            readiness: serviceReadiness(
              catalog,
              leaf.service,
              diagnosticsResults,
            ),
          })),
    [catalog, catalogEditable, diagnosticsResults, modelLeaves],
  );

  const failed = states.filter((item) => item.readiness === "failed");
  const missing = states.filter((item) => item.readiness === "not_configured");
  const ready = states.length - failed.length - missing.length;

  // Everything the user can act on, most urgent first. An empty list is worth
  // saying out loud — "nothing needs attention" is information, and the blank
  // panel it replaces is not.
  const attention: {
    key: string;
    text: string;
    href: string;
    label: string;
  }[] = [];
  if (draftState !== "clean") {
    attention.push({
      key: "draft",
      text:
        draftState === "saved"
          ? t("A saved draft is waiting to be applied.")
          : t("There are changes you have not saved anywhere yet."),
      href: settingsAnchorHref("llm"),
      label: t("Review"),
    });
  }
  for (const item of failed) {
    attention.push({
      key: `failed-${item.leaf.key}`,
      text: t("{{service}} failed its last connection test.", {
        service: tr(item.leaf.label),
      }),
      href: settingsAnchorHref(item.leaf.key),
      label: t("Open"),
    });
  }

  // What each service actually resolves to right now. Search names a provider
  // rather than a model, so it reports that instead of an empty string.
  const { detail, binding } = useMemo(() => {
    const detail: Record<string, string> = {};
    const binding: Record<string, string> = {};
    if (catalogEditable !== true) return { detail, binding };
    for (const leaf of modelLeaves) {
      const profile = getActiveProfile(catalog, leaf.service);
      binding[leaf.key] =
        (leaf.service === "search" ? profile?.provider : profile?.binding) ??
        "";
      detail[leaf.key] =
        leaf.service === "search"
          ? (profile?.provider ?? "")
          : (getActiveModel(catalog, leaf.service)?.model ?? "");
    }
    return { detail, binding };
  }, [catalog, catalogEditable, modelLeaves]);

  // The effective browser API base. The old hub previewed it on its Network
  // card, and it is the first thing to check on a Docker or LAN install, so it
  // did not deserve to disappear with that card.
  const [apiBase, setApiBase] = useState("");
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await apiFetch(apiUrl("/api/settings/network"));
        if (!res.ok) return;
        const data = (await res.json()) as {
          effective?: { browser_api_base?: string };
        };
        if (!cancelled) setApiBase(data.effective?.browser_api_base || "");
      } catch {
        /* non-admins get 403; the row simply does not render */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div>
      <header className="mb-6 flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="font-serif text-[22px] font-semibold tracking-tight text-[var(--foreground)]">
            {t("Settings")}
          </h1>
          <p className="mt-1.5 text-[13px] leading-relaxed text-[var(--muted-foreground)]">
            {catalogEditable === true && states.length > 0
              ? t("{{ready}} of {{total}} model services set up.", {
                  ready,
                  total: states.length,
                })
              : t("Appearance, models, knowledge, chat, and memory.")}
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            setPendingPrompt(
              tr({
                zh: "帮我配置一下 DeepTutor，先看看现在缺什么。",
                en: "Help me configure DeepTutor — start by checking what's missing.",
              }),
            );
          }}
          className="hidden shrink-0 items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)] sm:inline-flex"
        >
          {t("Set up with DeepTutor")}
        </button>
      </header>

      <SettingsStatusPanel />

      {catalogEditable === true && (
        <>
          <Section title={t("Needs attention")}>
            {attention.length === 0 ? (
              <div className="flex items-center gap-2 py-3 text-[12.5px] text-[var(--muted-foreground)]">
                <Check className="h-3.5 w-3.5 text-emerald-500" />
                {t("Nothing to do — everything configured is working.")}
              </div>
            ) : (
              attention.map((item, index) => (
                <div
                  key={item.key}
                  className={`flex flex-wrap items-center justify-between gap-x-4 gap-y-1 py-2.5 ${
                    index === 0 ? "" : "border-t border-[var(--border)]/50"
                  }`}
                >
                  <span className="text-[12.5px] text-[var(--foreground)]">
                    {item.text}
                  </span>
                  <Link
                    href={item.href}
                    className="inline-flex items-center gap-1 text-[11.5px] text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
                  >
                    {item.label}
                    <ArrowUpRight className="h-3 w-3" />
                  </Link>
                </div>
              ))
            )}
          </Section>

          <Section title={t("Model services")}>
            {states.map((item, index) => (
              <div
                key={item.leaf.key}
                className={`flex flex-wrap items-center justify-between gap-x-4 gap-y-1 py-2.5 ${
                  index === 0 ? "" : "border-t border-[var(--border)]/50"
                }`}
              >
                <Link
                  href={settingsAnchorHref(item.leaf.key)}
                  className="text-[12.5px] text-[var(--foreground)] transition-opacity hover:opacity-70"
                >
                  {tr(item.leaf.label)}
                </Link>
                <span className="flex min-w-0 items-center gap-2">
                  {detail[item.leaf.key] && (
                    <span className="flex min-w-0 items-center gap-1.5">
                      {binding[item.leaf.key] && (
                        <ProviderIcon
                          provider={binding[item.leaf.key]}
                          size={12}
                        />
                      )}
                      <span className="truncate font-mono text-[11px] text-[var(--muted-foreground)]">
                        {detail[item.leaf.key]}
                      </span>
                    </span>
                  )}
                  <ReadinessChip readiness={item.readiness} />
                </span>
              </div>
            ))}
          </Section>
        </>
      )}

      {apiBase && (
        <p className="mt-5 text-[11.5px] text-[var(--muted-foreground)]">
          {t("Browser API base")}{" "}
          <Link
            href={settingsAnchorHref("network")}
            className="font-mono text-[var(--foreground)]/70 underline-offset-2 hover:underline"
          >
            {apiBase}
          </Link>
        </p>
      )}

      <button
        type="button"
        onClick={startTour}
        className="mt-6 text-[11.5px] text-[var(--muted-foreground)] underline-offset-2 transition-colors hover:text-[var(--foreground)] hover:underline"
      >
        {t("Take the tour")}
      </button>
      {storedDraft?.updated_at && (
        <p className="mt-2 text-[11px] text-[var(--muted-foreground)]/70">
          {t("Draft saved {{when}}", { when: storedDraft.updated_at })}
        </p>
      )}
    </div>
  );
}

function ReadinessChip({ readiness }: { readiness: ServiceReadiness }) {
  const { t } = useTranslation();
  const label: Record<ServiceReadiness, string> = {
    passed: t("Test passed"),
    failed: t("Test failed"),
    untested: t("Configured"),
    not_configured: t("Not set"),
  };
  const tone: Record<ServiceReadiness, string> = {
    passed: "text-emerald-600 dark:text-emerald-400",
    failed: "text-red-500",
    untested: "text-[var(--muted-foreground)]",
    not_configured: "text-[var(--muted-foreground)]/60",
  };
  return (
    <span className={`shrink-0 text-[11px] ${tone[readiness]}`}>
      {label[readiness]}
    </span>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="mt-7">
      <h2 className="mb-2 text-[12px] font-medium text-[var(--muted-foreground)]">
        {title}
      </h2>
      <div className="border-t border-[var(--border)]/60">{children}</div>
    </section>
  );
}
