import { apiFetch, apiUrl } from "@/lib/api";

const ROOT = "/api/solution-sequence";

export interface SequenceStep {
  id: string;
  explanation: string;
  math: string;
}

export interface SequenceProblem {
  problem_id: string;
  question: string;
  formulas: string[];
  steps: SequenceStep[];
  placed_ids: string[];
  solved: boolean;
  explanation: string | null;
  progress: { solved: number; goal: number };
  sources: { title: string }[];
}

export interface PlaceResult {
  accepted: boolean;
  problem: SequenceProblem;
}

async function readDetail(response: Response, fallback: string): Promise<string> {
  try {
    const data = await response.json();
    if (typeof data?.detail === "string" && data.detail.trim()) return data.detail;
  } catch {
    /* The body was not JSON. */
  }
  return fallback;
}

async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await apiFetch(apiUrl(`${ROOT}${path}`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(await readDetail(response, "The solution sequence request failed."));
  }
  return response.json() as Promise<T>;
}

export function createSequenceProblem(knowledgeBase: string, topic: string) {
  return request<SequenceProblem>("/problems", { knowledge_base: knowledgeBase, topic });
}

export function placeSequenceStep(problemId: string, stepId: string, index: number) {
  return request<PlaceResult>(`/problems/${encodeURIComponent(problemId)}/place`, {
    step_id: stepId,
    index,
  });
}

export function removeSequenceStep(problemId: string, stepId: string) {
  return request<SequenceProblem>(`/problems/${encodeURIComponent(problemId)}/remove`, {
    step_id: stepId,
  });
}

export function requestSequenceHint(problemId: string) {
  return request<{ hint: string }>(`/problems/${encodeURIComponent(problemId)}/hint`);
}

export function explainSequenceStep(problemId: string, stepId: string) {
  return request<{ explanation: string }>(`/problems/${encodeURIComponent(problemId)}/explain`, {
    step_id: stepId,
  });
}
