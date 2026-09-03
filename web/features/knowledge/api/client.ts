import { apiFetch, apiUrl } from "@/lib/api";
import { invalidateClientCache, withClientCache } from "@/lib/client-cache";
import type { ImaKnowledgeBaseOption } from "@/lib/ima-connection";

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
  /** Whether the engine is ready to use (e.g. its API key is set). */
  configured?: boolean;
  /** Actionable reason when configured is false. */
  readiness_reason?: string;
  /** Whether the engine needs an API key configured before use. */
  requires_api_key?: boolean;
  /** Retrieval modes this engine supports (empty for mode-less engines). */
  modes?: string[];
  /** The active default retrieval mode for this engine. */
  default_mode?: string;
  /** Whether an existing index for this engine can be linked in place. */
  linkable?: boolean;
  /** The engine works, but reusable defaults have not been configured yet. */
  setup_required?: boolean;
}

export interface PageIndexConfig {
  api_key_set: boolean;
  configured: boolean;
}

/** Account-level Tencent IMA credentials, shared by every `ima` KB. */
export interface ImaAccountConfig {
  client_id: string;
  api_key_set: boolean;
  configured: boolean;
}

export interface LlamaIndexConfig {
  version: number;
  /** "hybrid" (BM25 + vector fusion) or "vector" only. */
  retrieval_profile: "hybrid" | "vector";
  /** Default number of chunks a query returns. */
  top_k: number;
  vector_top_k_multiplier: number;
  bm25_top_k_multiplier: number;
  /** Optional Hugging Face cross-encoder model; empty disables reranking. */
  reranker_model: string;
  /** First-stage candidates scored by the optional cross-encoder. */
  rerank_top_k: number;
  /** Vector index type used by the next full index build. */
  vector_index_type: "flat" | "hnsw";
  hnsw_m: number;
  hnsw_ef_construction: number;
  hnsw_ef_search: number;
  /** Chunk geometry — applies to documents indexed after the change. */
  chunk_size: number;
  chunk_overlap: number;
  /** Bounded multimodal LLM work during image-heavy indexing. */
  image_description_concurrency: number;
  image_description_timeout_seconds: number;
}

export interface GraphRagConfig {
  version: number;
  response_type: string;
  community_level: number;
  dynamic_community_selection: boolean;
}

export interface LightRagConfig {
  version: number;
  top_k: number;
  response_type: string;
  /** Frozen documents LightRAG parses in parallel while indexing. */
  max_concurrent_files: number;
  /** Concurrent LLM calls LightRAG's internal queue issues. */
  llm_model_max_async: number;
  /** Extra extraction passes per chunk, to recover missed entities. */
  entity_extract_max_gleaning: number;
  /** Stable catalog reference, or empty strings for the global active chat model. */
  llm_profile_id: string;
  llm_model_id: string;
}

export interface LightRagServerConfig {
  server_url: string;
  api_key_set: boolean;
  configured: boolean;
}

export interface PreflightCheck {
  key: string;
  label: string;
  ok: boolean;
  detail: string;
  /** Optional checks don't gate overall readiness (e.g. BM25, vision). */
  optional: boolean;
}

export interface EnginePreflight {
  ok: boolean;
  checks: PreflightCheck[];
}

export interface ModelOption {
  profile_id: string;
  profile_name: string;
  model_id: string;
  label: string;
  model: string;
  detail: string;
}

export interface ModelKindOptions {
  active: { profile_id: string | null; model_id: string | null };
  options: ModelOption[];
}

export interface GraphRagModelCompatibility {
  status: "compatible" | "incompatible" | "unverifiable";
  compatible: boolean | null;
  code: string;
  message: string;
  model: string;
  binding: string;
  retryable: boolean;
}

/** Map of service kind ("llm" | "embedding") → its options + active selection. */
export type ModelOptionsByKind = Record<string, ModelKindOptions>;

export interface KnowledgeUploadPolicy {
  extensions: string[];
  accept: string;
  max_file_size_bytes: number;
  allow_any_extension?: boolean;
}

export interface KnowledgeBaseFile {
  /** POSIX path relative to the KB's raw/ root (may include folders). */
  name: string;
  /** "folder" entries are organizational only; default "file". */
  type?: "file" | "folder";
  size?: number;
  modified?: number;
  mime_type?: string | null;
}

const IMAGE_UPLOAD_EXTENSIONS = [
  ".bmp",
  ".gif",
  ".jpeg",
  ".jpg",
  ".png",
  ".tif",
  ".tiff",
  ".webp",
];

const IMAGE_UPLOAD_MIME_TYPES = [
  "image/bmp",
  "image/gif",
  "image/jpeg",
  "image/png",
  "image/tiff",
  "image/webp",
];

function normalizeUploadPolicy(data: unknown): KnowledgeUploadPolicy {
  const payload = data as Partial<KnowledgeUploadPolicy> | null | undefined;
  const allowAnyExtension = payload?.allow_any_extension === true;
  const extensions = Array.from(
    new Set([
      ...(allowAnyExtension
        ? []
        : Array.isArray(payload?.extensions)
          ? payload.extensions
          : []),
      ...(allowAnyExtension ? [] : IMAGE_UPLOAD_EXTENSIONS),
    ]),
  ).sort();
  const serverAccept =
    typeof payload?.accept === "string"
      ? payload.accept
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean)
      : [];
  const accept = allowAnyExtension
    ? ""
    : Array.from(
        new Set([...serverAccept, ...extensions, ...IMAGE_UPLOAD_MIME_TYPES]),
      ).join(",");

  return {
    extensions,
    accept,
    allow_any_extension: allowAnyExtension,
    max_file_size_bytes:
      typeof payload?.max_file_size_bytes === "number"
        ? payload.max_file_size_bytes
        : 200 * 1024 * 1024,
  };
}

export async function listKnowledgeBases(options?: { force?: boolean }) {
  return withClientCache<KnowledgeBaseSummary[]>(
    `${KNOWLEDGE_CACHE_PREFIX}list`,
    async () => {
      const response = await apiFetch(apiUrl("/api/knowledge-bases"), {
        cache: "no-store",
      });
      if (!response.ok) {
        throw new Error(
          await readErrorDetail(response, "Failed to list knowledge bases"),
        );
      }
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
        apiUrl("/api/knowledge-bases/rag-providers"),
        {
          cache: "no-store",
        },
      );
      if (!response.ok) {
        throw new Error(
          await readErrorDetail(response, "Failed to list RAG providers"),
        );
      }
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
        apiUrl("/api/knowledge-bases/supported-file-types"),
        {
          cache: "no-store",
        },
      );
      if (!response.ok) {
        throw new Error(
          await readErrorDetail(response, "Failed to load upload policy"),
        );
      }
      const data = await response.json();
      return normalizeUploadPolicy(data);
    },
    {
      force: options?.force,
    },
  );
}

export function invalidateKnowledgeCaches() {
  invalidateClientCache(KNOWLEDGE_CACHE_PREFIX);
}

const PAGEINDEX_CONFIG_PATH =
  "/api/knowledge-bases/rag-pipelines/pageindex/config";

export async function getPageIndexConfig(options?: {
  force?: boolean;
}): Promise<PageIndexConfig> {
  return withClientCache<PageIndexConfig>(
    `${KNOWLEDGE_CACHE_PREFIX}pageindex-config`,
    async () => {
      const response = await apiFetch(apiUrl(PAGEINDEX_CONFIG_PATH), {
        cache: "no-store",
      });
      if (!response.ok) {
        throw new Error(
          await readErrorDetail(response, "Failed to read PageIndex config"),
        );
      }
      return (await response.json()) as PageIndexConfig;
    },
    { force: options?.force, ttlMs: 15_000 },
  );
}

export async function updatePageIndexConfig(payload: {
  /** Omit to keep the stored key, "" to clear it, any value to replace it. */
  api_key?: string;
}): Promise<PageIndexConfig> {
  const res = await apiFetch(apiUrl(PAGEINDEX_CONFIG_PATH), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error(
      await readErrorDetail(res, "Failed to update PageIndex config"),
    );
  }
  // The provider list's `configured` flag depends on this; refresh it.
  invalidateKnowledgeCaches();
  return (await res.json()) as PageIndexConfig;
}

const IMA_CONFIG_PATH = "/api/knowledge-bases/rag-pipelines/ima/config";

export async function getImaConfig(options?: {
  force?: boolean;
}): Promise<ImaAccountConfig> {
  return withClientCache<ImaAccountConfig>(
    `${KNOWLEDGE_CACHE_PREFIX}ima-config`,
    async () => {
      const response = await apiFetch(apiUrl(IMA_CONFIG_PATH), {
        cache: "no-store",
      });
      if (!response.ok) {
        throw new Error(
          await readErrorDetail(response, "Failed to read Tencent IMA config"),
        );
      }
      return (await response.json()) as ImaAccountConfig;
    },
    { force: options?.force, ttlMs: 15_000 },
  );
}

export async function updateImaConfig(payload: {
  client_id?: string;
  /** Omit to keep the stored key, "" to clear it, any value to replace it. */
  api_key?: string;
}): Promise<ImaAccountConfig> {
  const res = await apiFetch(apiUrl(IMA_CONFIG_PATH), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error(
      await readErrorDetail(res, "Failed to update Tencent IMA config"),
    );
  }
  // The provider list's `configured` flag depends on this; refresh it.
  invalidateKnowledgeCaches();
  return (await res.json()) as ImaAccountConfig;
}

const LLAMAINDEX_CONFIG_PATH =
  "/api/knowledge-bases/rag-pipelines/llamaindex/config";

export async function getLlamaIndexConfig(options?: {
  force?: boolean;
}): Promise<LlamaIndexConfig> {
  return withClientCache<LlamaIndexConfig>(
    `${KNOWLEDGE_CACHE_PREFIX}llamaindex-config`,
    async () => {
      const response = await apiFetch(apiUrl(LLAMAINDEX_CONFIG_PATH), {
        cache: "no-store",
      });
      if (!response.ok) {
        throw new Error(
          await readErrorDetail(response, "Failed to read LlamaIndex config"),
        );
      }
      return (await response.json()) as LlamaIndexConfig;
    },
    { force: options?.force, ttlMs: 15_000 },
  );
}

export async function updateLlamaIndexConfig(
  payload: Partial<Omit<LlamaIndexConfig, "version">>,
): Promise<LlamaIndexConfig> {
  const res = await apiFetch(apiUrl(LLAMAINDEX_CONFIG_PATH), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error(
      await readErrorDetail(res, "Failed to update LlamaIndex config"),
    );
  }
  invalidateKnowledgeCaches();
  return (await res.json()) as LlamaIndexConfig;
}

async function getEngineConfig<T>(
  provider: string,
  cacheKey: string,
  options?: { force?: boolean },
): Promise<T> {
  return withClientCache<T>(
    `${KNOWLEDGE_CACHE_PREFIX}${cacheKey}`,
    async () => {
      const response = await apiFetch(
        apiUrl(`/api/knowledge-bases/rag-pipelines/${provider}/config`),
        { cache: "no-store" },
      );
      if (!response.ok) {
        throw new Error(
          await readErrorDetail(response, `Failed to read ${provider} config`),
        );
      }
      return (await response.json()) as T;
    },
    { force: options?.force, ttlMs: 15_000 },
  );
}

async function updateEngineConfig<T>(
  provider: string,
  payload: Record<string, unknown>,
): Promise<T> {
  const res = await apiFetch(
    apiUrl(`/api/knowledge-bases/rag-pipelines/${provider}/config`),
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  if (!res.ok) {
    throw new Error(
      await readErrorDetail(res, `Failed to update ${provider} config`),
    );
  }
  invalidateKnowledgeCaches();
  return (await res.json()) as T;
}

export const getGraphRagConfig = (options?: { force?: boolean }) =>
  getEngineConfig<GraphRagConfig>("graphrag", "graphrag-config", options);
export const updateGraphRagConfig = (
  payload: Partial<Omit<GraphRagConfig, "version">>,
) => updateEngineConfig<GraphRagConfig>("graphrag", payload);

export const getLightRagConfig = (options?: { force?: boolean }) =>
  getEngineConfig<LightRagConfig>("lightrag", "lightrag-config", options);
export const updateLightRagConfig = (
  payload: Partial<Omit<LightRagConfig, "version">>,
) => updateEngineConfig<LightRagConfig>("lightrag", payload);

export const getLightRagServerConfig = (options?: { force?: boolean }) =>
  getEngineConfig<LightRagServerConfig>(
    "lightrag-server",
    "lightrag-server-config",
    options,
  );

export const updateLightRagServerConfig = (payload: {
  server_url?: string;
  /** Omit to keep the stored key; empty clears it. */
  api_key?: string;
}) => updateEngineConfig<LightRagServerConfig>("lightrag-server", payload);

export async function getEnginePreflight(
  provider: string,
): Promise<EnginePreflight> {
  const res = await apiFetch(
    apiUrl(`/api/knowledge-bases/rag-pipelines/${provider}/preflight`),
    {
      cache: "no-store",
    },
  );
  if (!res.ok) {
    throw new Error(await readErrorDetail(res, "Failed to check environment"));
  }
  return (await res.json()) as EnginePreflight;
}

export async function getEngineModelOptions(
  kinds: string[],
): Promise<ModelOptionsByKind> {
  const res = await apiFetch(
    apiUrl(
      `/api/knowledge-bases/rag-pipelines/model-options?kinds=${encodeURIComponent(kinds.join(","))}`,
    ),
    { cache: "no-store" },
  );
  if (!res.ok) {
    throw new Error(await readErrorDetail(res, "Failed to read model options"));
  }
  return (await res.json()) as ModelOptionsByKind;
}

export async function testGraphRagModelCompatibility(
  profileId: string,
  modelId: string,
): Promise<GraphRagModelCompatibility> {
  const res = await apiFetch(
    apiUrl("/api/knowledge-bases/rag-pipelines/graphrag/model-compatibility"),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profile_id: profileId, model_id: modelId }),
    },
  );
  if (!res.ok) {
    throw new Error(
      await readErrorDetail(res, "Failed to test GraphRAG compatibility"),
    );
  }
  return (await res.json()) as GraphRagModelCompatibility;
}

export async function setEngineActiveModel(
  kind: string,
  profileId: string,
  modelId: string,
): Promise<ModelKindOptions> {
  const res = await apiFetch(
    apiUrl("/api/knowledge-bases/rag-pipelines/active-model"),
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind, profile_id: profileId, model_id: modelId }),
    },
  );
  if (!res.ok) {
    throw new Error(await readErrorDetail(res, "Failed to switch model"));
  }
  invalidateKnowledgeCaches();
  return (await res.json()) as ModelKindOptions;
}

export async function updateRagProviderMode(
  provider: string,
  mode: string,
): Promise<{ provider: string; mode: string }> {
  const res = await apiFetch(
    apiUrl(
      `/api/knowledge-bases/rag-providers/${encodeURIComponent(provider)}/mode`,
    ),
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode }),
    },
  );
  if (!res.ok) {
    throw new Error(
      await readErrorDetail(res, "Failed to update retrieval mode"),
    );
  }
  // The provider list's `default_mode` depends on this; refresh it.
  invalidateKnowledgeCaches();
  return (await res.json()) as { provider: string; mode: string };
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
        apiUrl(`/api/knowledge-bases/${encodeURIComponent(name)}/files`),
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

/** Build the `/api/...` path for a raw KB file (caller can pass to apiUrl()). */
export function knowledgeBaseFilePath(
  kbName: string,
  filename: string,
): string {
  return `/api/knowledge-bases/${encodeURIComponent(kbName)}/files/${filename
    .split("/")
    .map(encodeURIComponent)
    .join("/")}`;
}

/** Build the `/api/...` path for extracted plain-text preview of a raw KB file. */
export function knowledgeBaseFilePreviewTextPath(
  kbName: string,
  filename: string,
): string {
  return `/api/knowledge-bases/${encodeURIComponent(kbName)}/file-preview-text/${filename
    .split("/")
    .map(encodeURIComponent)
    .join("/")}`;
}

export interface KnowledgeTaskResponse {
  task_id?: string;
  message?: string;
  noop?: boolean;
}

export async function readErrorDetail(
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

// A folder upload's File objects carry `webkitRelativePath` (e.g.
// "Papers/2024/a.pdf"); single-file picks leave it "". We forward it as
// `rel_paths` so the backend preserves the folder layout under raw/.
function appendFilesWithPaths(form: FormData, files: File[]): void {
  files.forEach((file) => {
    form.append("files", file);
    form.append("rel_paths", file.webkitRelativePath || "");
  });
}

export async function createKnowledgeBase(payload: {
  name: string;
  provider: string;
  files: File[];
  pageindexMode?: "flash" | "standard";
  searchMode?: string;
}): Promise<KnowledgeTaskResponse> {
  const form = new FormData();
  form.append("name", payload.name);
  form.append("rag_provider", payload.provider);
  if (payload.pageindexMode) {
    form.append("pageindex_mode", payload.pageindexMode);
  }
  if (payload.searchMode) form.append("search_mode", payload.searchMode);
  appendFilesWithPaths(form, payload.files);

  const res = await apiFetch(apiUrl("/api/knowledge-bases"), {
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

export async function connectObsidianVault(payload: {
  name: string;
  vaultPath: string;
}): Promise<{ status: string; name: string; vault_path: string }> {
  const res = await apiFetch(apiUrl("/api/knowledge-bases/connect-obsidian"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: payload.name, vault_path: payload.vaultPath }),
  });
  if (!res.ok) {
    throw new Error(
      await readErrorDetail(res, "Failed to connect Obsidian vault"),
    );
  }
  invalidateKnowledgeCaches();
  return (await res.json()) as {
    status: string;
    name: string;
    vault_path: string;
  };
}

export async function connectMarginNote4Library(payload: {
  name: string;
  description?: string;
}): Promise<{ status: string; name: string; db_path?: string }> {
  const res = await apiFetch(
    apiUrl("/api/knowledge-bases/connect-marginnote4"),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      // `db_path` is deliberately not sent: leaving it blank keeps one rule for
      // where the store lives (derived from the name), which is what lets the
      // pairing endpoints, the Add-on's syncs and the capability binding agree.
      body: JSON.stringify({
        name: payload.name,
        description: payload.description ?? "",
      }),
    },
  );
  if (!res.ok) {
    throw new Error(
      await readErrorDetail(res, "Failed to connect MarginNote 4 library"),
    );
  }
  invalidateKnowledgeCaches();
  return (await res.json()) as {
    status: string;
    name: string;
    db_path?: string;
  };
}

export interface LinkedFolderProbe {
  /** Whether the folder holds a ready index for the chosen engine. */
  ok: boolean;
  provider: string;
  external_path: string;
  version: string | null;
  doc_count: number | null;
  embedding: {
    /** null when compatibility could not be verified. */
    compatible: boolean | null;
    index_model: string | null;
    current_model: string | null;
  };
  warnings: string[];
  /** Set when the folder cannot be linked at all (no index, wrong engine, …). */
  error: string | null;
}

export async function probeLinkedFolder(payload: {
  folderPath: string;
  provider: string;
}): Promise<LinkedFolderProbe> {
  const res = await apiFetch(apiUrl("/api/knowledge-bases/probe-folder"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      folder_path: payload.folderPath,
      rag_provider: payload.provider,
    }),
  });
  if (!res.ok) {
    throw new Error(await readErrorDetail(res, "Failed to inspect folder"));
  }
  return (await res.json()) as LinkedFolderProbe;
}

export async function connectLinkedFolder(payload: {
  name: string;
  folderPath: string;
  provider: string;
}): Promise<{
  status: string;
  name: string;
  external_path: string;
  rag_provider: string;
  warnings: string[];
}> {
  const res = await apiFetch(apiUrl("/api/knowledge-bases/connect-folder"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: payload.name,
      folder_path: payload.folderPath,
      rag_provider: payload.provider,
    }),
  });
  if (!res.ok) {
    throw new Error(await readErrorDetail(res, "Failed to link folder"));
  }
  invalidateKnowledgeCaches();
  return (await res.json()) as {
    status: string;
    name: string;
    external_path: string;
    rag_provider: string;
    warnings: string[];
  };
}

export interface LightRagServerProbe {
  /** Reachable, a LightRAG server, and (if required) the API key is accepted. */
  ok: boolean;
  base_url: string;
  reachable: boolean;
  auth_required: boolean;
  auth_ok: boolean;
  core_version: string | null;
  api_version: string | null;
  /** Set when the server can't be connected (unreachable, bad key, …). */
  error: string | null;
}

export interface WeKnoraProbe {
  ok: boolean;
  base_url: string;
  knowledge_base_id: string;
  reachable: boolean;
  credentials_ok: boolean;
  knowledge_base_found: boolean;
  knowledge_base_name: string | null;
  error: string | null;
}

export interface ImaKnowledgeBasePage {
  knowledge_bases: ImaKnowledgeBaseOption[];
  next_cursor: string;
  is_end: boolean;
}

export interface ImaProbe {
  knowledge_base_id: string;
  ok: boolean;
  credentials_ok: boolean;
  knowledge_base_name: string | null;
  description: string | null;
  error: string | null;
}

export async function listImaKnowledgeBases(payload: {
  /** Empty falls back to the account credentials stored on the engine page. */
  clientId?: string;
  apiKey?: string;
  cursor?: string;
  limit?: number;
}): Promise<ImaKnowledgeBasePage> {
  const res = await apiFetch(apiUrl("/api/knowledge-bases/list-ima"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      client_id: payload.clientId ?? "",
      api_key: payload.apiKey ?? "",
      cursor: payload.cursor ?? "",
      limit: payload.limit ?? 20,
    }),
    skipAuthRedirect: true,
  });
  if (!res.ok) {
    throw new Error(
      await readErrorDetail(res, "Failed to read Tencent IMA knowledge bases"),
    );
  }
  return (await res.json()) as ImaKnowledgeBasePage;
}

export async function probeImaKnowledgeBase(payload: {
  clientId?: string;
  apiKey?: string;
  knowledgeBaseId: string;
}): Promise<ImaProbe> {
  const res = await apiFetch(apiUrl("/api/knowledge-bases/probe-ima"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      client_id: payload.clientId ?? "",
      api_key: payload.apiKey ?? "",
      knowledge_base_id: payload.knowledgeBaseId,
    }),
    skipAuthRedirect: true,
  });
  if (!res.ok) {
    throw new Error(
      await readErrorDetail(res, "Failed to verify Tencent IMA knowledge base"),
    );
  }
  return (await res.json()) as ImaProbe;
}

export async function connectImaKnowledgeBase(payload: {
  name: string;
  /** Empty binds the KB to the account credentials instead of pinning a copy. */
  clientId?: string;
  apiKey?: string;
  knowledgeBaseId: string;
}): Promise<{
  status: string;
  name: string;
  knowledge_base_id: string;
  rag_provider: string;
}> {
  const res = await apiFetch(apiUrl("/api/knowledge-bases/connect-ima"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: payload.name,
      client_id: payload.clientId ?? "",
      api_key: payload.apiKey ?? "",
      knowledge_base_id: payload.knowledgeBaseId,
    }),
    skipAuthRedirect: true,
  });
  if (!res.ok) {
    throw new Error(
      await readErrorDetail(
        res,
        "Failed to connect Tencent IMA knowledge base",
      ),
    );
  }
  invalidateKnowledgeCaches();
  return (await res.json()) as {
    status: string;
    name: string;
    knowledge_base_id: string;
    rag_provider: string;
  };
}

export async function probeLightRagServer(payload: {
  serverUrl: string;
  apiKey?: string;
  useSavedApiKey?: boolean;
}): Promise<LightRagServerProbe> {
  const res = await apiFetch(
    apiUrl("/api/knowledge-bases/probe-lightrag-server"),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        server_url: payload.serverUrl,
        api_key: payload.apiKey ?? "",
        use_saved_api_key: payload.useSavedApiKey ?? false,
      }),
    },
  );
  if (!res.ok) {
    throw new Error(
      await readErrorDetail(res, "Failed to reach LightRAG server"),
    );
  }
  return (await res.json()) as LightRagServerProbe;
}

export async function connectLightRagServer(payload: {
  name: string;
  serverUrl: string;
  apiKey?: string;
  mode?: string;
}): Promise<{
  status: string;
  name: string;
  server_url: string;
  rag_provider: string;
}> {
  const res = await apiFetch(
    apiUrl("/api/knowledge-bases/connect-lightrag-server"),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: payload.name,
        server_url: payload.serverUrl,
        api_key: payload.apiKey ?? "",
        search_mode: payload.mode ?? "",
      }),
    },
  );
  if (!res.ok) {
    throw new Error(
      await readErrorDetail(res, "Failed to connect LightRAG server"),
    );
  }
  invalidateKnowledgeCaches();
  return (await res.json()) as {
    status: string;
    name: string;
    server_url: string;
    rag_provider: string;
  };
}

export async function probeWeKnora(payload: {
  serverUrl: string;
  apiKey: string;
  knowledgeBaseId: string;
}): Promise<WeKnoraProbe> {
  const res = await apiFetch(apiUrl("/api/knowledge-bases/probe-weknora"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      server_url: payload.serverUrl,
      api_key: payload.apiKey,
      knowledge_base_id: payload.knowledgeBaseId,
    }),
  });
  if (!res.ok) {
    throw new Error(await readErrorDetail(res, "Failed to reach WeKnora"));
  }
  return (await res.json()) as WeKnoraProbe;
}

export async function connectWeKnora(payload: {
  name: string;
  serverUrl: string;
  apiKey: string;
  knowledgeBaseId: string;
}): Promise<{
  status: string;
  name: string;
  server_url: string;
  knowledge_base_id: string;
  rag_provider: string;
}> {
  const res = await apiFetch(apiUrl("/api/knowledge-bases/connect-weknora"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: payload.name,
      server_url: payload.serverUrl,
      api_key: payload.apiKey,
      knowledge_base_id: payload.knowledgeBaseId,
    }),
  });
  if (!res.ok) {
    throw new Error(await readErrorDetail(res, "Failed to connect WeKnora"));
  }
  invalidateKnowledgeCaches();
  return (await res.json()) as {
    status: string;
    name: string;
    server_url: string;
    knowledge_base_id: string;
    rag_provider: string;
  };
}

export async function uploadKnowledgeBaseFiles(
  name: string,
  files: File[],
  options?: { provider?: string; destSubdir?: string },
): Promise<KnowledgeTaskResponse> {
  const form = new FormData();
  appendFilesWithPaths(form, files);
  if (options?.provider) form.append("rag_provider", options.provider);
  // Places the batch under an existing KB folder. A folder pick reports paths
  // relative to the chosen directory, so its ancestors are not in the payload
  // — this is how the caller says where the subtree belongs (#866).
  if (options?.destSubdir) form.append("dest_subdir", options.destSubdir);

  const res = await apiFetch(
    apiUrl(`/api/knowledge-bases/${encodeURIComponent(name)}/upload`),
    {
      method: "POST",
      body: form,
    },
  );
  if (!res.ok) {
    throw new Error(await readErrorDetail(res, "Failed to upload files"));
  }
  invalidateKnowledgeCaches();
  return (await res.json()) as KnowledgeTaskResponse;
}

export async function createKbFolder(
  name: string,
  path: string,
): Promise<void> {
  const res = await apiFetch(
    apiUrl(`/api/knowledge-bases/${encodeURIComponent(name)}/folders`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    },
  );
  if (!res.ok) {
    throw new Error(await readErrorDetail(res, "Failed to create folder"));
  }
  invalidateKnowledgeCaches();
}

export async function moveKbFile(
  name: string,
  source: string,
  destFolder: string,
): Promise<void> {
  const res = await apiFetch(
    apiUrl(`/api/knowledge-bases/${encodeURIComponent(name)}/files/move`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source, dest_folder: destFolder }),
    },
  );
  if (!res.ok) {
    throw new Error(await readErrorDetail(res, "Failed to move file"));
  }
  invalidateKnowledgeCaches();
}

/**
 * Delete a single raw document from a KB. Works even while the KB is in an
 * error state, so an unparseable file can be dropped without rebuilding the
 * whole base. `was_indexed` signals whether a re-index is needed to purge the
 * file's vectors from retrieval.
 */
export async function deleteKbFile(
  name: string,
  filename: string,
): Promise<{ was_indexed: boolean }> {
  const res = await apiFetch(apiUrl(knowledgeBaseFilePath(name, filename)), {
    method: "DELETE",
  });
  if (!res.ok) {
    throw new Error(await readErrorDetail(res, "Failed to delete file"));
  }
  invalidateKnowledgeCaches();
  return (await res.json()) as { was_indexed: boolean };
}

export async function setDefaultKnowledgeBase(name: string): Promise<void> {
  const res = await apiFetch(
    apiUrl(`/api/knowledge-bases/default/${encodeURIComponent(name)}`),
    {
      method: "PUT",
    },
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
    apiUrl(`/api/knowledge-bases/${encodeURIComponent(name)}/reindex`),
    {
      method: "POST",
    },
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

export async function retryKnowledgeBase(
  name: string,
): Promise<KnowledgeTaskResponse> {
  const res = await apiFetch(
    apiUrl(`/api/knowledge-bases/${encodeURIComponent(name)}/retry`),
    {
      method: "POST",
    },
  );
  if (!res.ok) {
    const detail = await readErrorDetail(res, `Retry failed (${res.status})`);
    throw new Error(
      withDockerUpgradeHint(detail, res.status, "Knowledge retry"),
    );
  }
  invalidateKnowledgeCaches();
  return (await res.json()) as KnowledgeTaskResponse;
}

export async function deleteKnowledgeBase(name: string): Promise<void> {
  const res = await apiFetch(
    apiUrl(`/api/knowledge-bases/${encodeURIComponent(name)}`),
    {
      method: "DELETE",
    },
  );
  if (!res.ok) {
    throw new Error(
      await readErrorDetail(res, `Delete failed (${res.status})`),
    );
  }
  invalidateKnowledgeCaches();
}

// ── GitHub sources ───────────────────────────────────────────────────

export interface GitHubSource {
  id: string;
  repo: string;
  branch: string;
  path: string;
  glob: string;
  enabled: boolean;
  last_synced_sha: string;
  last_synced_at: string;
  last_sync_status: string;
  last_sync_error: string | null;
  files_synced: number;
  added_at: string;
}

export interface AddGitHubSourcePayload {
  repo: string;
  branch?: string;
  path?: string;
  glob?: string;
}

export interface GitHubSyncResult {
  source_id: string;
  repo: string;
  ok: boolean;
  skipped: boolean;
  files_added: number;
  files_updated: number;
  files_removed: number;
  error: string | null;
}

export async function listGitHubSources(
  kbName: string,
): Promise<GitHubSource[]> {
  const res = await apiFetch(
    apiUrl(`/api/knowledge-bases/${encodeURIComponent(kbName)}/github-sources`),
  );
  if (!res.ok) {
    throw new Error(
      await readErrorDetail(
        res,
        `Failed to list GitHub sources (${res.status})`,
      ),
    );
  }
  return (await res.json()) as GitHubSource[];
}

export async function addGitHubSource(
  kbName: string,
  payload: AddGitHubSourcePayload,
): Promise<GitHubSource> {
  const res = await apiFetch(
    apiUrl(`/api/knowledge-bases/${encodeURIComponent(kbName)}/github-source`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        repo: payload.repo,
        branch: payload.branch ?? "main",
        path: payload.path ?? "",
        glob: payload.glob ?? "*.md",
      }),
    },
  );
  if (!res.ok) {
    throw new Error(
      await readErrorDetail(res, `Failed to add GitHub source (${res.status})`),
    );
  }
  invalidateKnowledgeCaches();
  return (await res.json()) as GitHubSource;
}

export async function removeGitHubSource(
  kbName: string,
  sourceId: string,
): Promise<void> {
  const res = await apiFetch(
    apiUrl(
      `/api/knowledge-bases/${encodeURIComponent(kbName)}/github-source/${encodeURIComponent(sourceId)}`,
    ),
    { method: "DELETE" },
  );
  if (!res.ok) {
    throw new Error(
      await readErrorDetail(
        res,
        `Failed to remove GitHub source (${res.status})`,
      ),
    );
  }
  invalidateKnowledgeCaches();
}

export async function syncGitHubSources(
  kbName: string,
): Promise<GitHubSyncResult[]> {
  const res = await apiFetch(
    apiUrl(`/api/knowledge-bases/${encodeURIComponent(kbName)}/sync-github`),
    { method: "POST" },
  );
  if (!res.ok) {
    throw new Error(
      await readErrorDetail(res, `GitHub sync failed (${res.status})`),
    );
  }
  const body = await res.json();
  return (body.results ?? []) as GitHubSyncResult[];
}

// ── Web sources ──────────────────────────────────────────────────────

export interface WebSource {
  id: string;
  url: string;
  max_depth: number;
  max_pages: number;
  enabled: boolean;
  page_count: number;
  last_synced_at: string;
  last_sync_status: string;
  last_sync_error: string | null;
  added_at: string;
}

export interface AddWebSourcePayload {
  url: string;
  max_depth?: number;
  max_pages?: number;
}

export interface WebSyncSourceResult {
  source_id: string;
  url: string;
  ok: boolean;
  page_count: number;
  pages_added: number;
  pages_updated: number;
  pages_removed: number;
  pages_unchanged: number;
  error: string | null;
}

export interface WebSyncResult {
  ok: boolean;
  message: string;
  results: WebSyncSourceResult[];
}

export async function listWebSources(
  kbName: string,
  options?: { signal?: AbortSignal },
): Promise<WebSource[]> {
  const res = await apiFetch(
    apiUrl(`/api/knowledge-bases/${encodeURIComponent(kbName)}/web-sources`),
    { signal: options?.signal },
  );
  if (!res.ok) {
    throw new Error(
      await readErrorDetail(res, `Failed to list web sources (${res.status})`),
    );
  }
  return (await res.json()) as WebSource[];
}

export async function addWebSource(
  kbName: string,
  payload: AddWebSourcePayload,
): Promise<WebSource> {
  const res = await apiFetch(
    apiUrl(`/api/knowledge-bases/${encodeURIComponent(kbName)}/web-source`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: payload.url,
        max_depth: payload.max_depth ?? 3,
        max_pages: payload.max_pages ?? 200,
      }),
    },
  );
  if (!res.ok) {
    throw new Error(
      await readErrorDetail(res, `Failed to add web source (${res.status})`),
    );
  }
  invalidateKnowledgeCaches();
  return (await res.json()) as WebSource;
}

export async function removeWebSource(
  kbName: string,
  sourceId: string,
): Promise<void> {
  const res = await apiFetch(
    apiUrl(
      `/api/knowledge-bases/${encodeURIComponent(kbName)}/web-source/${encodeURIComponent(sourceId)}`,
    ),
    { method: "DELETE" },
  );
  if (!res.ok) {
    throw new Error(
      await readErrorDetail(res, `Failed to remove web source (${res.status})`),
    );
  }
  invalidateKnowledgeCaches();
}

export async function syncWebSources(kbName: string): Promise<WebSyncResult> {
  const res = await apiFetch(
    apiUrl(`/api/knowledge-bases/${encodeURIComponent(kbName)}/sync-web`),
    {
      method: "POST",
    },
  );
  if (!res.ok) {
    throw new Error(
      await readErrorDetail(res, `Web sync failed (${res.status})`),
    );
  }
  return (await res.json()) as WebSyncResult;
}
