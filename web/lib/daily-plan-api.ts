import { apiFetch, apiUrl } from "@/lib/api";

/**
 * The learner daily-plan contract (``GET /api/daily-plan``).
 *
 * Both sides spell the fields out — the card renders exactly these, and the
 * router returns exactly these, so a contract drift is a type error rather
 * than a silently blank card.
 */

/** Where "continue learning" points, and which surface reopens it. */
export type ContinueKind = "space" | "book" | "reading";

export interface ContinueLearning {
  kind: ContinueKind;
  title: string;
  ref: string;
}

export interface KpRecommendation {
  kp_id: string;
  title: string;
  /** 0..1, recency-weighted; lower means weaker. */
  mastery_level: number;
  suggestion: string;
}

export interface DailyPlan {
  continue_learning: ContinueLearning | null;
  recommendations: KpRecommendation[];
}

async function asJson(response: Response) {
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return response.json();
}

/** The learner's "today" plan, or a fully empty one when the call fails. */
export async function getDailyPlan(): Promise<DailyPlan> {
  const response = await apiFetch(apiUrl("/api/daily-plan"));
  const data = (await asJson(response)) as {
    continue_learning?: {
      kind?: unknown;
      title?: unknown;
      ref?: unknown;
    } | null;
    recommendations?: unknown;
  };

  const entry = data.continue_learning;
  const continueLearning =
    entry && typeof entry.ref === "string" && entry.ref
      ? {
          kind: (entry.kind === "book" || entry.kind === "reading"
            ? entry.kind
            : "space") as ContinueKind,
          title: typeof entry.title === "string" ? entry.title : "",
          ref: entry.ref,
        }
      : null;

  const recommendations = Array.isArray(data.recommendations)
    ? data.recommendations
        .filter(
          (item): item is Record<string, unknown> =>
            !!item && typeof item === "object" && !!item.kp_id,
        )
        .slice(0, 3)
        .map((item) => ({
          kp_id: String(item.kp_id),
          title: String(item.title ?? ""),
          mastery_level: Number(item.mastery_level ?? 0),
          suggestion: String(item.suggestion ?? ""),
        }))
    : [];

  return { continue_learning: continueLearning, recommendations };
}
