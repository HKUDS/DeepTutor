import { apiFetch, apiUrl } from "@/lib/api";
import { invalidateClientCache, withClientCache } from "@/lib/client-cache";

const SKILLS_CACHE_PREFIX = "skills:";
const SKILL_TAGS_CACHE_KEY = `${SKILLS_CACHE_PREFIX}tags`;

export type SkillSource = "user" | "builtin" | "admin";

export interface SkillInfo {
  name: string;
  description: string;
  tags: string[];
  source?: SkillSource;
  read_only?: boolean;
}

export interface SkillDetail extends SkillInfo {
  content: string;
}

export interface CreateSkillPayload {
  name: string;
  description: string;
  content: string;
  tags?: string[];
}

export interface UpdateSkillPayload {
  description?: string;
  content?: string;
  rename_to?: string;
  tags?: string[];
}

function normalizeSource(raw: unknown): SkillSource {
  return raw === "builtin" || raw === "admin" ? raw : "user";
}

function normalizeTags(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  const seen = new Set<string>();
  const out: string[] = [];
  for (const item of raw) {
    const tag = String(item ?? "")
      .trim()
      .toLowerCase();
    if (!tag || seen.has(tag)) continue;
    seen.add(tag);
    out.push(tag);
  }
  return out;
}

async function asJson(response: Response) {
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return response.json();
}

export async function listSkills(options?: {
  force?: boolean;
}): Promise<SkillInfo[]> {
  return withClientCache<SkillInfo[]>(
    `${SKILLS_CACHE_PREFIX}list`,
    async () => {
      const response = await apiFetch(apiUrl("/api/v1/skills/list"), {
        cache: "no-store",
      });
      const data = await asJson(response);
      const items = Array.isArray(data?.skills) ? data.skills : [];
      return items.map(
        (item: {
          name?: unknown;
          description?: unknown;
          tags?: unknown;
          source?: unknown;
          read_only?: unknown;
        }) => ({
          name: String(item?.name ?? ""),
          description: String(item?.description ?? ""),
          tags: normalizeTags(item?.tags),
          source: normalizeSource(item?.source),
          read_only: Boolean(item?.read_only),
        }),
      );
    },
    { force: options?.force },
  );
}

export async function getSkill(name: string): Promise<SkillDetail> {
  const response = await apiFetch(
    apiUrl(`/api/v1/skills/${encodeURIComponent(name)}`),
    {
      cache: "no-store",
    },
  );
  const data = await asJson(response);
  return {
    name: String(data?.name ?? name),
    description: String(data?.description ?? ""),
    content: String(data?.content ?? ""),
    tags: normalizeTags(data?.tags),
    source: normalizeSource(data?.source),
    read_only: Boolean(data?.read_only),
  };
}

export interface InstalledSkill {
  name: string;
  version: string;
  verdict: { status: string; detail: string };
}

/**
 * Import a hub skill (e.g. from EduHub) into the caller's own skill layer.
 * `ref` is a `<hub>:<slug>[@version]` reference — the EduHub import flow always
 * builds an `eduhub:` ref. Surfaces the hub's security verdict so callers can
 * warn on `unknown`/`suspicious` packages.
 */
export async function installSkillFromHub(
  ref: string,
  options?: { name?: string; force?: boolean; allowUnverified?: boolean },
): Promise<InstalledSkill> {
  const response = await apiFetch(apiUrl("/api/v1/skills/install"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ref,
      name: options?.name,
      force: options?.force ?? false,
      allow_unverified: options?.allowUnverified ?? false,
    }),
  });
  const data = await asJson(response);
  invalidateSkillsCache();
  return {
    name: String(data?.skill?.name ?? ""),
    version: String(data?.version ?? ""),
    verdict: {
      status: String(data?.verdict?.status ?? "unknown"),
      detail: String(data?.verdict?.detail ?? ""),
    },
  };
}

// ── EduHub / hub browsing ───────────────────────────────────────────────
// Powers the in-app "Import from EduHub" browser. The backend proxies the
// hub's public catalog (no login, no iframe), so the panel can render hub
// skills in DeepTutor's own UI and download them with one click.

export interface HubSkillListing {
  slug: string;
  name: string;
  summary: string;
  version: string;
  downloads: number;
  stars: number;
  owner: string;
  ownerUrl: string;
}

export interface HubCatalog {
  hub: string;
  /** The hub's website origin (for a "view on EduHub" link out). */
  webUrl: string;
  skills: HubSkillListing[];
}

export interface HubSkillDetail extends HubSkillListing {
  content: string;
  tags: string[];
  /** Direct link to this skill's page on the hub site. */
  webUrl: string;
}

function normalizeHubListing(item: Record<string, unknown>): HubSkillListing {
  return {
    slug: String(item?.slug ?? ""),
    name: String(item?.name ?? item?.slug ?? ""),
    summary: String(item?.summary ?? ""),
    version: String(item?.version ?? ""),
    downloads: Number(item?.downloads ?? 0),
    stars: Number(item?.stars ?? 0),
    owner: String(item?.owner ?? ""),
    ownerUrl: String(item?.owner_url ?? ""),
  };
}

/** List skills available on a hub (default EduHub). `query` filters server-side. */
export async function fetchHubCatalog(options?: {
  hub?: string;
  query?: string;
  limit?: number;
}): Promise<HubCatalog> {
  const params = new URLSearchParams();
  if (options?.hub) params.set("hub", options.hub);
  if (options?.query) params.set("q", options.query);
  if (options?.limit) params.set("limit", String(options.limit));
  const qs = params.toString();
  const response = await apiFetch(
    apiUrl(`/api/v1/skills/hub/catalog${qs ? `?${qs}` : ""}`),
    { cache: "no-store" },
  );
  const data = await asJson(response);
  const skills = Array.isArray(data?.skills) ? data.skills : [];
  return {
    hub: String(data?.hub ?? "eduhub"),
    webUrl: String(data?.web_url ?? ""),
    skills: skills.map((item: Record<string, unknown>) =>
      normalizeHubListing(item),
    ),
  };
}

/** Full metadata + rendered SKILL.md body for one hub skill. */
export async function fetchHubSkillDetail(
  slug: string,
  options?: { hub?: string },
): Promise<HubSkillDetail> {
  const params = new URLSearchParams({ slug });
  if (options?.hub) params.set("hub", options.hub);
  const response = await apiFetch(
    apiUrl(`/api/v1/skills/hub/detail?${params.toString()}`),
    { cache: "no-store" },
  );
  const data = await asJson(response);
  return {
    ...normalizeHubListing(data),
    content: String(data?.content ?? ""),
    tags: normalizeTags(data?.tags),
    webUrl: String(data?.web_url ?? ""),
  };
}

export async function createSkill(
  payload: CreateSkillPayload,
): Promise<SkillInfo> {
  const response = await apiFetch(apiUrl("/api/v1/skills/create"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: payload.name,
      description: payload.description,
      content: payload.content,
      tags: payload.tags ?? [],
    }),
  });
  const data = await asJson(response);
  invalidateSkillsCache();
  return {
    name: String(data?.name ?? payload.name),
    description: String(data?.description ?? payload.description ?? ""),
    tags: normalizeTags(data?.tags ?? payload.tags),
  };
}

export async function updateSkill(
  name: string,
  payload: UpdateSkillPayload,
): Promise<SkillInfo> {
  const response = await apiFetch(
    apiUrl(`/api/v1/skills/${encodeURIComponent(name)}`),
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  const data = await asJson(response);
  invalidateSkillsCache();
  return {
    name: String(data?.name ?? name),
    description: String(data?.description ?? ""),
    tags: normalizeTags(data?.tags),
  };
}

export async function deleteSkill(name: string): Promise<void> {
  const response = await apiFetch(
    apiUrl(`/api/v1/skills/${encodeURIComponent(name)}`),
    {
      method: "DELETE",
    },
  );
  await asJson(response);
  invalidateSkillsCache();
}

export async function listSkillTags(options?: {
  force?: boolean;
}): Promise<string[]> {
  return withClientCache<string[]>(
    SKILL_TAGS_CACHE_KEY,
    async () => {
      const response = await apiFetch(apiUrl("/api/v1/skills/tags/list"), {
        cache: "no-store",
      });
      const data = await asJson(response);
      return normalizeTags(data?.tags);
    },
    { force: options?.force },
  );
}

export async function createSkillTag(name: string): Promise<string> {
  const response = await apiFetch(apiUrl("/api/v1/skills/tags/create"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  const data = await asJson(response);
  invalidateSkillsCache();
  return String(data?.name ?? name);
}

export async function renameSkillTag(
  oldName: string,
  newName: string,
): Promise<string> {
  const response = await apiFetch(
    apiUrl(`/api/v1/skills/tags/${encodeURIComponent(oldName)}`),
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rename_to: newName }),
    },
  );
  const data = await asJson(response);
  invalidateSkillsCache();
  return String(data?.name ?? newName);
}

export async function deleteSkillTag(name: string): Promise<void> {
  const response = await apiFetch(
    apiUrl(`/api/v1/skills/tags/${encodeURIComponent(name)}`),
    {
      method: "DELETE",
    },
  );
  await asJson(response);
  invalidateSkillsCache();
}

export function invalidateSkillsCache() {
  invalidateClientCache(SKILLS_CACHE_PREFIX);
}
