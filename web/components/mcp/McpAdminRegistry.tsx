"use client";

import { useState } from "react";
import { ChevronDown, Loader2, Plus, ShieldCheck } from "lucide-react";
import { useTranslation } from "react-i18next";

import McpServerForm from "@/components/mcp/McpServerForm";
import McpServerList from "@/components/mcp/McpServerList";
import { ADMIN_MCP_SURFACE } from "@/components/mcp/surface";
import { useMcpServers } from "@/hooks/useMcpServers";
import { emptyMcpServerConfig } from "@/lib/mcp-api";

/**
 * The deployment-wide MCP registry, embedded on `/space/mcp` for admins.
 *
 * This is the old `/settings/mcp` page. It lives here so both kinds of server
 * are managed in one place, and it stays behind an `isAdmin` check by its
 * caller: stdio is selectable on this surface, and a stdio `command` runs on the
 * host as the application user.
 *
 * Collapsed by default — the page is primarily about the reader's own servers,
 * and an admin opens this when they mean to change what everyone gets.
 */
export default function McpAdminRegistry() {
  const { t } = useTranslation();
  const mcp = useMcpServers(ADMIN_MCP_SURFACE);
  const [open, setOpen] = useState(false);

  return (
    <section
      className={`overflow-hidden rounded-xl border transition-colors ${
        open
          ? "border-[var(--border)] bg-[var(--card)] shadow-sm"
          : "border-[var(--border)]/60 bg-[var(--card)]/40"
      }`}
    >
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left transition-colors hover:bg-[var(--muted)]/30"
      >
        <span className="flex min-w-0 items-center gap-2 text-[13px] font-medium text-[var(--foreground)]">
          <ShieldCheck
            size={14}
            strokeWidth={1.7}
            className="shrink-0 text-[var(--muted-foreground)]"
          />
          {t("Deployment registry")}
          <span className="rounded-full bg-[var(--muted)] px-1.5 py-0.5 text-[10px] tabular-nums text-[var(--muted-foreground)]">
            {mcp.serverNames.length}
          </span>
          <span className="rounded-full border border-[var(--border)] px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
            {t("Admin")}
          </span>
        </span>
        <ChevronDown
          size={14}
          className={`shrink-0 text-[var(--muted-foreground)] transition-transform duration-200 ${
            open ? "rotate-180" : ""
          }`}
        />
      </button>

      {open && (
        <div className="space-y-4 border-t border-[var(--border)]/70 px-4 pb-4 pt-3">
          <p className="text-[11.5px] leading-relaxed text-[var(--muted-foreground)]">
            {t(
              "Servers every account on this deployment can use. Local commands (stdio) are only configurable here.",
            )}
          </p>

          {mcp.loadError && (
            <div className="rounded-lg border border-red-500/40 bg-red-500/5 px-3 py-2 text-[12px] text-red-500">
              {t("Failed to load MCP servers")}: {mcp.loadError}
            </div>
          )}
          {mcp.saveError && (
            <div className="rounded-lg border border-red-500/40 bg-red-500/5 px-3 py-2 text-[12px] text-red-500">
              {t("Failed to save")}: {mcp.saveError}
            </div>
          )}

          {!mcp.servers && !mcp.loadError && (
            <div className="flex items-center gap-2 text-[12px] text-[var(--muted-foreground)]">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              {t("Loading...")}
            </div>
          )}

          {mcp.servers && (
            <div className="space-y-4">
              <McpServerList
                surface={ADMIN_MCP_SURFACE}
                servers={mcp.servers}
                names={mcp.serverNames}
                statusByName={mcp.statusByName}
                expanded={mcp.expanded}
                editingName={mcp.editingKey}
                saving={mcp.saving}
                onToggleExpanded={mcp.toggleExpanded}
                onToggleEnabled={mcp.toggleEnabled}
                onEdit={mcp.toggleEditing}
                onCancelEdit={mcp.cancelEditing}
                onDelete={mcp.remove}
                onSave={mcp.save}
              />

              {mcp.editingKey === "" ? (
                <div className="rounded-xl border border-[var(--border)]/60 bg-[var(--background)]/40 px-5 py-5">
                  <div className="mb-4 text-[13px] font-semibold text-[var(--foreground)]">
                    {t("Add MCP server")}
                  </div>
                  <McpServerForm
                    surface={ADMIN_MCP_SURFACE}
                    originalName=""
                    initialName=""
                    initialConfig={emptyMcpServerConfig()}
                    existingNames={mcp.serverNames}
                    saving={mcp.saving}
                    onCancel={mcp.cancelEditing}
                    onSave={mcp.save}
                  />
                </div>
              ) : (
                <button
                  type="button"
                  onClick={mcp.startAdding}
                  disabled={mcp.saving}
                  className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--card)] px-3.5 py-2 text-[12.5px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <Plus className="h-3.5 w-3.5" />
                  {t("Add server")}
                </button>
              )}

              {/* Same transparency the settings toolbar gave every page it
                  hosted: say where the parameters actually live. */}
              <p className="text-[11.5px] text-[var(--muted-foreground)]">
                {t("Saved to")}{" "}
                <span className="font-mono text-[var(--foreground)]/65">
                  {"data/user/settings/mcp.json"}
                </span>
              </p>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
