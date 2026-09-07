"use client";

import { useTranslation } from "react-i18next";
import { kbProvider, type KnowledgeBase } from "@/lib/knowledge-helpers";

export default function LightRagEmbeddingWarning({
  kb,
}: {
  kb: KnowledgeBase;
}) {
  const { t } = useTranslation();
  if (kbProvider(kb) !== "lightrag" || !kb.metadata?.embedding_mismatch)
    return null;
  const meta = kb.metadata;
  return (
    <span className="mt-2 block rounded-lg border border-amber-200 bg-amber-50/80 px-3 py-2 text-[12px] text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/20 dark:text-amber-300">
      {t(
        "The current embedding configuration does not match this index. Restore the original configuration or rebuild with the current embedding before querying or adding documents.",
      )}
      <span className="mt-2 block">
        {t("Index embedding")}: {meta.indexed_embedding_model || t("Unknown")} ·{" "}
        {meta.indexed_embedding_dim ?? "?"}
        {t("d")}
      </span>
      <span className="block">
        {t("Current embedding")}: {meta.current_embedding_model || t("Unknown")}{" "}
        · {meta.current_embedding_dim ?? "?"}
        {t("d")}
      </span>
    </span>
  );
}
