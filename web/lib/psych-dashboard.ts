import { apiFetch, apiUrl } from "@/lib/api";

export type PsychEmotionEvent = {
  ts: string;
  session_id: string;
  surface: string;
  labels: string[];
  intensity: number;
  trigger: string;
  skill_id: string;
};

export type PsychActionPlan = {
  id: string;
  type: string;
  steps: { text: string; done: boolean }[];
  due: string;
  linked_skill?: string | null;
  linked_sim?: string | null;
  linked_counsel?: string | null;
  linked_room?: string | null;
};

export type PsychSessionRow = {
  id: string;
  closed: boolean;
  mtime?: number;
  safety?: string;
  turns?: number;
  turns_done?: number;
  scenario_id?: string;
  linked_counsel?: string | null;
};

export type PsychDashboardSummary = {
  emotions: PsychEmotionEvent[];
  open_plans: PsychActionPlan[];
  sessions: {
    counsel: PsychSessionRow[];
    sim: PsychSessionRow[];
    dual: PsychSessionRow[];
    whisper: PsychSessionRow[];
    intake: PsychSessionRow[];
  };
};

export type PsychSessionKind = keyof PsychDashboardSummary["sessions"];

const SESSION_ROUTES: Record<PsychSessionKind, string> = {
  counsel: "/counsel",
  sim: "/sim",
  dual: "/dual",
  whisper: "/whisper",
  intake: "/intake",
};

/** Workspace route for a stored psych session id (room pages require manual attach). */
export function psychSessionHref(kind: PsychSessionKind, id: string): string {
  const base = SESSION_ROUTES[kind];
  if (kind === "counsel") {
    return `${base}?session_hint=${encodeURIComponent(id)}`;
  }
  if (kind === "whisper" || kind === "intake") {
    return `${base}?room_hint=${encodeURIComponent(id)}`;
  }
  return base;
}

export function observeDebriefHref(counselSessionId: string): string {
  return `/observe?counsel_id=${encodeURIComponent(counselSessionId)}`;
}

export async function fetchPsychDashboard(
  limits?: { emotion_limit?: number; session_limit?: number },
): Promise<PsychDashboardSummary> {
  const response = await apiFetch(
    apiUrl("/api/v1/plugins/tools/psych_timeline_summary/execute"),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        params: {
          emotion_limit: limits?.emotion_limit ?? 10,
          session_limit: limits?.session_limit ?? 5,
        },
      }),
    },
  );
  if (!response.ok) {
    throw new Error(`psych_timeline_summary failed (${response.status})`);
  }
  const payload = (await response.json()) as {
    success?: boolean;
    metadata?: PsychDashboardSummary;
    content?: string;
  };
  if (!payload.success || !payload.metadata) {
    throw new Error(payload.content || "psych_timeline_summary returned no data");
  }
  return payload.metadata;
}
