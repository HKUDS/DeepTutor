import { apiFetch, apiUrl } from "@/lib/api";
import { invalidateClientCache, withClientCache } from "@/lib/client-cache";

const KNOWLEDGE_CACHE_PREFIX = "knowledge:";

export interface KnowledgeBaseSummary {
  id?: string;
  name: string;
  is_default?: boolean;
  status?: string;
  path?: string;
  metadata?: Record<string, unknown>;
  progress?: Record<string, unknown>;
  statistics?: Record<string, unknown>;
  source?: "admin" | "user";
  assigned?: boolean;
  read_only?: boolean;
  provenance_label?: string;
  available?: boolean;
}

export interface RagProviderSummary {
  id: string;
  name: string;
  description: string;
}

export interface KnowledgeUploadPolicy {
  extensions: string[];
  accept: string;
  max_file_size_bytes: number;
  max_pdf_size_bytes: number;
}

export interface KnowledgeBaseFile {
  name: string;
  size: number;
  modified: number;
  mime_type?: string | null;
}

export async function listKnowledgeBases(options?: { force?: boolean }) {
  return withClientCache<KnowledgeBaseSummary[]>(
    `${KNOWLEDGE_CACHE_PREFIX}list`,
    async () => {
      const response = await apiFetch(apiUrl("/api/v1/knowledge/list"), {
        cache: "no-store",
      });
      const data = await response.json();
      return Array.isArray(data)
        ? data
        : Array.isArray(data?.knowledge_bases)
          ? data.knowledge_bases
          : [];
    },
    {
      force: options?.force,
    },
  );
}

export async function listRagProviders(options?: { force?: boolean }) {
  return withClientCache<RagProviderSummary[]>(
    `${KNOWLEDGE_CACHE_PREFIX}providers`,
    async () => {
      const response = await apiFetch(
        apiUrl("/api/v1/knowledge/rag-providers"),
        {
          cache: "no-store",
        },
      );
      const data = await response.json();
      return Array.isArray(data?.providers) ? data.providers : [];
    },
    {
      force: options?.force,
    },
  );
}

export async function getKnowledgeUploadPolicy(options?: { force?: boolean }) {
  return withClientCache<KnowledgeUploadPolicy>(
    `${KNOWLEDGE_CACHE_PREFIX}upload-policy`,
    async () => {
      const response = await apiFetch(
        apiUrl("/api/v1/knowledge/supported-file-types"),
        {
          cache: "no-store",
        },
      );
      const data = await response.json();
      return {
        extensions: Array.isArray(data?.extensions) ? data.extensions : [],
        accept: typeof data?.accept === "string" ? data.accept : "",
        max_file_size_bytes:
          typeof data?.max_file_size_bytes === "number"
            ? data.max_file_size_bytes
            : 100 * 1024 * 1024,
        max_pdf_size_bytes:
          typeof data?.max_pdf_size_bytes === "number"
            ? data.max_pdf_size_bytes
            : 50 * 1024 * 1024,
      };
    },
    {
      force: options?.force,
    },
  );
}

export function invalidateKnowledgeCaches() {
  invalidateClientCache(KNOWLEDGE_CACHE_PREFIX);
}

function withDockerUpgradeHint(
  detail: string,
  status: number,
  action: string,
): string {
  if (status === 404 && detail.trim().toLowerCase() === "not found") {
    return `${action} endpoint not found (404). The web UI may be newer than the backend API. If using Docker, pull and recreate the container, then retry.`;
  }
  return detail;
}

export async function listKnowledgeBaseFiles(
  name: string,
  options?: { force?: boolean },
): Promise<KnowledgeBaseFile[]> {
  return withClientCache<KnowledgeBaseFile[]>(
    `${KNOWLEDGE_CACHE_PREFIX}files:${name}`,
    async () => {
      const response = await apiFetch(
        apiUrl(`/api/v1/knowledge/${encodeURIComponent(name)}/files`),
        { cache: "no-store" },
      );
      if (!response.ok) {
        const detail = await readErrorDetail(
          response,
          `Failed to list files (${response.status})`,
        );
        throw new Error(
          withDockerUpgradeHint(
            detail,
            response.status,
            "Knowledge file listing",
          ),
        );
      }
      const data = await response.json();
      return Array.isArray(data?.files) ? data.files : [];
    },
    { force: options?.force, ttlMs: 15_000 },
  );
}

/** Build the `/api/v1/...` path for a raw KB file (caller can pass to apiUrl()). */
export function knowledgeBaseFilePath(
  kbName: string,
  filename: string,
): string {
  return `/api/v1/knowledge/${encodeURIComponent(kbName)}/files/${filename
    .split("/")
    .map(encodeURIComponent)
    .join("/")}`;
}

export interface KnowledgeTaskResponse {
  task_id?: string;
  message?: string;
  noop?: boolean;
}

async function readErrorDetail(
  res: Response,
  fallback: string,
): Promise<string> {
  try {
    const body = await res.json();
    if (body?.detail) return String(body.detail);
  } catch {
    // body wasn't JSON; fall through
  }
  return fallback;
}

export async function createKnowledgeBase(payload: {
  name: string;
  provider: string;
  files: File[];
}): Promise<KnowledgeTaskResponse> {
  const form = new FormData();
  form.append("name", payload.name);
  form.append("rag_provider", payload.provider);
  payload.files.forEach((file) => form.append("files", file));

  const res = await apiFetch(apiUrl("/api/v1/knowledge/create"), {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    throw new Error(
      await readErrorDetail(res, "Failed to create knowledge base"),
    );
  }
  invalidateKnowledgeCaches();
  return (await res.json()) as KnowledgeTaskResponse;
}

export async function uploadKnowledgeBaseFiles(
  name: string,
  files: File[],
  options?: { provider?: string },
): Promise<KnowledgeTaskResponse> {
  const form = new FormData();
  files.forEach((file) => form.append("files", file));
  if (options?.provider) form.append("rag_provider", options.provider);

  const res = await apiFetch(
    apiUrl(`/api/v1/knowledge/${encodeURIComponent(name)}/upload`),
    { method: "POST", body: form },
  );
  if (!res.ok) {
    throw new Error(await readErrorDetail(res, "Failed to upload files"));
  }
  invalidateKnowledgeCaches();
  return (await res.json()) as KnowledgeTaskResponse;
}

export async function setDefaultKnowledgeBase(name: string): Promise<void> {
  const res = await apiFetch(
    apiUrl(`/api/v1/knowledge/default/${encodeURIComponent(name)}`),
    { method: "PUT" },
  );
  if (!res.ok) {
    throw new Error(await readErrorDetail(res, "Failed to set default"));
  }
  invalidateKnowledgeCaches();
}

export async function reindexKnowledgeBase(
  name: string,
): Promise<KnowledgeTaskResponse> {
  const res = await apiFetch(
    apiUrl(`/api/v1/knowledge/${encodeURIComponent(name)}/reindex`),
    { method: "POST" },
  );
  if (!res.ok) {
    const detail = await readErrorDetail(
      res,
      `Re-index failed (${res.status})`,
    );
    throw new Error(
      withDockerUpgradeHint(detail, res.status, "Knowledge re-index"),
    );
  }
  invalidateKnowledgeCaches();
  return (await res.json()) as KnowledgeTaskResponse;
}

export async function deleteKnowledgeBase(name: string): Promise<void> {
  const res = await apiFetch(
    apiUrl(`/api/v1/knowledge/${encodeURIComponent(name)}`),
    { method: "DELETE" },
  );
  if (!res.ok) {
    throw new Error(
      await readErrorDetail(res, `Delete failed (${res.status})`),
    );
  }
  invalidateKnowledgeCaches();
}
