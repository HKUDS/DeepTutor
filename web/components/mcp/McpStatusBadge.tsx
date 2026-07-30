"use client";

import { useTranslation } from "react-i18next";

import type { McpServerStatus } from "@/lib/mcp-api";

export default function McpStatusBadge({
  status,
  error,
}: {
  status: McpServerStatus;
  error?: string;
}) {
  const { t } = useTranslation();
  const labels: Record<McpServerStatus, string> = {
    connected: t("Connected"),
    connecting: t("Connecting"),
    error: t("Error"),
    needs_auth: t("Needs authorization"),
    disabled: t("Disabled"),
  };
  const dotClass: Record<McpServerStatus, string> = {
    connected: "bg-emerald-500",
    connecting: "bg-amber-400",
    error: "bg-red-500",
    // Amber, like connecting: nothing is broken, something is pending.
    needs_auth: "bg-amber-400",
    disabled: "bg-[var(--border)]",
  };
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border border-[var(--border)] bg-[var(--muted)]/30 px-2 py-0.5 text-[10.5px] font-medium text-[var(--muted-foreground)]"
      title={status === "error" && error ? error : undefined}
    >
      <span
        className={`h-1.5 w-1.5 rounded-full ${dotClass[status]}`}
        aria-hidden
      />
      {labels[status]}
    </span>
  );
}
