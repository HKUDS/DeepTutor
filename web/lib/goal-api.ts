"use client";

import { apiUrl } from "@/lib/api";

export interface GoalConfigPayload {
  goal_level: "foundation" | "competent" | "advanced";
  remaining_days: number;
  daily_minutes: number;
  days_per_week: number;
  goal_statement?: string;
  preferences: {
    strategy: "depth_first" | "breadth_first" | "high_yield_first";
    include_practice: boolean;
    practice_ratio: number;
    review_ratio: number;
    language: string;
  };
}

type GoalApiErrorPayload = {
  ok?: boolean;
  error?: {
    code?: string;
    message?: string;
    detail?: unknown;
  };
};

async function parseGoalApiError(response: Response, fallback: string): Promise<Error> {
  try {
    const payload = (await response.json()) as GoalApiErrorPayload;
    const detail = payload?.error;
    if (detail?.code || detail?.message) {
      const prefix = detail.code ? `[${detail.code}] ` : "";
      return new Error(`${prefix}${detail.message || fallback}`);
    }
  } catch {
    // Ignore JSON parsing failures and use fallback message.
  }
  return new Error(fallback);
}

export async function createGoalSession(kbName: string, goalConfig: GoalConfigPayload) {
  const response = await fetch(apiUrl("/api/v1/goal/create_session"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kb_name: kbName, goal_config: goalConfig }),
  });
  if (!response.ok) {
    throw await parseGoalApiError(response, "Failed to create goal session");
  }
  return response.json();
}

export async function runGoalPlan(sessionId: string) {
  const response = await fetch(apiUrl(`/api/v1/goal/session/${sessionId}/run_plan`), {
    method: "POST",
  });
  if (!response.ok) {
    throw await parseGoalApiError(response, "Failed to run plan");
  }
  return response.json();
}

export async function getGoalPlan(sessionId: string) {
  const response = await fetch(apiUrl(`/api/v1/goal/session/${sessionId}/plan`));
  if (!response.ok) {
    throw await parseGoalApiError(response, "Failed to load plan");
  }
  return response.json();
}

export async function getGoalDayPlanDetail(sessionId: string, dayIndex: number) {
  const response = await fetch(apiUrl(`/api/v1/goal/session/${sessionId}/day/${dayIndex}`));
  if (!response.ok) {
    throw await parseGoalApiError(response, "Failed to load day plan detail");
  }
  return response.json();
}

export async function submitGoalFeedback(
  sessionId: string,
  payload: {
    feedback_id: string;
    task_id: string;
    completion: "done" | "partial" | "missed" | "skipped";
    actual_minutes?: number;
    quiz?: { score: number; total: number } | null;
    reflection?: string;
  },
) {
  const response = await fetch(apiUrl(`/api/v1/goal/session/${sessionId}/feedback`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw await parseGoalApiError(response, "Failed to submit feedback");
  }
  return response.json();
}

export async function replanGoalSession(sessionId: string, reason = "manual_feedback") {
  const response = await fetch(apiUrl(`/api/v1/goal/session/${sessionId}/replan`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason, strategy: "rule_based" }),
  });
  if (!response.ok) {
    throw await parseGoalApiError(response, "Failed to replan");
  }
  return response.json();
}

export async function generateGoalPractice(
  sessionId: string,
  taskId: string,
  payload: {
    count: number;
    difficulty: string;
    question_type: string;
  },
) {
  const response = await fetch(
    apiUrl(`/api/v1/goal/session/${sessionId}/task/${taskId}/generate_practice`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  if (!response.ok) {
    throw await parseGoalApiError(response, "Failed to generate practice");
  }
  return response.json();
}

export async function generateGoalDayInteractivePage(
  sessionId: string,
  dayIndex: number,
  payload: { force?: boolean } = {},
) {
  const response = await fetch(
    apiUrl(`/api/v1/goal/session/${sessionId}/day/${dayIndex}/interactive_page`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ force: Boolean(payload.force) }),
    },
  );
  if (!response.ok) {
    throw await parseGoalApiError(response, "Failed to generate interactive page");
  }
  return response.json();
}

export async function askGoalDayInteractiveAssistant(
  sessionId: string,
  dayIndex: number,
  payload: { question: string },
) {
  const response = await fetch(
    apiUrl(`/api/v1/goal/session/${sessionId}/day/${dayIndex}/interactive_chat`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  if (!response.ok) {
    throw await parseGoalApiError(response, "Failed to ask interactive assistant");
  }
  return response.json();
}

export async function analyzeGoalExamMaterials(
  sessionId: string,
  payload: {
    pastedText?: string;
    files?: File[];
  },
) {
  const form = new FormData();
  if (payload.pastedText) {
    form.append("pasted_text", payload.pastedText);
  }
  for (const file of payload.files || []) {
    form.append("files", file);
  }
  const response = await fetch(apiUrl(`/api/v1/goal/session/${sessionId}/exam_analysis`), {
    method: "POST",
    body: form,
  });
  if (!response.ok) {
    throw await parseGoalApiError(response, "Failed to analyze exam materials");
  }
  return response.json();
}
