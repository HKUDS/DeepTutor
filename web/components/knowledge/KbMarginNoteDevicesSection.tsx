"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  AlertTriangle,
  Check,
  Copy,
  Loader2,
  Plus,
  Smartphone,
  Trash2,
} from "lucide-react";
import {
  getMarginNote4Status,
  listMarginNote4Devices,
  pairMarginNote4Device,
  revokeMarginNote4Device,
  type MarginNoteDevice,
  type MarginNoteLibraryStatus,
  type MarginNotePairing,
} from "@/lib/marginnote4-api";
import {
  formatKnowledgeTimestamp,
  type KnowledgeBase,
} from "@/lib/knowledge-helpers";

/**
 * Devices paired to a connected MarginNote 4 library.
 *
 * The library has no documents of its own — this is where its content comes
 * from. Pairing mints a token the MN4 add-on presents on every sync; the server
 * keeps only a hash, so the plaintext is shown here once and never again.
 */
export default function KbMarginNoteDevicesSection({
  kb,
}: {
  kb: KnowledgeBase;
}) {
  const { t } = useTranslation();
  const [devices, setDevices] = useState<MarginNoteDevice[] | null>(null);
  const [status, setStatus] = useState<MarginNoteLibraryStatus | null>(null);
  const [deviceName, setDeviceName] = useState("");
  const [pairing, setPairing] = useState(false);
  const [issued, setIssued] = useState<MarginNotePairing | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [list, summary] = await Promise.all([
        listMarginNote4Devices(kb.name),
        getMarginNote4Status(kb.name),
      ]);
      setDevices(list);
      setStatus(summary);
      setError(null);
    } catch (err) {
      // An unpaired library has no store yet, which is not an error state —
      // report the failure but still render the empty case below.
      setDevices([]);
      setStatus(null);
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [kb.name]);

  useEffect(() => {
    void load();
  }, [load]);

  const handlePair = async () => {
    if (pairing) return;
    setPairing(true);
    setError(null);
    try {
      const result = await pairMarginNote4Device({
        kbName: kb.name,
        deviceName: deviceName.trim(),
      });
      setIssued(result);
      setCopied(false);
      setDeviceName("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPairing(false);
    }
  };

  const handleRevoke = async (deviceId: string) => {
    setError(null);
    try {
      await revokeMarginNote4Device({ kbName: kb.name, deviceId });
      if (issued?.device_id === deviceId) setIssued(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const handleCopy = async () => {
    if (!issued) return;
    try {
      await navigator.clipboard.writeText(
        `${issued.device_id}:${issued.token}`,
      );
      setCopied(true);
    } catch {
      // Clipboard permission denied — the value stays selectable on screen.
    }
  };

  const active = (devices || []).filter((device) => device.active);

  return (
    <div className="space-y-6">
      <section className="space-y-3">
        <div>
          <div className="text-[13px] font-medium text-[var(--foreground)]">
            {t("MarginNote 4 devices")}
          </div>
          <p className="mt-0.5 text-[11.5px] leading-relaxed text-[var(--muted-foreground)]">
            {t(
              "Pair a device to get a token, then paste it into the MarginNote 4 add-on. The add-on pushes notes, excerpts, cards and mindmap nodes into this library.",
            )}
          </p>
        </div>

        <dl className="grid gap-3 rounded-lg border border-[var(--border)] bg-[var(--background)] p-3 sm:grid-cols-2">
          <Field label={t("Synced objects")}>
            {status ? status.objects.toLocaleString() : "—"}
          </Field>
          <Field label={t("Active devices")}>
            {devices ? active.length.toLocaleString() : "—"}
          </Field>
        </dl>
      </section>

      <section className="space-y-3 rounded-lg border border-[var(--border)] bg-[var(--background)] p-3">
        <div>
          <div className="text-[12.5px] font-medium text-[var(--foreground)]">
            {t("Pair a device")}
          </div>
          <p className="mt-0.5 text-[11.5px] text-[var(--muted-foreground)]">
            {t("A name only helps you tell your devices apart later.")}
          </p>
        </div>
        <div className="flex gap-2">
          <input
            value={deviceName}
            onChange={(event) => setDeviceName(event.target.value)}
            disabled={pairing}
            placeholder={t("My iPad")}
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[12.5px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--foreground)]/25 disabled:opacity-50"
          />
          <button
            type="button"
            onClick={() => void handlePair()}
            disabled={pairing}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3 text-[12px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {pairing ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Plus className="h-3.5 w-3.5" />
            )}
            {t("Pair device")}
          </button>
        </div>

        {issued && (
          <div className="space-y-2 rounded-lg border border-amber-300 bg-amber-50 p-3 dark:border-amber-900/60 dark:bg-amber-950/20">
            <div className="flex items-center gap-1.5 text-[12px] font-medium text-amber-800 dark:text-amber-300">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
              {t("Copy this now — it is not shown again.")}
            </div>
            <div className="flex items-center gap-2">
              <code className="min-w-0 flex-1 select-all break-all rounded-md bg-[var(--background)] px-2 py-1.5 font-mono text-[11px] text-[var(--foreground)]">
                {issued.device_id}:{issued.token}
              </code>
              <button
                type="button"
                onClick={() => void handleCopy()}
                className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--background)] px-2.5 py-1 text-[12px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)]"
              >
                {copied ? (
                  <Check className="h-3 w-3" />
                ) : (
                  <Copy className="h-3 w-3" />
                )}
                {copied ? t("Copied") : t("Copy")}
              </button>
            </div>
          </div>
        )}
      </section>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
          {error}
        </div>
      )}

      <section className="space-y-3">
        <div className="text-[12.5px] font-medium text-[var(--foreground)]">
          {t("Paired devices")}
        </div>
        {devices === null ? (
          <div className="flex items-center gap-2 text-[12px] text-[var(--muted-foreground)]">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            {t("Loading…")}
          </div>
        ) : devices.length === 0 ? (
          <div className="rounded-lg border border-dashed border-[var(--border)] px-3 py-6 text-center text-[12px] text-[var(--muted-foreground)]">
            {t("No devices paired yet.")}
          </div>
        ) : (
          <ul className="divide-y divide-[var(--border)] overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--background)]">
            {devices.map((device) => (
              <li
                key={device.device_id}
                className="flex items-center gap-3 px-3 py-2.5"
              >
                <Smartphone className="h-3.5 w-3.5 shrink-0 text-[var(--muted-foreground)]" />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-[12.5px] font-medium text-[var(--foreground)]">
                      {device.device_name || t("Unnamed device")}
                    </span>
                    {!device.active && (
                      <span className="inline-flex shrink-0 items-center rounded-full bg-[var(--muted)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--muted-foreground)]">
                        {t("Revoked")}
                      </span>
                    )}
                  </div>
                  <div className="mt-0.5 text-[11px] text-[var(--muted-foreground)]">
                    {device.device_kind} · {t("Last seen")}{" "}
                    {formatKnowledgeTimestamp(device.last_seen) || "—"}
                  </div>
                </div>
                {device.active && (
                  <button
                    type="button"
                    onClick={() => void handleRevoke(device.device_id)}
                    className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-red-200 bg-red-50 px-2.5 py-1 text-[12px] font-medium text-red-700 transition-colors hover:bg-red-100 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300"
                  >
                    <Trash2 className="h-3 w-3" />
                    {t("Revoke")}
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <dt className="text-[10.5px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
        {label}
      </dt>
      <dd className="mt-0.5 text-[12.5px] text-[var(--foreground)]">
        {children}
      </dd>
    </div>
  );
}
