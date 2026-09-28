"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2, RefreshCcw } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  fetchSettingsPresets,
  type SettingsPreset,
} from "@/lib/settings-presets";
import { useSettings } from "@/features/settings/store/SettingsStore";

export default function SettingsPresetsPanel({ enabled }: { enabled: boolean }) {
  const { t } = useTranslation();
  const { stagePreset, saving } = useSettings();
  const [presets, setPresets] = useState<SettingsPreset[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [activeId, setActiveId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const payload = await fetchSettingsPresets();
      setPresets(payload.presets);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!enabled) return;
    void refresh();
  }, [enabled, refresh]);

  const load = async (preset: SettingsPreset) => {
    if (saving) return;
    setActiveId(preset.id);
    try {
      await stagePreset(preset.id);
    } finally {
      setActiveId(null);
    }
  };

  return (
    <section className="mt-8" aria-labelledby="settings-presets-title">
      <header className="mb-2 flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h2
            id="settings-presets-title"
            className="text-[15px] font-semibold tracking-tight text-[var(--foreground)]"
          >
            {t("settings.presets.title")}
          </h2>
          <p className="mt-1 text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
            {t("settings.presets.blurb")}
          </p>
        </div>
        <button
          type="button"
          onClick={() => void refresh()}
          disabled={loading || !enabled}
          aria-label={t("Refresh")}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-[var(--border)] px-2.5 py-1.5 text-[11.5px] text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)] disabled:opacity-50"
        >
          {loading ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <RefreshCcw className="h-3 w-3" />
          )}
          {t("readiness.refresh")}
        </button>
      </header>

      {error && (
        <p role="alert" className="py-3 text-[12.5px] text-amber-600">
          {t("settings.presets.error")}
        </p>
      )}

      {!presets && !error && (
        <div className="grid gap-3 pt-2 sm:grid-cols-2">
          {[0, 1, 2, 3].map((index) => (
            <div
              key={index}
              className="h-[172px] animate-pulse rounded-lg border border-[var(--border)]/60 bg-[var(--muted)]/40"
            />
          ))}
        </div>
      )}

      {presets && presets.length === 0 && (
        <p className="py-3 text-[12.5px] text-[var(--muted-foreground)]">
          {t("settings.presets.empty")}
        </p>
      )}

      {presets && presets.length > 0 && (
        <div className="grid gap-3 pt-2 sm:grid-cols-2">
          {presets.map((preset) => (
            <article
              key={preset.id}
              className="flex min-w-0 flex-col rounded-lg border border-[var(--border)]/70 p-3"
            >
              <div className="flex min-w-0 items-start justify-between gap-3">
                <h3 className="min-w-0 text-[13px] font-medium text-[var(--foreground)]">
                  {t(preset.label)}
                </h3>
                <span className="shrink-0 text-[11px] text-[var(--muted-foreground)]">
                  {t(`settings.presets.cost.${preset.resource_cost}`)}
                </span>
              </div>
              <p className="mt-1 text-[12px] leading-relaxed text-[var(--muted-foreground)]">
                {t(preset.description)}
              </p>

              <dl className="mt-3 space-y-1.5 text-[11.5px]">
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <dt className="text-[var(--muted-foreground)]">
                    {t("settings.presets.parser")}
                  </dt>
                  <dd className="min-w-0 font-mono text-[var(--foreground)]">
                    {preset.parser}
                  </dd>
                </div>
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <dt className="text-[var(--muted-foreground)]">
                    {t("settings.presets.prerequisites")}
                  </dt>
                  <dd className="min-w-0 text-[var(--foreground)]">
                    {preset.prerequisites
                      .map((item) =>
                        t(`settings.presets.prerequisite.${item}`),
                      )
                      .join(" · ")}
                  </dd>
                </div>
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <dt className="text-[var(--muted-foreground)]">
                    {t("settings.presets.credentials")}
                  </dt>
                  <dd className="min-w-0 text-[var(--foreground)]">
                    {preset.credentials
                      .map((item) => t(`settings.presets.credential.${item}`))
                      .join(" · ")}
                  </dd>
                </div>
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <dt className="text-[var(--muted-foreground)]">
                    {t("settings.presets.features")}
                  </dt>
                  <dd className="min-w-0 text-[var(--foreground)]">
                    {preset.unlocked_features
                      .map((item) => t(`settings.presets.feature.${item}`))
                      .join(" · ")}
                  </dd>
                </div>
              </dl>

              <button
                type="button"
                onClick={() => void load(preset)}
                disabled={saving || !enabled}
                className="mt-4 inline-flex w-fit items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-[12px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)] disabled:opacity-50"
              >
                {activeId === preset.id && (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                )}
                {t("settings.presets.loadDraft")}
              </button>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
