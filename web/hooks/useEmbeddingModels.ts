"use client";

import { useEffect, useState } from "react";
import { getEngineModelOptions } from "@/features/knowledge/api/engines";
import type {
  EmbeddingModelSelection,
  ModelOption,
} from "@/features/knowledge/model/types";

export function useEmbeddingModels(
  preferred?: EmbeddingModelSelection,
  enabled = true,
) {
  const [options, setOptions] = useState<ModelOption[]>([]);
  const [selection, setSelection] = useState<EmbeddingModelSelection | null>(
    preferred || null,
  );
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState<string | null>(null);
  const profileId = preferred?.profile_id;
  const modelId = preferred?.model_id;
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    void Promise.resolve()
      .then(() => {
        if (cancelled) return;
        setLoading(true);
        setError(null);
        return getEngineModelOptions(["embedding"]);
      })
      .then((data) => {
        if (cancelled || !data) return;
        const choices = data.embedding?.options || [];
        setOptions(choices);
        const target =
          profileId && modelId
            ? { profile_id: profileId, model_id: modelId }
            : data.embedding?.active;
        const match = choices.find(
          (option) =>
            option.profile_id === target?.profile_id &&
            option.model_id === target?.model_id,
        );
        const selected = match || (!profileId ? choices[0] : null);
        setSelection(
          selected
            ? { profile_id: selected.profile_id, model_id: selected.model_id }
            : null,
        );
      })
      .catch((err) => {
        if (!cancelled)
          setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [enabled, profileId, modelId]);
  return { options, selection, setSelection, loading, error };
}
