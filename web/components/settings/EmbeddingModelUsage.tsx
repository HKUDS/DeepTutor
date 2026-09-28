"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { getEmbeddingUsage } from "@/features/knowledge/api/engines";
import type { EmbeddingUsage } from "@/features/knowledge/model/types";

export default function EmbeddingModelUsage({
  profileId,
  modelId,
}: {
  profileId: string;
  modelId: string;
}) {
  const { t } = useTranslation();
  const [usage, setUsage] = useState<EmbeddingUsage[] | null>(null);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const requestKey = JSON.stringify([profileId, modelId, attempt]);
  const [resolvedKey, setResolvedKey] = useState(requestKey);
  if (resolvedKey !== requestKey) {
    setResolvedKey(requestKey);
    setUsage(null);
    setError(false);
  }
  useEffect(() => {
    let cancelled = false;
    void getEmbeddingUsage()
      .then((rows) => {
        if (!cancelled)
          setUsage(
            rows.filter(
              (row) => row.profile_id === profileId && row.model_id === modelId,
            ),
          );
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [profileId, modelId, attempt]);
  return (
    <section
      className="space-y-2 rounded-lg border border-[var(--border)] p-3 text-xs"
      aria-label={t("Knowledge bases using this model")}
    >
      <h3 className="font-medium">
        {t("Knowledge bases using this model")}
        {usage && ` (${usage.length})`}
      </h3>
      {error ? (
        <div className="space-y-2">
          <p role="alert">{t("Failed to load embedding model usage")}</p>
          <p className="text-[var(--muted-foreground)]">{t("This list shows knowledge base references, not the model connection status.")}</p>
          <button type="button" onClick={() => setAttempt(value => value + 1)} className="rounded-md border border-[var(--border)] px-3 py-1.5 hover:bg-[var(--accent)]">{t("Retry")}</button>
        </div>
      ) : !usage ? (
        <p>{t("Loading...")}</p>
      ) : usage.length === 0 ? (
        <p className="text-[var(--muted-foreground)]">
          {t("No knowledge bases use this model.")}
        </p>
      ) : (
        <>
          <ul className="space-y-1">
            {usage.map((row, index) => (
              <li key={`${row.workspace_name}:${row.name}:${index}`}>
                {row.name}
                {row.workspace_name && ` · ${row.workspace_name}`}
              </li>
            ))}
          </ul>
          <p className="text-amber-700 dark:text-amber-300">
            {t(
              "Deleting this model is allowed. These knowledge bases will need another embedding model before they can be used again. Their documents and indexes will be preserved.",
            )}
          </p>
        </>
      )}
    </section>
  );
}
