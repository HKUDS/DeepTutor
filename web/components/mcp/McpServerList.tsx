"use client";

import { Plug } from "lucide-react";
import { useTranslation } from "react-i18next";

import McpServerForm from "@/components/mcp/McpServerForm";
import McpServerRow from "@/components/mcp/McpServerRow";
import McpToolList from "@/components/mcp/McpToolList";
import type { McpSurface } from "@/components/mcp/surface";
import type { McpServerConfig, McpStatusRow } from "@/lib/mcp-api";

export default function McpServerList({
  surface,
  servers,
  names,
  statusByName,
  configuredSecrets,
  oauth,
  expanded,
  editingName,
  saving,
  onToggleExpanded,
  onToggleEnabled,
  onEdit,
  onCancelEdit,
  onDelete,
  onSave,
  onAuthorize,
}: {
  surface: McpSurface;
  servers: Record<string, McpServerConfig>;
  names: string[];
  statusByName: Map<string, McpStatusRow>;
  /** Server name → the credential fields that have a stored value. */
  configuredSecrets?: Record<string, readonly string[]>;
  /** Server name → OAuth state, for the servers that need one. */
  oauth?: Record<string, { required: boolean; authorized: boolean }>;
  expanded: Set<string>;
  /** A server name while editing it, `""` while adding, `null` otherwise. */
  editingName: string | null;
  saving: boolean;
  onToggleExpanded: (name: string) => void;
  onToggleEnabled: (name: string) => void;
  onEdit: (name: string) => void;
  onAuthorize?: (name: string) => void;
  onCancelEdit: () => void;
  onDelete: (name: string) => void;
  onSave: (
    originalName: string | "",
    name: string,
    cfg: McpServerConfig,
  ) => Promise<boolean>;
}) {
  const { t } = useTranslation();

  if (names.length === 0) {
    // The add form carries its own framing, so the placeholder would just
    // duplicate its heading while it is open.
    if (editingName !== null) return null;
    return (
      <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-[var(--border)]/70 bg-[var(--card)]/30 px-6 py-14 text-center">
        <div className="flex h-10 w-10 items-center justify-center rounded-full bg-[var(--muted)]/60">
          <Plug className="h-4 w-4 text-[var(--muted-foreground)]" />
        </div>
        <div className="text-[14px] font-medium text-[var(--foreground)]">
          {t("No MCP servers yet")}
        </div>
        <p className="max-w-md text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
          {t(
            "Add a server to expose its tools to the chat agent. Test the connection first, then save.",
          )}
        </p>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-[var(--border)]/60 bg-[var(--card)]/40">
      {names.map((name, idx) => {
        const cfg = servers[name];
        const status = statusByName.get(name);
        const isExpanded = expanded.has(name);
        const isEditing = editingName === name;
        return (
          <div
            key={name}
            className={
              idx > 0 ? "border-t border-[var(--border)]/50" : undefined
            }
          >
            <McpServerRow
              name={name}
              cfg={cfg}
              status={status}
              secretFields={configuredSecrets?.[name]}
              oauthAuthorized={oauth?.[name]?.authorized}
              onAuthorize={onAuthorize ? () => onAuthorize(name) : undefined}
              isExpanded={isExpanded}
              saving={saving}
              onToggleExpanded={() => onToggleExpanded(name)}
              onToggleEnabled={() => onToggleEnabled(name)}
              onEdit={() => onEdit(name)}
              onDelete={() => onDelete(name)}
            />
            {isExpanded && status && status.tools.length > 0 && (
              <McpToolList tools={status.tools} />
            )}
            {isEditing && (
              <div className="border-t border-[var(--border)]/40 bg-[var(--background)]/40 px-5 py-5">
                <McpServerForm
                  surface={surface}
                  originalName={name}
                  initialName={name}
                  initialConfig={cfg}
                  existingNames={names}
                  saving={saving}
                  onCancel={onCancelEdit}
                  onSave={onSave}
                />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
