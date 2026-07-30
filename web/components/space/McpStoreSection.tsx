"use client";

import { useState } from "react";
import { AlertTriangle, Loader2, Plug, Plus } from "lucide-react";
import { useTranslation } from "react-i18next";

import McpAdminRegistry from "@/components/mcp/McpAdminRegistry";
import McpCatalogBrowser from "@/components/mcp/McpCatalogBrowser";
import McpDeploymentList from "@/components/mcp/McpDeploymentList";
import McpServerForm from "@/components/mcp/McpServerForm";
import McpServerList from "@/components/mcp/McpServerList";
import { SPACE_MCP_SURFACE } from "@/components/mcp/surface";
import SpaceSectionHeader from "@/components/space/SpaceSectionHeader";
import { useAuthStatus } from "@/hooks/useAuthStatus";
import { useMcpServers } from "@/hooks/useMcpServers";
import { emptyMcpServerConfig } from "@/lib/mcp-api";

type Tab = "installed" | "store";

/**
 * MCP Services — the per-user store.
 *
 * Two tabs over one surface: what this account has connected, and the curated
 * catalog it can install from. Only remote servers appear anywhere here; a stdio
 * server is a command on the host, so it stays in the deployment registry (which
 * an admin reaches through the block at the bottom).
 */
export default function McpStoreSection() {
  const { t } = useTranslation();
  const { isAdmin, loading: authLoading } = useAuthStatus();
  const mcp = useMcpServers(SPACE_MCP_SURFACE);
  const [tab, setTab] = useState<Tab>("installed");

  const view = mcp.userView;
  const maxServers = view?.maxServers ?? 0;
  const atCapacity = maxServers > 0 && mcp.serverNames.length >= maxServers;

  return (
    <div className="space-y-6">
      <SpaceSectionHeader
        icon={Plug}
        title={t("MCP Services")}
        description={t(
          "Connect hosted MCP services to your account — their tools become available to the chat agent.",
        )}
        meta={
          <span className="rounded-full border border-[var(--border)] bg-[var(--card)] px-2 py-0.5 text-[10.5px] font-medium text-[var(--muted-foreground)]">
            {maxServers > 0
              ? t("{{used}} / {{max}} connected", {
                  used: mcp.serverNames.length,
                  max: maxServers,
                })
              : t("{{count}} connected", { count: mcp.serverNames.length })}
          </span>
        }
      />

      <div className="border-b border-[var(--border)]">
        <div className="flex gap-1">
          <TabButton
            label={t("Installed")}
            count={mcp.serverNames.length}
            active={tab === "installed"}
            onClick={() => setTab("installed")}
          />
          <TabButton
            label={t("Store")}
            active={tab === "store"}
            onClick={() => setTab("store")}
          />
        </div>
      </div>

      {tab === "store" ? (
        <McpCatalogBrowser
          surface={SPACE_MCP_SURFACE}
          // Nullable on purpose: until the list has loaded, "not installed" and
          // "nothing loaded yet" are different answers, and collapsing them to
          // `{}` is what makes an installed service read as available.
          installedServers={mcp.servers}
          atCapacity={atCapacity}
          onInstalled={mcp.applyState}
        />
      ) : (
        <div className="space-y-5">
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

          {!mcp.servers && !mcp.loadError ? (
            <div className="flex items-center justify-center py-16">
              <Loader2 className="h-4 w-4 animate-spin text-[var(--muted-foreground)]" />
            </div>
          ) : (
            mcp.servers && (
              <>
                <McpServerList
                  surface={SPACE_MCP_SURFACE}
                  servers={mcp.servers}
                  names={mcp.serverNames}
                  statusByName={mcp.statusByName}
                  configuredSecrets={view?.configuredSecrets}
                  oauth={view?.oauth}
                  expanded={mcp.expanded}
                  editingName={mcp.editingKey}
                  saving={mcp.saving}
                  onToggleExpanded={mcp.toggleExpanded}
                  onToggleEnabled={mcp.toggleEnabled}
                  onEdit={mcp.toggleEditing}
                  onCancelEdit={mcp.cancelEditing}
                  onDelete={mcp.remove}
                  onSave={mcp.save}
                  onAuthorize={(name) => void mcp.authorize(name)}
                />

                {mcp.editingKey === "" ? (
                  <div className="rounded-xl border border-[var(--border)]/60 bg-[var(--card)]/40 px-5 py-5">
                    <div className="mb-4 text-[13px] font-semibold text-[var(--foreground)]">
                      {t("Add a server by URL")}
                    </div>
                    <McpServerForm
                      surface={SPACE_MCP_SURFACE}
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
                  <div className="flex flex-wrap items-center gap-3">
                    <button
                      type="button"
                      onClick={mcp.startAdding}
                      disabled={mcp.saving || atCapacity}
                      className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--card)] px-3.5 py-2 text-[12.5px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)] disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      <Plus className="h-3.5 w-3.5" />
                      {t("Add a server by URL")}
                    </button>
                    <button
                      type="button"
                      onClick={() => setTab("store")}
                      className="text-[12.5px] font-medium text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
                    >
                      {t("Browse the store")}
                    </button>
                    {atCapacity && (
                      <span className="text-[11.5px] text-amber-700 dark:text-amber-400">
                        {t(
                          "You have reached your MCP server limit. Remove one first.",
                        )}
                      </span>
                    )}
                  </div>
                )}

                {view && view.rejected.length > 0 && (
                  <RejectedServers
                    rows={view.rejected}
                    onRemove={(name) => void mcp.removeRejected(name)}
                    busy={mcp.saving}
                  />
                )}

                {/* Where these live, in the same spirit as the settings
                    toolbar's storage line. The file is per account. */}
                <p className="text-[11.5px] text-[var(--muted-foreground)]">
                  {t("Saved to")}{" "}
                  <span className="font-mono text-[var(--foreground)]/65">
                    {"data/system/user-mcp/<your account>.json"}
                  </span>
                </p>

                {/* One block, not both: for an admin the deployment's servers
                    are editable, so listing them read-only as well would show
                    every row twice. Held back until the role is known rather
                    than flashing the read-only list at an admin. */}
                {authLoading ? null : isAdmin ? (
                  <McpAdminRegistry />
                ) : (
                  view && (
                    <McpDeploymentList
                      names={view.deployment.servers}
                      statusRows={view.deployment.status}
                    />
                  )
                )}
              </>
            )
          )}
        </div>
      )}
    </div>
  );
}

/**
 * Entries that exist in the account's config file but will not be connected.
 *
 * Shown rather than filtered out: silently listing fewer servers than the file
 * holds is how someone spends an afternoon wondering where their server went.
 */
function RejectedServers({
  rows,
  onRemove,
  busy,
}: {
  rows: { name: string; reason: string }[];
  onRemove: (name: string) => void;
  busy: boolean;
}) {
  const { t } = useTranslation();
  return (
    <section className="space-y-2">
      <h3 className="text-[13px] font-semibold text-[var(--foreground)]">
        {t("Not connected")}
      </h3>
      <ul className="overflow-hidden rounded-xl border border-amber-500/25 bg-amber-500/5">
        {rows.map((row, idx) => (
          <li
            key={row.name}
            className={`flex items-start gap-3 px-5 py-3 ${
              idx > 0 ? "border-t border-amber-500/20" : ""
            }`}
          >
            <AlertTriangle
              size={14}
              className="mt-0.5 shrink-0 text-amber-600 dark:text-amber-400"
            />
            <div className="min-w-0 flex-1">
              <span className="font-mono text-[13px] text-[var(--foreground)]">
                {row.name}
              </span>
              <p className="mt-0.5 text-[12px] leading-relaxed text-[var(--muted-foreground)]">
                {row.reason}
              </p>
            </div>
            {/* These entries are not in the servers map, so the ordinary
                diff-based delete would issue no request — without this the row
                is one the user can see and not get rid of. */}
            <button
              type="button"
              disabled={busy}
              onClick={() => onRemove(row.name)}
              className="shrink-0 rounded-md px-2 py-1 text-[11.5px] text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-red-500 disabled:opacity-50"
            >
              {t("Remove")}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

function TabButton({
  label,
  count,
  active,
  onClick,
}: {
  label: string;
  count?: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`relative px-4 py-2 text-[13px] font-medium transition-colors ${
        active
          ? "text-[var(--foreground)]"
          : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
      }`}
    >
      {label}
      {typeof count === "number" && (
        <span className="ml-2 rounded-full bg-[var(--muted)] px-1.5 py-0.5 text-[10px] font-normal text-[var(--muted-foreground)]">
          {count}
        </span>
      )}
      {active && (
        <span
          aria-hidden
          className="absolute -bottom-px left-0 right-0 h-[2px] bg-[var(--foreground)]"
        />
      )}
    </button>
  );
}
