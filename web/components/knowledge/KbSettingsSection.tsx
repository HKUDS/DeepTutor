"use client";

import { useTranslation } from "react-i18next";
import { Star, Trash2 } from "lucide-react";
import {
  formatKnowledgeTimestamp,
  type KnowledgeBase,
} from "@/lib/knowledge-helpers";

interface KbSettingsSectionProps {
  kb: KnowledgeBase;
  onSetDefault: () => Promise<void>;
  onDelete: () => Promise<void>;
}

export default function KbSettingsSection({
  kb,
  onSetDefault,
  onDelete,
}: KbSettingsSectionProps) {
  const { t } = useTranslation();
  const meta = kb.metadata || {};
  const provider = kb.statistics?.rag_provider || "llamaindex";
  const embeddingLabel = meta.embedding_model
    ? typeof meta.embedding_dim === "number"
      ? `${meta.embedding_model} · ${meta.embedding_dim}${t("d")}`
      : meta.embedding_model
    : t("Default embedding");
  const created = formatKnowledgeTimestamp(meta.created_at);
  const updated = formatKnowledgeTimestamp(meta.last_updated);
  const lastIndexed = formatKnowledgeTimestamp(meta.last_indexed_at);

  return (
    <div className="space-y-6">
      <section className="space-y-3">
        <div>
          <div className="text-[13px] font-medium text-[var(--foreground)]">
            {t("Overview")}
          </div>
          <p className="mt-0.5 text-[11.5px] text-[var(--muted-foreground)]">
            {t("Read-only metadata. Use the actions below to manage this KB.")}
          </p>
        </div>

        <dl className="grid gap-3 rounded-lg border border-[var(--border)] bg-[var(--background)] p-3 sm:grid-cols-2">
          <Field label={t("RAG provider")}>{provider}</Field>
          <Field label={t("Embedding")}>{embeddingLabel}</Field>
          <Field label={t("Created")}>{created || "—"}</Field>
          <Field label={t("Updated")}>{updated || "—"}</Field>
          <Field label={t("Last indexed")}>{lastIndexed || "—"}</Field>
          {kb.path && (
            <Field label={t("On-disk path")} className="sm:col-span-2">
              <span className="font-mono text-[10.5px] text-[var(--muted-foreground)]">
                {kb.path}
              </span>
            </Field>
          )}
        </dl>
      </section>

      <section className="space-y-3 rounded-lg border border-[var(--border)] bg-[var(--background)] p-3">
        <div>
          <div className="text-[12.5px] font-medium text-[var(--foreground)]">
            {t("Default knowledge base")}
          </div>
          <p className="mt-0.5 text-[11.5px] text-[var(--muted-foreground)]">
            {t("The default KB is selected automatically in chat & partners.")}
          </p>
        </div>
        {kb.is_default ? (
          <span className="inline-flex items-center gap-1.5 rounded-md bg-amber-100 px-2.5 py-1 text-[12px] font-medium text-amber-700 dark:bg-amber-950/30 dark:text-amber-300">
            <Star className="h-3 w-3" fill="currentColor" />
            {t("Currently default")}
          </span>
        ) : (
          <button
            type="button"
            onClick={() => void onSetDefault()}
            className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--background)] px-2.5 py-1 text-[12px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)]"
          >
            <Star className="h-3 w-3" />
            {t("Set as default")}
          </button>
        )}
      </section>

      <section className="space-y-3 rounded-lg border border-red-200 bg-red-50/40 p-3 dark:border-red-900/60 dark:bg-red-950/15">
        <div>
          <div className="text-[12.5px] font-medium text-red-700 dark:text-red-300">
            {t("Danger zone")}
          </div>
          <p className="mt-0.5 text-[11.5px] text-red-700/80 dark:text-red-300/80">
            {t(
              "Deleting a knowledge base permanently removes its raw documents and index versions.",
            )}
          </p>
        </div>
        <button
          type="button"
          onClick={() => void onDelete()}
          className="inline-flex items-center gap-1.5 rounded-md border border-red-300 bg-red-50 px-2.5 py-1 text-[12px] font-medium text-red-700 transition-colors hover:bg-red-100 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300 dark:hover:bg-red-950/50"
        >
          <Trash2 className="h-3 w-3" />
          {t("Delete knowledge base")}
        </button>
      </section>
    </div>
  );
}

function Field({
  label,
  children,
  className = "",
}: {
  label: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={className}>
      <dt className="text-[10.5px] uppercase tracking-[0.14em] text-[var(--muted-foreground)]">
        {label}
      </dt>
      <dd className="mt-1 text-[12.5px] text-[var(--foreground)]">
        {children}
      </dd>
    </div>
  );
}
