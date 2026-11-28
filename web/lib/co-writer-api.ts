import { apiFetch, apiUrl } from "@/lib/api";
import type { NotePage } from "@/lib/notes-api";

import type { CoWriterDocument, CoWriterDocumentSummary } from "./co-writer-types";
export type { CoWriterDocument, CoWriterDocumentSummary } from "./co-writer-types";

const BASE = "/api";

async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(
      `Request failed (${res.status}): ${text || res.statusText}`,
    );
  }
  return res.json() as Promise<T>;
}

export async function listCoWriterDocuments(): Promise<
  CoWriterDocumentSummary[]
> {
  const res = await apiFetch(apiUrl(`${BASE}/documents`), {
    cache: "no-store",
  });
  const data = await jsonOrThrow<{ documents: CoWriterDocumentSummary[] }>(res);
  return Array.isArray(data?.documents) ? data.documents : [];
}

export async function createCoWriterDocument(payload?: {
  title?: string | null;
  content?: string;
}): Promise<CoWriterDocument> {
  const res = await apiFetch(apiUrl(`${BASE}/documents`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title: payload?.title ?? null,
      content: payload?.content ?? "",
    }),
  });
  return jsonOrThrow<CoWriterDocument>(res);
}

export async function getCoWriterDocument(
  docId: string,
): Promise<CoWriterDocument> {
  const res = await apiFetch(
    apiUrl(`${BASE}/documents/${encodeURIComponent(docId)}`),
    {
      cache: "no-store",
    },
  );
  return jsonOrThrow<CoWriterDocument>(res);
}

export async function updateCoWriterDocument(
  docId: string,
  payload: { title?: string | null; content?: string | null },
): Promise<CoWriterDocument> {
  const res = await apiFetch(
    apiUrl(`${BASE}/documents/${encodeURIComponent(docId)}`),
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: payload.title ?? null,
        content: payload.content ?? null,
      }),
    },
  );
  return jsonOrThrow<CoWriterDocument>(res);
}

export async function deleteCoWriterDocument(docId: string): Promise<boolean> {
  const res = await apiFetch(
    apiUrl(`${BASE}/documents/${encodeURIComponent(docId)}`),
    {
      method: "DELETE",
    },
  );
  const data = await jsonOrThrow<{ deleted: boolean }>(res);
  return Boolean(data?.deleted);
}

export async function importCoWriterDocx(
  file: File,
): Promise<NotePage> {
  const body = new FormData();
  body.append("file", file);
  const res = await apiFetch(apiUrl(`${BASE}/documents/import/docx`), {
    method: "POST",
    body,
  });
  return jsonOrThrow<NotePage>(res);
}

export async function exportCoWriterDocx(payload: {
  title: string;
  content: string;
}): Promise<Blob> {
  const res = await apiFetch(apiUrl(`${BASE}/documents/export/docx`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title: payload.title ?? "",
      content: payload.content ?? "",
    }),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(
      `Request failed (${res.status}): ${text || res.statusText}`,
    );
  }
  return res.blob();
}
