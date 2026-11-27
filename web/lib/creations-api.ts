/** Typed client for the /api/creations backend (create-mode drafts). */

import { apiFetch, apiUrl } from "@/lib/api";
import type { CreationDraftData } from "@/lib/creation-draft";

/** What approving this draft would do, per the backend's name-collision check. */
export type CreationApproval = "create" | "update" | "conflict" | "done";

export interface CreationDraftResponse {
  draft: CreationDraftData;
  approval: CreationApproval;
}

export interface CreationDraftEdits {
  name?: string;
  description?: string;
  content?: string;
  tags?: string[];
}

export interface CreationApproveResult {
  draft: CreationDraftData;
  saved_name: string;
  replaced: boolean;
  already_created: boolean;
  href: string;
}

/** Carries the HTTP status so callers can special-case a 409 name conflict. */
export class CreationApiError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "CreationApiError";
    this.status = status;
  }
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as {
      detail?: string | { message?: string };
    };
    const detail = body.detail;
    const message =
      typeof detail === "string"
        ? detail
        : (detail?.message ?? `Request failed: ${res.status}`);
    throw new CreationApiError(message, res.status);
  }
  return (await res.json()) as T;
}

export async function getCreationDraft(
  draftId: string,
): Promise<CreationDraftResponse> {
  return json(
    await apiFetch(
      apiUrl(`/api/creations/drafts/${encodeURIComponent(draftId)}`),
      { cache: "no-store" },
    ),
  );
}

export async function approveCreationDraft(
  draftId: string,
  edits: CreationDraftEdits,
): Promise<CreationApproveResult> {
  return json(
    await apiFetch(
      apiUrl(`/api/creations/drafts/${encodeURIComponent(draftId)}/approve`),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(edits),
      },
    ),
  );
}
