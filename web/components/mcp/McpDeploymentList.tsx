"use client";

import { Plug } from "lucide-react";
import { useTranslation } from "react-i18next";

import McpStatusBadge from "@/components/mcp/McpStatusBadge";
import type { McpStatusRow } from "@/lib/mcp-api";

/**
 * The deployment's own MCP servers, read-only.
 *
 * They are listed here — on a page about *your* servers — so "which tools do I
 * have?" has one answer instead of two. Nothing is editable: these belong to the
 * administrator's registry.
 */
export default function McpDeploymentList({
  names,
  statusRows,
}: {
  names: string[];
  statusRows: McpStatusRow[];
}) {
  const { t } = useTranslation();
  if (names.length === 0) return null;

  const statusByName = new Map(statusRows.map((row) => [row.name, row]));

  return (
    <section className="space-y-2">
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="text-[13px] font-semibold text-[var(--foreground)]">
          {t("Provided by this deployment")}
        </h3>
        <span className="text-[11.5px] text-[var(--muted-foreground)]">
          {t("Read-only")}
        </span>
      </div>
      <ul className="overflow-hidden rounded-xl border border-[var(--border)]/60 bg-[var(--card)]/30">
        {names.map((name, idx) => {
          const row = statusByName.get(name);
          return (
            <li
              key={name}
              className={`flex items-center gap-3 px-5 py-3 ${
                idx > 0 ? "border-t border-[var(--border)]/50" : ""
              }`}
            >
              <Plug className="h-3.5 w-3.5 shrink-0 text-[var(--muted-foreground)]" />
              <span className="min-w-0 flex-1 truncate font-mono text-[13px] text-[var(--foreground)]">
                {name}
              </span>
              <span className="shrink-0 text-[11.5px] text-[var(--muted-foreground)]">
                {t("{{count}} tools", { count: row?.tools.length ?? 0 })}
              </span>
              <McpStatusBadge
                status={row?.status ?? "connecting"}
                error={row?.error}
              />
            </li>
          );
        })}
      </ul>
    </section>
  );
}
