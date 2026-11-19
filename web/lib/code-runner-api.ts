import { apiFetch, apiUrl } from "@/shared/api/client";

export type CodeLanguage = "python" | "c" | "cpp";

export interface CodeTestCase {
  name: string;
  stdin: string;
  expected_stdout: string;
}

export interface CodeSpec {
  language: CodeLanguage;
  starter_code: string;
  stdin: string;
  tests: CodeTestCase[];
}

export interface CodeTestResult {
  name: string;
  passed: boolean;
  stdout: string;
  stderr: string;
  exit_code: number;
  timed_out: boolean;
  expected_stdout: string;
  duration_ms: number;
}

export interface CodeRunRequest {
  language: CodeLanguage;
  code: string;
  stdin?: string;
  timeout?: number;
  tests?: CodeTestCase[];
}

export interface CodeRunResponse {
  stdout: string;
  stderr: string;
  exit_code: number;
  timed_out: boolean;
  error: string;
  tests: CodeTestResult[];
  passed: number;
  total: number;
  duration_ms: number;
}

export interface CodeCapabilities {
  available: boolean;
  isolation: string;
  languages: CodeLanguage[];
  max_timeout: number;
  max_tests: number;
}

async function failure(response: Response): Promise<string> {
  const body = (await response.json().catch(() => null)) as
    | { detail?: unknown; message?: unknown }
    | null;
  const detail = body?.detail ?? body?.message;
  if (typeof detail === "string" && detail.trim()) return detail;
  return response.statusText || `Request failed (${response.status})`;
}

export async function fetchCodeCapabilities(): Promise<CodeCapabilities> {
  const response = await apiFetch(apiUrl("/api/code/capabilities"));
  if (!response.ok) throw new Error(await failure(response));
  return (await response.json()) as CodeCapabilities;
}

export async function runCode(payload: CodeRunRequest): Promise<CodeRunResponse> {
  const response = await apiFetch(apiUrl("/api/code/run"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(await failure(response));
  return (await response.json()) as CodeRunResponse;
}
