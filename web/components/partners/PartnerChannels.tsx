"use client";

/**
 * Channel configuration panel — Partners channel-config logic preserved:
 * schema-driven form for any channel (built-in or plugin), secret masking
 * with explicit reveal, delivery flags, and live listener reload on save.
 */

import { useCallback, useEffect, useState } from "react";
import { Loader2, Save } from "lucide-react";
import { useTranslation } from "react-i18next";
import { apiFetch, apiUrl } from "@/lib/api";
import {
  getChannelSchemas,
  type ChannelsSchemaResponse,
} from "@/lib/partners-api";
import {
  SchemaField,
  defaultFor,
  type JsonSchema,
} from "@/components/partners/schema-form";
import ChannelIcon from "@/components/partners/ChannelIcon";

const LEGACY_GLOBAL_DELIVERY_KEYS = new Set([
  "send_progress",
  "send_tool_hints",
  "sendProgress",
  "sendToolHints",
]);

function stripLegacyGlobalDelivery(channels: Record<string, unknown>) {
  return Object.fromEntries(
    Object.entries(channels).filter(
      ([key]) => !LEGACY_GLOBAL_DELIVERY_KEYS.has(key),
    ),
  );
}

export default function PartnerChannels({
  partnerId,
  onToast,
}: {
  partnerId: string;
  onToast: (msg: string) => void;
}) {
  const { t } = useTranslation();
  const [schemaCatalog, setSchemaCatalog] =
    useState<ChannelsSchemaResponse | null>(null);
  const [channels, setChannels] = useState<Record<string, unknown>>({});
  const [activeChannel, setActiveChannel] = useState<string | null>(null);
  const [reloadError, setReloadError] = useState<string | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(true);
  const [saving, setSaving] = useState(false);
  /** dot-paths of secrets the user has explicitly toggled to plaintext. */
  const [revealed, setRevealed] = useState<Set<string>>(new Set());

  useEffect(() => {
    void (async () => {
      try {
        setSchemaCatalog(await getChannelSchemas());
      } catch {
        /* leave catalog null → renders fallback message */
      }
    })();
  }, []);

  const loadDetail = useCallback(async () => {
    setLoadingDetail(true);
    try {
      // Edit form needs raw secrets to populate fields. Default GET masks them.
      const res = await apiFetch(
        apiUrl(`/api/v1/partners/${partnerId}?include_secrets=true`),
      );
      if (!res.ok) return;
      const data = await res.json();
      const raw = (data.channels ?? {}) as Record<string, unknown>;
      setChannels(stripLegacyGlobalDelivery(raw));
      setReloadError(
        typeof data.last_reload_error === "string"
          ? data.last_reload_error
          : null,
      );
    } finally {
      setLoadingDetail(false);
    }
  }, [partnerId]);

  useEffect(() => {
    setRevealed(new Set());
    void loadDetail();
  }, [loadDetail]);

  // Default active channel: prefer one already enabled.
  useEffect(() => {
    if (activeChannel || !schemaCatalog) return;
    const names = Object.keys(schemaCatalog.channels);
    const enabled = names.find((n) => {
      const cfg = channels[n];
      return (
        cfg &&
        typeof cfg === "object" &&
        (cfg as Record<string, unknown>).enabled === true
      );
    });
    setActiveChannel(enabled ?? names[0] ?? null);
  }, [schemaCatalog, channels, activeChannel]);

  const toggleSecret = useCallback((path: string) => {
    setRevealed((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }, []);

  const setActiveChannelConfig = (next: unknown) => {
    if (!activeChannel) return;
    setChannels((prev) => ({ ...prev, [activeChannel]: next }));
  };

  const save = async () => {
    setSaving(true);
    try {
      const res = await apiFetch(apiUrl(`/api/v1/partners/${partnerId}`), {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ channels: stripLegacyGlobalDelivery(channels) }),
      });
      if (res.ok) {
        onToast(t("Channels saved"));
        await loadDetail();
      } else if (res.status === 422) {
        const err = (await res.json().catch(() => ({}))) as {
          detail?: { message?: string } | string;
        };
        const detail = err.detail;
        onToast(
          typeof detail === "string"
            ? detail
            : (detail?.message ?? t("Invalid channel configuration")),
        );
      } else {
        const err = (await res.json().catch(() => ({}))) as { detail?: string };
        onToast(err.detail ?? t("Save failed"));
      }
    } catch (error) {
      onToast(error instanceof Error ? error.message : t("Save failed"));
    } finally {
      setSaving(false);
    }
  };

  if (loadingDetail || !schemaCatalog) {
    return (
      <div className="flex justify-center py-10">
        <Loader2 className="h-5 w-5 animate-spin text-[var(--muted-foreground)]" />
      </div>
    );
  }

  const channelEntries = Object.entries(schemaCatalog.channels).sort(
    ([, a], [, b]) => a.display_name.localeCompare(b.display_name),
  );
  const activeEntry = activeChannel
    ? schemaCatalog.channels[activeChannel]
    : undefined;
  const activeValue =
    activeChannel &&
    channels[activeChannel] &&
    typeof channels[activeChannel] === "object"
      ? (channels[activeChannel] as Record<string, unknown>)
      : (activeEntry?.default_config ?? {});
  const activeSecretSet = new Set(activeEntry?.secret_fields ?? []);

  return (
    <div className="space-y-4">
      {reloadError && (
        <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-[12px] text-amber-700 dark:text-amber-300">
          <strong className="font-medium">
            {t("Channel listeners failed to restart:")}
          </strong>{" "}
          <span className="font-mono">{reloadError}</span>{" "}
          <span className="opacity-80">
            {t("Config is saved on disk; stop and start the partner to apply.")}
          </span>
        </div>
      )}

      <div className="flex justify-end">
        <button
          type="button"
          onClick={() => void save()}
          disabled={saving}
          className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3 py-1.5 text-[12px] font-medium text-[var(--primary-foreground)] disabled:opacity-40"
        >
          {saving ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Save className="h-3.5 w-3.5" />
          )}
          {t("Save")}
        </button>
      </div>

      {/* Channel master-detail */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-[180px_1fr]">
        <aside className="h-fit rounded-xl border border-[var(--border)] p-2">
          <ul className="space-y-0.5">
            {channelEntries.map(([name, entry]) => {
              const cfg = channels[name] as Record<string, unknown> | undefined;
              const enabled = cfg?.enabled === true;
              const isActive = activeChannel === name;
              const unavailable = entry.available === false;
              return (
                <li key={name}>
                  <button
                    type="button"
                    onClick={() => setActiveChannel(name)}
                    title={unavailable ? entry.unavailable_reason : undefined}
                    className={`group flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-[13px] transition-colors ${
                      isActive
                        ? "bg-[var(--muted)] font-medium text-[var(--foreground)]"
                        : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                    } ${unavailable ? "opacity-45" : ""}`}
                  >
                    <ChannelIcon name={name} size={15} />
                    <span className="min-w-0 flex-1 truncate">
                      {entry.display_name}
                    </span>
                    {enabled && (
                      <span
                        aria-label={t("Enabled")}
                        title={t("Enabled")}
                        className="h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-500"
                      />
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        </aside>

        <section className="rounded-xl border border-[var(--border)] p-4 space-y-3">
          {!activeEntry ? (
            <p className="text-[13px] text-[var(--muted-foreground)]">
              {t("Select a channel.")}
            </p>
          ) : (
            <>
              <div className="flex items-center justify-between">
                <h3 className="inline-flex items-center gap-2 text-[14px] font-medium text-[var(--foreground)]">
                  <ChannelIcon name={activeEntry.name} size={18} />
                  {activeEntry.display_name}
                </h3>
                <code className="text-[11px] text-[var(--muted-foreground)]">
                  {activeEntry.name}
                </code>
              </div>
              {activeEntry.available === false || !activeEntry.json_schema ? (
                <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-[12px] text-amber-700 dark:text-amber-300">
                  <strong className="font-medium">
                    {t("This channel is not available on the server.")}
                  </strong>{" "}
                  {activeEntry.unavailable_reason && (
                    <span className="font-mono">
                      {activeEntry.unavailable_reason}
                    </span>
                  )}
                </div>
              ) : (
                <>
                  {(activeEntry.json_schema as JsonSchema).description && (
                    <p className="text-[11px] text-[var(--muted-foreground)]">
                      {(activeEntry.json_schema as JsonSchema).description}
                    </p>
                  )}
                  {Object.entries(
                    (activeEntry.json_schema as JsonSchema).properties ?? {},
                  ).map(([k, child]) => (
                    <SchemaField
                      key={k}
                      fieldKey={k}
                      schema={child}
                      value={activeValue[k] ?? defaultFor(child)}
                      onChange={(next) =>
                        setActiveChannelConfig({ ...activeValue, [k]: next })
                      }
                      secretFields={activeSecretSet}
                      path={k}
                      showSecretFor={revealed}
                      toggleSecret={toggleSecret}
                    />
                  ))}
                </>
              )}
            </>
          )}
        </section>
      </div>
    </div>
  );
}
