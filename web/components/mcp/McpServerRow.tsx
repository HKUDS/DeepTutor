"use client";

import { type ReactNode } from "react";
import {
  ChevronDown,
  KeyRound,
  Pencil,
  Plug,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { BrandGlyph } from "@/components/common/BrandIcon";
import { brandIconFor } from "@/lib/brand-icons";

import McpStatusBadge from "@/components/mcp/McpStatusBadge";
import {
  mcpRowStatus,
  resolveMcpTransport,
  type McpServerConfig,
  type McpStatusRow,
} from "@/lib/mcp-api";

export default function McpServerRow({
  name,
  cfg,
  status,
  secretFields,
  oauthAuthorized,
  isExpanded,
  saving,
  onToggleExpanded,
  onToggleEnabled,
  onEdit,
  onDelete,
  onAuthorize,
}: {
  name: string;
  cfg: McpServerConfig;
  status: McpStatusRow | undefined;
  /**
   * Credential fields that have a stored value. Only the field names exist on
   * the client — the values never leave the backend — so these render as
   * "configured" markers and nothing else.
   */
  secretFields?: readonly string[];
  /**
   * For an OAuth-backed server: whether this account has granted it. Undefined
   * for every other server, which needs no such step.
   */
  oauthAuthorized?: boolean;
  isExpanded: boolean;
  saving: boolean;
  onToggleExpanded: () => void;
  onToggleEnabled: () => void;
  onEdit: () => void;
  onDelete: () => void;
  onAuthorize?: () => void;
}) {
  const { t } = useTranslation();
  const transport = status?.transport || resolveMcpTransport(cfg) || "";
  const toolCount = status?.tools.length ?? 0;
  const rowStatus = mcpRowStatus(cfg, status);
  // Resolved here rather than rendered blindly: `BrandGlyph` yields null for an
  // unknown brand, but a JSX element is always truthy, so `?? plug` in the markup
  // would never fire.
  const brand = brandIconFor("mcp", cfg.catalog_entry || name);
  return (
    <div className="flex w-full items-start gap-3 px-5 py-4">
      {/* The mark comes from the catalog entry this server was installed from,
          not from its local name — the installer may have renamed it. A
          hand-written server has no provenance and keeps the generic plug. */}
      <span className="mt-0.5 shrink-0 text-[var(--muted-foreground)]">
        {brand ? (
          <BrandGlyph
            namespace="mcp"
            id={cfg.catalog_entry || name}
            size={14}
          />
        ) : (
          <Plug className="h-3.5 w-3.5" />
        )}
      </span>
      <button
        type="button"
        onClick={onToggleExpanded}
        className="flex min-w-0 flex-1 items-start gap-3 text-left"
        aria-expanded={isExpanded}
      >
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-[13px] font-medium text-[var(--foreground)]">
              {name}
            </span>
            {transport && (
              <span className="rounded-full bg-[var(--muted)]/40 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
                {transport}
              </span>
            )}
            <McpStatusBadge status={rowStatus} error={status?.error} />
          </div>
          <p className="mt-1 text-[12px] leading-relaxed text-[var(--muted-foreground)]">
            {cfg.command || cfg.url || t("Not configured")}
            {" · "}
            {t("{{count}} tools", { count: toolCount })}
          </p>
          {rowStatus === "error" && status?.error && (
            <p className="mt-1 text-[11.5px] leading-relaxed text-red-500">
              {status.error}
            </p>
          )}
          {secretFields && secretFields.length > 0 && (
            <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
              {secretFields.map((field) => (
                <span
                  key={field}
                  title={t("Stored on the server and never shown here.")}
                  className="inline-flex items-center gap-1 rounded-full border border-[var(--border)]/60 bg-[var(--muted)]/40 px-2 py-0.5 text-[10.5px] font-medium text-[var(--muted-foreground)]"
                >
                  <KeyRound className="h-2.5 w-2.5" />
                  <span className="font-mono">{field}</span>
                  <span className="opacity-70">{t("configured")}</span>
                </span>
              ))}
            </div>
          )}
        </div>
        <ChevronDown
          className={`mt-1 h-4 w-4 shrink-0 text-[var(--muted-foreground)] transition-transform ${
            isExpanded ? "rotate-180" : ""
          }`}
        />
      </button>
      <div className="mt-0.5 flex shrink-0 items-center gap-1.5">
        {/* Offered only where it is the actual fix: an OAuth-backed server this
            account has not granted. Nothing else in the row can resolve that
            state — a retry cannot, and neither can editing the config. */}
        {cfg.auth === "oauth" && onAuthorize && (
          <button
            type="button"
            onClick={onAuthorize}
            disabled={saving}
            className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-[11.5px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${
              oauthAuthorized
                ? "border-[var(--border)] bg-[var(--card)] text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
                : "border-[var(--primary)]/40 bg-[var(--primary)]/10 text-[var(--primary)] hover:bg-[var(--primary)]/15"
            }`}
          >
            <ShieldCheck className="h-3 w-3" />
            {oauthAuthorized ? t("Reauthorize") : t("Connect")}
          </button>
        )}
        <Toggle
          checked={cfg.enabled}
          disabled={saving}
          onChange={onToggleEnabled}
          label={cfg.enabled ? t("Enabled") : t("Disabled")}
        />
        <IconButton
          label={t("Edit")}
          onClick={onEdit}
          disabled={saving}
          icon={<Pencil className="h-3.5 w-3.5" />}
        />
        <IconButton
          label={t("Delete")}
          onClick={onDelete}
          disabled={saving}
          icon={<Trash2 className="h-3.5 w-3.5" />}
          danger
        />
      </div>
    </div>
  );
}

// ── small controls ──────────────────────────────────────────────────────
function Toggle({
  checked,
  disabled,
  onChange,
  label,
}: {
  checked: boolean;
  disabled: boolean;
  onChange: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onChange}
      className={`relative inline-flex h-[18px] w-[32px] shrink-0 items-center rounded-full border transition-colors ${
        checked
          ? "border-[var(--primary)] bg-[var(--primary)]/70"
          : "border-[var(--border)] bg-[var(--muted)]/50"
      } ${disabled ? "cursor-not-allowed opacity-60" : "cursor-pointer"}`}
    >
      <span
        className={`inline-block h-[12px] w-[12px] transform rounded-full bg-white shadow transition-transform ${
          checked ? "translate-x-[16px]" : "translate-x-[2px]"
        }`}
      />
    </button>
  );
}

function IconButton({
  label,
  onClick,
  disabled,
  icon,
  danger,
}: {
  label: string;
  onClick: () => void;
  disabled: boolean;
  icon: ReactNode;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={label}
      className={`rounded-md p-1.5 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] ${
        danger ? "hover:text-red-500" : "hover:text-[var(--foreground)]"
      } disabled:cursor-not-allowed disabled:opacity-60`}
    >
      {icon}
    </button>
  );
}
