"use client";

import { useEffect, useMemo, useState } from "react";
import { Check, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import Modal from "@/components/common/Modal";
import ProviderIcon from "@/components/common/ProviderIcon";
import { apiFetch, apiUrl } from "@/lib/api";
import type {
  CatalogProfile,
  ServiceName,
} from "@/features/settings/store/SettingsStore";
import { inputClass } from "./shared";

/**
 * Lists what an endpoint serves and lets the user pick which ids to add.
 *
 * Adding, not replacing: the models already under a provider are the user's
 * curated list (names, context windows, capability overrides), so a fetched
 * list only ever appends. Ids already present are shown but cannot be picked
 * again.
 */
export function ModelListPicker({
  service,
  profile,
  existing,
  onAdd,
  onClose,
}: {
  service: Extract<ServiceName, "llm" | "task">;
  profile: CatalogProfile;
  existing: string[];
  onAdd: (ids: string[]) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [ids, setIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const present = useMemo(() => new Set(existing), [existing]);

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      setLoading(true);
      setError("");
      try {
        const response = await apiFetch(apiUrl("/api/settings/fetch-models"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            binding: profile.binding ?? "",
            base_url: profile.base_url ?? "",
            api_key: profile.api_key || null,
            profile_id: profile.id,
            service,
            api_format: profile.api_format ?? "auto",
          }),
        });
        const payload = (await response.json().catch(() => ({}))) as {
          models?: { id: string }[];
          detail?: string;
        };
        if (!response.ok) {
          throw new Error(payload.detail || `HTTP ${response.status}`);
        }
        const fetched = (payload.models ?? []).map((item) => item.id);
        if (cancelled) return;
        setIds(fetched);
        if (fetched.length === 0)
          setError(t("The provider returned no models."));
      } catch (caught) {
        if (cancelled) return;
        setError(
          caught instanceof Error
            ? caught.message
            : t("Could not reach provider."),
        );
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void run();
    return () => {
      cancelled = true;
    };
  }, [
    profile.id,
    profile.binding,
    profile.base_url,
    profile.api_key,
    profile.api_format,
    service,
    t,
  ]);

  const needle = query.trim().toLowerCase();
  const visible = needle
    ? ids.filter((id) => id.toLowerCase().includes(needle))
    : ids;

  const toggle = (id: string) => {
    if (present.has(id)) return;
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <Modal
      isOpen
      onClose={onClose}
      title={t("List models")}
      titleIcon={<ProviderIcon provider={profile.binding ?? ""} size={15} />}
      width="md"
      footer={
        <div className="flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="inline-flex h-8 items-center rounded-lg px-3 text-[12px] text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
          >
            {t("Cancel")}
          </button>
          <button
            type="button"
            disabled={selected.size === 0}
            onClick={() => onAdd([...selected])}
            className="inline-flex h-8 items-center rounded-lg bg-[var(--foreground)] px-3.5 text-[12px] font-medium text-[var(--background)] transition-opacity hover:opacity-90 disabled:opacity-40"
          >
            {t("Add selected ({{count}})", { count: selected.size })}
          </button>
        </div>
      }
    >
      <div className="space-y-3 p-5">
        <p className="text-[11.5px] text-[var(--muted-foreground)]">
          {t("Select the models to add to this provider.")}
        </p>
        <input
          className={inputClass}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={t("Search models…")}
          disabled={loading || ids.length === 0}
        />
        {loading ? (
          <div className="flex items-center gap-2 py-6 text-[12px] text-[var(--muted-foreground)]">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            {t("Fetching models…")}
          </div>
        ) : error ? (
          <p className="py-4 text-[12px] text-amber-600 dark:text-amber-400">
            {error}
          </p>
        ) : visible.length === 0 ? (
          <p className="py-4 text-[12px] text-[var(--muted-foreground)]">
            {t("No models matched.")}
          </p>
        ) : (
          <div className="max-h-[50vh] overflow-y-auto rounded-lg border border-[var(--border)]">
            {visible.map((id, index) => {
              const added = present.has(id);
              const checked = selected.has(id);
              return (
                <button
                  key={id}
                  type="button"
                  onClick={() => toggle(id)}
                  disabled={added}
                  aria-pressed={checked}
                  className={`flex w-full items-center gap-3 px-3 py-2 text-left transition-colors ${
                    index === 0 ? "" : "border-t border-[var(--border)]/60"
                  } ${added ? "opacity-50" : "hover:bg-[var(--muted)]/40"}`}
                >
                  <span
                    className={`flex h-4 w-4 shrink-0 items-center justify-center rounded border ${
                      checked || added
                        ? "border-[var(--foreground)] bg-[var(--foreground)] text-[var(--background)]"
                        : "border-[var(--border)]"
                    }`}
                  >
                    {(checked || added) && <Check className="h-3 w-3" />}
                  </span>
                  <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-[var(--foreground)]">
                    {id}
                  </span>
                  {added && (
                    <span className="shrink-0 text-[11px] text-[var(--muted-foreground)]">
                      {t("Already added")}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        )}
      </div>
    </Modal>
  );
}
