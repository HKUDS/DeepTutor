"use client";

/**
 * SAGE Memory Companion — Playground tile.
 *
 * Surfaces the SAGE plugin status in the Playground page. Renders one of
 * three states (Connected / Disabled / Disconnected) plus a degraded
 * "not configured" muted card when the backend probe fails. The tile is
 * additive and must never throw — any error path falls back to the muted
 * state instead of bubbling up to the Playground page.
 *
 * Strings are hardcoded English with t() wrapping so they slot into the
 * existing react-i18next pipeline (locales are key=text, see
 * web/locales/en/app.json). zh-CN translations can be added later by
 * dropping the same keys into web/locales/zh.
 *
 * TODO(i18n): Add zh-CN translations for the strings below if/when the
 * project routes Playground tiles through translated locales. For now,
 * react-i18next falls back to the English key text when no translation
 * exists, which matches every other Playground string.
 */

import { useEffect, useState } from "react";
import {
  AlertCircle,
  Brain,
  CheckCircle2,
  ExternalLink,
  Loader2,
  PauseCircle,
  Power,
  RefreshCw,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { apiUrl } from "@/lib/api";

type SageStatusState = "loading" | "connected" | "disabled" | "disconnected" | "unavailable";

interface SageStatusPayload {
  enabled: boolean;
  reachable: boolean;
  agent_id: string | null;
  node_url: string;
  last_observation_at: string | null;
  sdk_installed?: boolean;
  plugin_loaded?: boolean;
  detail?: string | null;
}

function deriveState(payload: SageStatusPayload | null): SageStatusState {
  if (!payload) return "unavailable";
  if (!payload.plugin_loaded) return "unavailable";
  if (!payload.enabled) return "disabled";
  if (payload.reachable) return "connected";
  return "disconnected";
}

function badgeStyles(state: SageStatusState): {
  label: string;
  classes: string;
  Icon: typeof CheckCircle2;
} {
  switch (state) {
    case "connected":
      return {
        label: "Connected",
        classes:
          "border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-300",
        Icon: CheckCircle2,
      };
    case "disabled":
      return {
        label: "Disabled",
        classes:
          "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300",
        Icon: PauseCircle,
      };
    case "disconnected":
      return {
        label: "Disconnected",
        classes:
          "border-rose-500/30 bg-rose-500/10 text-rose-600 dark:text-rose-300",
        Icon: AlertCircle,
      };
    case "loading":
      return {
        label: "Checking...",
        classes:
          "border-[var(--border)] bg-[var(--muted)] text-[var(--muted-foreground)]",
        Icon: Loader2,
      };
    default:
      return {
        label: "Not configured",
        classes:
          "border-[var(--border)] bg-[var(--muted)] text-[var(--muted-foreground)]",
        Icon: AlertCircle,
      };
  }
}

function buildSageDashboardUrl(nodeUrl: string): string {
  const base = (nodeUrl || "http://localhost:8080").replace(/\/$/, "");
  return `${base}/ui/`;
}

export default function SagePluginTile() {
  const { t } = useTranslation();
  const [status, setStatus] = useState<SageStatusPayload | null>(null);
  const [state, setState] = useState<SageStatusState>("loading");
  const [error, setError] = useState<string | null>(null);
  const [toggling, setToggling] = useState(false);

  const refresh = async () => {
    try {
      const res = await fetch(apiUrl("/api/v1/plugins/sage/status"));
      if (!res.ok) {
        setError(`HTTP ${res.status}`);
        setStatus(null);
        setState("unavailable");
        return;
      }
      const payload = (await res.json()) as SageStatusPayload;
      setStatus(payload);
      setState(deriveState(payload));
      setError(null);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "fetch failed");
      setStatus(null);
      setState("unavailable");
    }
  };

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      if (cancelled) return;
      await refresh();
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleToggle = async () => {
    if (!status) return;
    setToggling(true);
    try {
      const res = await fetch(apiUrl("/api/v1/plugins/sage/toggle"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: !status.enabled }),
      });
      if (!res.ok) {
        setError(`Toggle failed: HTTP ${res.status}`);
      } else {
        await refresh();
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "toggle failed");
    } finally {
      setToggling(false);
    }
  };

  const badge = badgeStyles(state);
  const BadgeIcon = badge.Icon;
  const isConnected = state === "connected";
  const showToggle = state === "connected" || state === "disabled" || state === "disconnected";
  const dashboardUrl = status ? buildSageDashboardUrl(status.node_url) : "";

  return (
    <section className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-[var(--border)] bg-[var(--background)] text-[var(--primary)]">
            <Brain size={16} strokeWidth={1.7} />
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-[14px] font-semibold tracking-tight text-[var(--foreground)]">
                {t("SAGE Memory Companion")}
              </h3>
              <span
                className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[10.5px] font-medium uppercase tracking-[0.08em] ${badge.classes}`}
              >
                <BadgeIcon
                  size={10}
                  strokeWidth={2}
                  className={state === "loading" ? "animate-spin" : undefined}
                />
                {t(badge.label)}
              </span>
            </div>
            <p className="mt-0.5 text-[12px] leading-relaxed text-[var(--muted-foreground)]">
              {t("Cross-tutor knowledge sharing")}
              {status?.node_url ? (
                <>
                  {" — "}
                  <span className="font-mono text-[11px] text-[var(--muted-foreground)]/80">
                    {status.node_url}
                  </span>
                </>
              ) : null}
            </p>
            {status?.detail && state !== "loading" ? (
              <p className="mt-1 text-[11px] leading-relaxed text-[var(--muted-foreground)]/80">
                {status.detail}
              </p>
            ) : null}
            {error ? (
              <p className="mt-1 text-[11px] leading-relaxed text-rose-500/90">
                {error}
              </p>
            ) : null}
            {status?.agent_id ? (
              <p className="mt-1 truncate text-[10.5px] font-mono text-[var(--muted-foreground)]/70">
                agent: {status.agent_id}
              </p>
            ) : null}
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-1.5">
          <button
            type="button"
            onClick={() => void refresh()}
            className="rounded-md border border-[var(--border)] bg-[var(--background)] p-1.5 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            aria-label={t("Refresh SAGE status")}
            title={t("Refresh SAGE status")}
          >
            <RefreshCw size={12} strokeWidth={1.8} />
          </button>
          {isConnected && dashboardUrl ? (
            <a
              href={dashboardUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 rounded-md border border-[var(--primary)]/40 bg-[var(--primary)]/10 px-2.5 py-1.5 text-[11.5px] font-medium text-[var(--primary)] transition-colors hover:bg-[var(--primary)]/15"
            >
              <ExternalLink size={11} strokeWidth={1.8} />
              {t("Open SAGE Dashboard")}
            </a>
          ) : null}
          {showToggle ? (
            <button
              type="button"
              onClick={() => void handleToggle()}
              disabled={toggling}
              className={`inline-flex items-center gap-1 rounded-md border px-2.5 py-1.5 text-[11.5px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
                status?.enabled
                  ? "border-[var(--border)] bg-[var(--background)] text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
                  : "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 hover:bg-emerald-500/15 dark:text-emerald-300"
              }`}
            >
              {toggling ? (
                <Loader2 size={11} strokeWidth={1.8} className="animate-spin" />
              ) : (
                <Power size={11} strokeWidth={1.8} />
              )}
              {status?.enabled ? t("Disable") : t("Enable")}
            </button>
          ) : null}
        </div>
      </div>
    </section>
  );
}
