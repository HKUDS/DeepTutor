import { apiFetch, apiUrl } from "@/lib/api";

/** Languages a notebook code cell can run. Mirrors the backend cell runner. */
export type NotebookCellLanguage = "python" | "shell" | "c" | "cpp";

/** A file a cell produced (an image/plot, or any written output). */
export interface NotebookCellArtifact {
  filename: string;
  /** A `/files/outputs/...` URL, relative to the backend. */
  url: string;
  mime_type: string;
  size_bytes: number;
  relative_path: string;
}

export interface NotebookCellRun {
  stdout: string;
  stderr: string;
  exit_code: number;
  timed_out: boolean;
  /** Set when the sandbox itself failed, not the learner's code. */
  error: string;
  artifacts: NotebookCellArtifact[];
}

export interface RunNotebookCellInput {
  code: string;
  language?: NotebookCellLanguage;
  /** Keys the run to one notebook so its files/outputs stay together. */
  notebookId?: string;
  timeout?: number;
}

/** Run one notebook cell and return its streams plus any produced files. */
export async function runNotebookCell(
  input: RunNotebookCellInput,
): Promise<NotebookCellRun> {
  const response = await apiFetch(apiUrl("/api/notebooks/cells/run"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      code: input.code,
      language: input.language ?? "python",
      notebook_id: input.notebookId ?? "",
      timeout: input.timeout ?? 30,
    }),
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    const message =
      detail && typeof detail.detail === "string" ? detail.detail : "";
    throw new Error(message || `Run failed (${response.status})`);
  }
  return (await response.json()) as NotebookCellRun;
}
