"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertCircle, Loader2, QrCode, Wifi } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  getPartnerChannelRuntime,
  type PartnerChannelRuntimeEntry,
} from "@/lib/partners-api";

const REFRESH_MS = 2500;

export default function ChannelRuntimeStatus({
  partnerId,
  channel,
  enabled,
}: {
  partnerId: string;
  channel: string;
  enabled: boolean;
}) {
  const { t } = useTranslation();
  const [entry, setEntry] = useState<PartnerChannelRuntimeEntry | null>(null);

  useEffect(() => {
    if (!enabled) {
      setEntry(null);
      return;
    }

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const refresh = async () => {
      try {
        const response = await getPartnerChannelRuntime(partnerId);
        if (!cancelled) setEntry(response.channels[channel] ?? null);
      } catch {
        if (!cancelled) setEntry(null);
      } finally {
        if (!cancelled) timer = setTimeout(refresh, REFRESH_MS);
      }
    };

    void refresh();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [channel, enabled, partnerId]);

  const setup = entry?.setup;
  const label = useMemo(() => {
    switch (setup?.status) {
      case "connected":
        return t("Connected");
      case "connecting":
      case "starting":
        return t("Connecting");
      case "running":
        return t("Listener running");
      case "waiting_for_scan":
        return t("Waiting for scan");
      case "action_required":
        return channel === "weixin"
          ? t("Waiting for scan")
          : t("Configuration required");
      case "unavailable":
        return t("Unavailable");
      case "error":
        return t("Connection failed");
      case "disconnected":
        return t("Not connected");
      default:
        return "";
    }
  }, [channel, setup?.status, t]);

  if (!setup?.status || !label) return null;

  const isError = setup.status === "error" || setup.status === "unavailable";
  const isBusy = setup.status === "connecting" || setup.status === "starting";
  const isConnected =
    setup.status === "connected" || setup.status === "running";

  return (
    <div
      className={`rounded-lg border px-3 py-2.5 text-[11px] ${
        isError
          ? "border-red-500/35 bg-red-500/10 text-red-700 dark:text-red-300"
          : "border-[var(--border)] bg-[var(--card)] text-[var(--muted-foreground)]"
      }`}
    >
      <div className="flex items-center gap-2 font-medium">
        {isBusy ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
        ) : isError ? (
          <AlertCircle className="h-3.5 w-3.5" aria-hidden />
        ) : isConnected ? (
          <Wifi className="h-3.5 w-3.5 text-emerald-500" aria-hidden />
        ) : (
          <QrCode className="h-3.5 w-3.5 text-[var(--primary)]" aria-hidden />
        )}
        <span>
          {t("Status")}: {label}
        </span>
      </div>
      {setup.message && (
        <p className="mt-1.5 leading-relaxed">{t(setup.message)}</p>
      )}
      {setup.qr_data_url ? (
        /* QR data URLs are generated in-process and cannot use Next's image
           optimizer; this mirrors the existing channel-onboarding panel. */
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={setup.qr_data_url}
          alt={t("Scan to connect")}
          className="mt-2 h-[148px] w-[148px] rounded-md bg-white p-1.5"
        />
      ) : setup.qr_payload ? (
        <p className="mt-2 break-all font-mono text-[10px]">
          {setup.qr_payload}
        </p>
      ) : null}
    </div>
  );
}
