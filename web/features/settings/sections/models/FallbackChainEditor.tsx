"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowDown, ArrowUp, Loader2, Plus, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { inputClass } from "@/components/settings/shared";
import { useSettings } from "@/features/settings/store/SettingsStore";
import { apiFetch, apiUrl } from "@/lib/api";

import {
  availableChoices,
  fallbackChoices,
  sanitizeChain,
  withoutActive,
  type FallbackEntry,
} from "./fallback-chain";

const MAX_FALLBACKS = 4;

const emptyRow = (): FallbackEntry => ({ profile_id: "", model_id: "" });

/**
 * Edit `services.llm.fallbacks` (#2693): an ordered list of existing
 * profile/model pairs the turn may move to when the active one fails before
 * any output. The stored chain is what the runtime already reads; this editor
 * only writes it, through the same `apply/service` endpoint the provider
 * dialogs use.
 */
export function FallbackChainEditor() {
  const { t } = useTranslation();
  const { catalog, reloadSettings } = useSettings();
  const llm = catalog.services.llm;
  const choices = useMemo(() => fallbackChoices(llm.profiles || []), [llm.profiles]);
  const selectable = useMemo(
    () =>
      // The active model is not a fallback of itself: offering it here would
      // let the operator build a chain entry the save silently drops.
      choices.filter(
        (choice) =>
          !(
            choice.profileId === llm.active_profile_id &&
            choice.modelId === llm.active_model_id
          ),
      ),
    [choices, llm.active_model_id, llm.active_profile_id],
  );
  const stored = useMemo(
    () =>
      (llm.fallbacks ?? []).map((entry) => ({
        profile_id: entry.profile_id,
        model_id: entry.model_id,
      })),
    [llm.fallbacks],
  );

  const [rows, setRows] = useState<FallbackEntry[]>(stored);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  // The settings store loads asynchronously (and reloads after a save), so the
  // chain arrives *after* the first render. Without this sync a refresh shows an
  // empty editor even though the catalog holds a chain — and the next save would
  // then write that empty list back (#2693).
  const appliedSignature = useRef<string | null>(null);
  const storedSignature = useMemo(() => JSON.stringify(stored), [stored]);
  useEffect(() => {
    if (appliedSignature.current === storedSignature) return;
    appliedSignature.current = storedSignature;
    setRows(stored);
  }, [stored, storedSignature]);

  const dirty = useMemo(() => {
    const next = sanitizeChain(rows, choices, MAX_FALLBACKS);
    return JSON.stringify(next) !== JSON.stringify(stored);
  }, [choices, rows, stored]);

  const update = (index: number, patch: Partial<FallbackEntry>) => {
    setRows((current) =>
      current.map((row, position) => (position === index ? { ...row, ...patch } : row)),
    );
    setSaved(null);
  };

  const move = (index: number, delta: number) => {
    setRows((current) => {
      const target = index + delta;
      if (target < 0 || target >= current.length) return current;
      const next = [...current];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
    setSaved(null);
  };

  const save = async () => {
    setSaving(true);
    setError(null);
    setSaved(null);
    try {
      const chain = withoutActive(sanitizeChain(rows, choices, MAX_FALLBACKS), {
        profile_id: llm.active_profile_id,
        model_id: llm.active_model_id,
      });
      const response = await apiFetch(apiUrl("/api/settings/apply/service"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          service: "llm",
          config: { ...llm, fallbacks: chain },
        }),
      });
      const data = (await response.json().catch(() => ({}))) as { detail?: string };
      if (!response.ok) {
        throw new Error(data.detail || t("Could not save the fallback chain."));
      }
      await reloadSettings();
      setSaved(t("Fallback chain saved."));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="mb-6 rounded-xl border border-[var(--border)]/60 bg-[var(--card)] px-4 py-3">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-[13px] font-medium">
            {t("Fallback chain ({{count}} configured)", { count: stored.length })}
          </div>
          <div className="mt-0.5 text-[11.5px] leading-relaxed text-[var(--muted-foreground)]">
            {t(
              "When the active model fails before any output, DeepTutor tries these in order and returns to the primary once its cooldown ends.",
            )}
          </div>
        </div>
        <button
          type="button"
          className="rounded-lg border border-[var(--border)] px-2.5 py-1 text-[12px] font-medium disabled:opacity-40"
          onClick={() => {
            setRows((current) => [...current, emptyRow()]);
            setSaved(null);
          }}
          disabled={rows.length >= MAX_FALLBACKS || selectable.length <= rows.length}
        >
          <Plus className="mr-1 inline h-3.5 w-3.5" />
          {t("Add fallback")}
        </button>
      </div>

      {rows.length === 0 ? (
        <p className="mt-3 text-[12px] text-[var(--muted-foreground)]">
          {t("No fallback configured. The turn fails when the active model fails.")}
        </p>
      ) : (
        <ul className="mt-3 space-y-2">
          {rows.map((row, index) => {
            const selected = choices.find(
              (choice) =>
                choice.profileId === row.profile_id && choice.modelId === row.model_id,
            );
            return (
              <li key={`fallback-${index}`} className="flex items-center gap-2">
                <select
                  className={`${inputClass} flex-1`}
                  aria-label={t("Fallback {{index}}", { index: index + 1 })}
                  value={selected ? `${selected.profileId}:${selected.modelId}` : ""}
                  onChange={(event) => {
                    const [profileId, modelId] = event.target.value.split(":");
                    update(index, { profile_id: profileId, model_id: modelId });
                  }}
                >
                  <option value="">{t("Choose a configured model")}</option>
                  {availableChoices(selectable, rows, index).map((choice) => (
                    <option
                      key={`${choice.profileId}:${choice.modelId}`}
                      value={`${choice.profileId}:${choice.modelId}`}
                    >
                      {choice.label}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  className="rounded p-1 disabled:opacity-30"
                  onClick={() => move(index, -1)}
                  disabled={index === 0}
                  aria-label={t("Move up")}
                >
                  <ArrowUp className="h-3.5 w-3.5" />
                </button>
                <button
                  type="button"
                  className="rounded p-1 disabled:opacity-30"
                  onClick={() => move(index, 1)}
                  disabled={index === rows.length - 1}
                  aria-label={t("Move down")}
                >
                  <ArrowDown className="h-3.5 w-3.5" />
                </button>
                <button
                  type="button"
                  className="rounded p-1 text-red-600 dark:text-red-400"
                  onClick={() => {
                    setRows((current) => current.filter((_, position) => position !== index));
                    setSaved(null);
                  }}
                  aria-label={t("Remove fallback")}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </li>
            );
          })}
        </ul>
      )}

      <div className="mt-3 flex items-center gap-3">
        <button
          type="button"
          className="rounded-lg bg-[var(--foreground)] px-3 py-1.5 text-[12px] font-medium text-[var(--background)] disabled:opacity-40"
          onClick={() => void save()}
          disabled={!dirty || saving}
        >
          {saving ? <Loader2 className="mr-1 inline h-3.5 w-3.5 animate-spin" /> : null}
          {t("Save fallback chain")}
        </button>
        {saved && <span className="text-[11.5px] text-emerald-600">{saved}</span>}
        {error && <span className="text-[11.5px] text-red-600 dark:text-red-300">{error}</span>}
        <span className="ml-auto text-[11px] text-[var(--muted-foreground)]">
          {t("Order matters · up to {{max}}", { max: MAX_FALLBACKS })}
        </span>
      </div>
    </div>
  );
}
