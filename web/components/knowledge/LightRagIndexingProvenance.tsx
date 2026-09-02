"use client";

import { useTranslation } from "react-i18next";
import {
  formatKnowledgeTimestamp,
  type IndexVersion,
  type LightRagIndexingPolicy,
} from "@/lib/knowledge-helpers";

interface LightRagIndexingProvenanceProps {
  policy?: LightRagIndexingPolicy;
  version?: IndexVersion;
  compact?: boolean;
}

export default function LightRagIndexingProvenance({
  policy,
  version,
  compact = false,
}: LightRagIndexingProvenanceProps) {
  const { t } = useTranslation();
  const resolved = policy ?? { policy: "legacy_unpinned" };
  const pending = resolved.policy === "pending_pinned";
  const pinned = resolved.policy === "pinned" || pending;
  const model = resolved.descriptor?.model;
  const binding = resolved.descriptor?.binding;
  const modelLabel = [binding, model].filter(Boolean).join(" · ");
  const effort = resolved.descriptor?.reasoning_effort;
  const title = pending
    ? t("Pending pinned indexing model")
    : pinned
      ? t("Pinned indexing model")
      : t("Legacy unpinned indexing model");
  const summary = pending
    ? t(
        "Takes effect on the first index. No index version has been published yet.",
      )
    : pinned
      ? t("Incremental indexing continues with this pinned model.")
      : t(
          "The historical indexing model is unknown. Queries remain available, but incremental uploads require a full rebuild.",
        );

  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--muted)]/25 px-3 py-2.5">
      <div className="text-[12px] font-medium text-[var(--foreground)]">
        {title}
      </div>
      <p className="mt-0.5 text-[11px] text-[var(--muted-foreground)]">
        {summary}
      </p>
      {compact && (
        <p className="mt-1 text-[11px] font-medium text-[var(--foreground)]">
          {modelLabel || t("Unverified historical indexing model")}
          {` · ${t("Reasoning effort")}: ${effort || t("Model default")}`}
        </p>
      )}
      {!compact && (
        <dl className="mt-2 grid gap-x-4 gap-y-1 text-[11px] sm:grid-cols-2">
          <ProvenanceField label={t("Model")}>
            {modelLabel || t("Unverified historical indexing model")}
          </ProvenanceField>
          <ProvenanceField label={t("Reasoning effort")}>
            {effort || t("Model default")}
          </ProvenanceField>
          <ProvenanceField label={t("VLM capability")}>
            {typeof resolved.vision_available === "boolean"
              ? resolved.vision_available
                ? t("Available")
                : t("Unavailable")
              : t("Unknown")}
            {resolved.vlm_used === true
              ? ` · ${t("used for this version")}`
              : resolved.vlm_used === false
                ? ` · ${t("not used for this version")}`
                : ""}
          </ProvenanceField>
          <ProvenanceField label={t("Version source")}>
            {version?.version ||
              (pending ? t("Pending configuration") : t("Legacy metadata"))}
            {version?.created_at
              ? ` · ${formatKnowledgeTimestamp(version.created_at)}`
              : ""}
          </ProvenanceField>
        </dl>
      )}
    </div>
  );
}

function ProvenanceField({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <dt className="text-[var(--muted-foreground)]">{label}</dt>
      <dd className="break-words text-[var(--foreground)]">{children}</dd>
    </div>
  );
}
