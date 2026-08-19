export type SimRecommendation = {
  kind: string;
  targetId: string;
  reason: string;
};

export function parseSimRecommendation(
  metadata?: Record<string, unknown> | null,
): SimRecommendation | null {
  const kind = typeof metadata?.kind === "string" ? metadata.kind.trim() : "";
  const targetId =
    typeof metadata?.target_id === "string" ? metadata.target_id.trim() : "";
  const reason =
    typeof metadata?.reason === "string" ? metadata.reason.trim() : "";
  if (!kind || !targetId) return null;
  return { kind, targetId, reason };
}
