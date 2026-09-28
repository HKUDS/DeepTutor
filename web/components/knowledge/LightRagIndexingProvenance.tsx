"use client";

import { useTranslation } from "react-i18next";
import type {
  IndexVersion,
  LightRagIndexingPolicy,
} from "@/lib/knowledge-helpers";

interface LightRagIndexingProvenanceProps {
  policy?: LightRagIndexingPolicy;
  version?: IndexVersion;
  embedding?: { model: string; dimension: number };
  title?: string;
  compact?: boolean;
}

export default function LightRagIndexingProvenance({
  policy,
  version,
  embedding,
  title,
  compact = false,
}: LightRagIndexingProvenanceProps) {
  const { t } = useTranslation();
  const resolved = policy ?? { policy: "legacy_unpinned" };
  const extract = resolved.schema_version === 2 ? resolved.extract : resolved;
  const visionEnabled =
    resolved.schema_version === 2
      ? resolved.vlm?.mode === "enabled"
        ? true
        : resolved.vlm?.mode === "disabled"
          ? false
          : undefined
      : resolved.vision_available;
  const vision =
    resolved.schema_version === 2 ? resolved.vlm?.snapshot : resolved;
  const modelLabel = (value?: LightRagIndexingPolicy) => {
    const name = [value?.descriptor?.binding, value?.descriptor?.model]
      .filter(Boolean)
      .join(" · ");
    return name
      ? `${name} · ${value?.descriptor?.reasoning_effort || t("Auto")}`
      : t("Unverified historical indexing model");
  };
  const embeddingModel = embedding?.model ?? version?.embedding_model;
  const dimension = embedding?.dimension ?? version?.embedding_dim;
  const rows = [
    ...(embeddingModel
      ? [
          [
            t("Embedding"),
            `${embeddingModel}${dimension ? ` · ${dimension}${t("d")}` : ""}`,
          ],
        ]
      : []),
    [t("EXTRACT model"), modelLabel(extract)],
    [
      t("VLM model"),
      visionEnabled === true
        ? modelLabel(vision)
        : visionEnabled === false
          ? t("Disabled")
          : t("Unknown"),
    ],
  ];

  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--muted)]/25 px-3 py-2.5">
      <div className="text-[12px] font-medium text-[var(--foreground)]">
        {title || t("Index configuration")}
      </div>
      {resolved.policy === "legacy_unpinned" && (
        <p className="mt-1 text-[11px] text-[var(--muted-foreground)]">
          {t(
            "The historical indexing model is unknown. Queries remain available, but incremental uploads require a full rebuild.",
          )}
        </p>
      )}
      <dl
        className={`mt-2 gap-1 text-[11px] ${compact ? "flex flex-wrap gap-x-4" : "grid"}`}
      >
        {rows.map(([label, value]) => (
          <div key={label} className="flex gap-2">
            <dt className="shrink-0 text-[var(--muted-foreground)]">{label}</dt>
            <dd className="break-words text-[var(--foreground)]">{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
