import { apiFetch, apiUrl } from "@/lib/api";

const ROOT = "/api/solution-sequence";
const NOT_READ = "This knowledge base has not been read yet.";

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

export interface SequenceModule {
  id: string;
  category: string;
  name: string;
  topic: string;
  solved: number;
  goal: number;
}

export interface SequenceOutline {
  knowledge_base: string;
  source: "files" | "retrieval";
  modules: SequenceModule[];
}

export interface SequenceCheckResult {
  solved: boolean;
  marks: Array<"correct" | "incorrect">;
  problem: SequenceProblem;
}

export interface PlaceResult {
  accepted: boolean;
  problem: SequenceProblem;
}

export class SequenceRequestError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "SequenceRequestError";
    this.status = status;
  }
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

async function request<T>(path: string, body?: unknown, method: "GET" | "POST" = "POST"): Promise<T> {
  const response = await apiFetch(apiUrl(`${ROOT}${path}`), {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: method === "GET" ? "no-store" : undefined,
  });
  if (!response.ok) {
    throw new SequenceRequestError(
      response.status,
      await readDetail(response, "The request failed."),
    );
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

/** Null means this knowledge base has not been read yet. */
export async function getSequenceOutline(knowledgeBase: string): Promise<SequenceOutline | null> {
  const query = new URLSearchParams({ knowledge_base: knowledgeBase });
  try {
    return await request<SequenceOutline>(`/outlines?${query.toString()}`, undefined, "GET");
  } catch (error) {
    if (
      error instanceof SequenceRequestError &&
      error.status === 404 &&
      error.message.trim() === NOT_READ
    ) {
      return null;
    }
    throw error;
  }
}

export function rebuildSequenceOutline(knowledgeBase: string) {
  return request<SequenceOutline>("/outlines", { knowledge_base: knowledgeBase });
}

export function checkSequenceAnswer(problemId: string, stepIds: readonly string[]) {
  return request<SequenceCheckResult>(`/problems/${encodeURIComponent(problemId)}/check`, {
    step_ids: [...stepIds],
  });
}

export function requestSequenceHint(problemId: string, stepIds?: readonly string[]) {
  return request<{ hint: string }>(
    `/problems/${encodeURIComponent(problemId)}/hint`,
    stepIds === undefined ? undefined : { step_ids: [...stepIds] },
  );
}

export function explainSequenceStep(problemId: string, stepId: string) {
  return request<{ explanation: string }>(`/problems/${encodeURIComponent(problemId)}/explain`, {
    step_id: stepId,
  });
}
