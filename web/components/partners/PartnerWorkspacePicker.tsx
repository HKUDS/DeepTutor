"use client";

import { useEffect, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { FolderOpen } from "lucide-react";
import { getPartnerWorkspaces } from "@/lib/partners-api";
import {
  listWorkspaces,
  workspaceLabel,
  type ChatWorkspaceRegistration,
} from "@/lib/workspaces-api";

export default function PartnerWorkspacePicker({
  value,
  onChange,
  disabled = false,
  partnerId,
}: {
  value: string;
  onChange: (id: string, label: string) => void;
  disabled?: boolean;
  partnerId?: string;
}) {
  const { t, i18n } = useTranslation();
  const id = useId();
  const [rows, setRows] = useState<ChatWorkspaceRegistration[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const zh = i18n.language.startsWith("zh");

  useEffect(() => {
    let active = true;
    void (partnerId ? getPartnerWorkspaces(partnerId) : listWorkspaces(true))
      .then((result) => {
        if (active) {
          setError("");
          setRows(
            result.filter(
              (row) =>
                row.kind !== "system" &&
                !row.archived &&
                row.status === "ready",
            ),
          );
        }
      })
      .catch((e) => {
        if (active)
          setError(
            e instanceof Error ? e.message : t("Failed to load workspaces"),
          );
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [attempt, partnerId, t]);

  return (
    <div className="space-y-2">
      <label
        htmlFor={id}
        className="inline-flex items-center gap-1.5 text-[13px] font-medium text-[var(--muted-foreground)]"
      >
        <FolderOpen className="h-4 w-4" />
        {t("Workspace")}
      </label>
      <select
        id={id}
        value={value}
        disabled={disabled || loading}
        onChange={(event) => {
          const row = rows.find(
            (row) => row.workspace_id === event.target.value,
          );
          onChange(
            event.target.value,
            row ? workspaceLabel(row, zh) : t("Partner private workspace"),
          );
        }}
        className="w-full rounded-xl border border-[var(--border)] bg-[var(--background)] px-3 py-2.5 text-[13px] text-[var(--foreground)] disabled:opacity-50"
      >
        <option value="">{t("Partner private workspace")}</option>
        {value && !rows.some((row) => row.workspace_id === value) && (
          <option value={value} disabled>
            {loading ? t("Loading…") : t("Assigned workspace unavailable")}
          </option>
        )}
        {rows.map((row) => (
          <option key={row.workspace_id} value={row.workspace_id}>
            {workspaceLabel(row, zh)}
          </option>
        ))}
      </select>
      <p className="text-[12px] leading-relaxed text-[var(--muted-foreground)]">
        {value
          ? t(
              "This partner shares the workspace's files, knowledge bases, skills, and notebooks. Changes stay in sync; generated files go to its outputs folder.",
            )
          : t(
              "Use a private workspace, or bind an existing workspace to share its latest resources.",
            )}
      </p>
      {error && (
        <p role="alert" className="text-[12px] text-[var(--destructive)]">
          {error}{" "}
          <button
            type="button"
            onClick={() => {
              setLoading(true);
              setError("");
              setAttempt(attempt + 1);
            }}
            className="underline"
          >
            {t("Retry")}
          </button>
        </p>
      )}
    </div>
  );
}
