"use client";

import { Fragment, useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { apiFetch, apiUrl } from "@/lib/api";
import { StatusStripDivider } from "@/components/settings/shared";

/**
 * Live resident-memory readout — the whole point of the settings status strip
 * now that the model/search items moved into their own pages.
 *
 * Backed by `/api/v1/system/memory` (deeptutor/runtime/memory_probe.py), which
 * walks the whole DeepTutor process tree — backend, the Next.js server, and
 * whatever sandboxes and subagent CLIs are alive — rather than just this
 * process. Its own endpoint, not part of `/system/status`: that snapshot
 * resolves model configs and is fetched once per mount, while this polls.
 *
 * Everything is inline rather than behind a hover: the per-process split is
 * the number you actually want when watching memory move, and hiding it makes
 * you chase a tooltip while the value changes underneath you.
 *
 * The endpoint answers `{available: false}` for non-admins and on platforms
 * where the tree can't be read, and this renders nothing in that case.
 */

const POLL_MS = 10_000;

/** One role in the tree; `count` collapses e.g. three live sandboxes into a row. */
interface MemoryProcess {
  label: string;
  count: number;
  rss_bytes: number;
}

interface MemoryUsage {
  available: boolean;
  total_rss_bytes?: number;
  limit_bytes?: number | null;
  available_bytes?: number | null;
  limit_source?: string;
  usage_ratio?: number | null;
  partial?: boolean;
  processes?: MemoryProcess[];
}

function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null) return "—";
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  return `${Math.round(bytes / 1024 ** 2)} MB`;
}

/** Green under two thirds, amber past it, red once the OOM killer is plausible. */
function pressureDotClass(ratio: number | null | undefined): string {
  if (ratio == null) return "bg-emerald-500";
  if (ratio >= 0.9) return "bg-red-400";
  if (ratio >= 0.7) return "bg-amber-400";
  return "bg-emerald-500";
}

export default function MemoryUsageItem() {
  const { t } = useTranslation();
  const [usage, setUsage] = useState<MemoryUsage | null>(null);

  const roleLabel = useCallback(
    (row: MemoryProcess) => {
      const known: Record<string, string> = {
        backend: t("Backend"),
        web: t("Frontend"),
        sandbox: t("Sandbox"),
        supervisor: t("Supervisor"),
        other: t("Other"),
      };
      const name = known[row.label] ?? row.label;
      return row.count > 1 ? `${name} ×${row.count}` : name;
    },
    [t],
  );

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const poll = async () => {
      try {
        const res = await apiFetch(apiUrl("/api/v1/system/memory"));
        if (cancelled) return;
        if (res.ok) setUsage((await res.json()) as MemoryUsage);
      } catch {
        // A failed probe is not worth a console entry every 10s; the strip
        // simply keeps the last reading until the next poll succeeds.
      }
      if (!cancelled) timer = setTimeout(poll, POLL_MS);
    };

    // Polling a hidden tab burns a request per user per 10s for a number
    // nobody is looking at; resume with an immediate read so the value is
    // fresh the moment the tab comes back.
    const onVisibility = () => {
      if (document.hidden) {
        if (timer) clearTimeout(timer);
        timer = null;
      } else if (timer === null) {
        void poll();
      }
    };

    void poll();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  if (!usage?.available) return null;

  const ratio = usage.usage_ratio ?? null;
  const percent = ratio == null ? null : Math.max(Math.round(ratio * 100), 1);
  const used = formatBytes(usage.total_rss_bytes);
  const summary =
    percent == null || !usage.limit_bytes
      ? used
      : t("{{used}} · {{percent}}% of {{total}}", {
          used,
          percent,
          total: formatBytes(usage.limit_bytes),
        });

  return (
    <Fragment>
      <StatusStripDivider />
      <div className="flex items-center gap-2.5">
        <span
          className={`h-2 w-2 shrink-0 rounded-full ${pressureDotClass(ratio)}`}
        />
        <div className="flex items-baseline gap-2">
          <span className="text-[13px] font-medium leading-none tracking-tight text-[var(--foreground)]">
            {t("Memory")}
          </span>
          <span className="text-[12px] leading-none tabular-nums text-[var(--muted-foreground)]">
            {summary}
          </span>
        </div>
      </div>

      <StatusStripDivider />
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1.5 text-[12px] leading-none text-[var(--muted-foreground)]">
        {(usage.processes ?? []).map((row) => (
          <span key={row.label} className="tabular-nums">
            {roleLabel(row)}{" "}
            <span className="text-[var(--foreground)]/70">
              {formatBytes(row.rss_bytes)}
            </span>
          </span>
        ))}
        <span className="tabular-nums">
          {usage.limit_source === "cgroup"
            ? t("Container available")
            : t("System available")}{" "}
          <span className="text-[var(--foreground)]/70">
            {formatBytes(usage.available_bytes)}
          </span>
        </span>
        {usage.partial && (
          <span
            title={t(
              "Only the backend and its own children. Start DeepTutor through the launcher to include the web server.",
            )}
          >
            {t("(backend only)")}
          </span>
        )}
      </div>
    </Fragment>
  );
}
