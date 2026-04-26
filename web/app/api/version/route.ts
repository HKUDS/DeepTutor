import { NextResponse } from "next/server";
import { execFileSync } from "node:child_process";
import {
  parseBuild,
  unknownBuild,
  type ParsedBuild,
  type VersionSource,
} from "@/lib/version";

/**
 * Returns both:
 * - current: the version of the code that is actually running
 * - latest: the latest GitHub release for update awareness
 *
 * The route itself stays dynamic so current git metadata is not frozen into
 * the client bundle. The GitHub release lookup is cached separately below.
 */

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

// Refresh the remote release lookup at most once per hour. Tune via env if needed.
const LATEST_REVALIDATE_SECONDS = 3600;
const LATEST_FALLBACK_CACHE_SECONDS = 300;

const DEFAULT_REPO = "HKUDS/DeepTutor";

interface GithubRelease {
  tag_name: string;
  html_url: string;
  name: string | null;
  published_at: string | null;
  prerelease: boolean;
  draft: boolean;
}

interface LatestVersionPayload {
  tag: string | null;
  name: string | null;
  url: string | null;
  publishedAt: string | null;
  source: "github" | "fallback";
}

interface CurrentVersionPayload extends ParsedBuild {
  source: VersionSource;
  detectedAt: string;
}

interface VersionPayload extends LatestVersionPayload {
  current: CurrentVersionPayload;
  latest: LatestVersionPayload;
}

const FALLBACK_LATEST: LatestVersionPayload = {
  tag: null,
  name: null,
  url: `https://github.com/${DEFAULT_REPO}/releases`,
  publishedAt: null,
  source: "fallback",
};

let latestCache: {
  repo: string;
  expiresAt: number;
  payload: LatestVersionPayload;
} | null = null;

function readGitDescribe(): string | null {
  try {
    return execFileSync(
      "git",
      ["describe", "--tags", "--always", "--dirty=-dev"],
      {
        cwd: process.cwd(),
        encoding: "utf8",
        stdio: ["ignore", "pipe", "ignore"],
        timeout: 2000,
      },
    ).trim();
  } catch {
    return null;
  }
}

function detectCurrentVersion(): CurrentVersionPayload {
  const detectedAt = new Date().toISOString();
  const gitRaw = readGitDescribe();
  const envRaw =
    process.env.APP_VERSION || process.env.NEXT_PUBLIC_APP_VERSION || "";
  const raw = gitRaw || envRaw;
  const parsed = parseBuild(raw) ?? unknownBuild(raw);

  return {
    ...parsed,
    source: gitRaw ? "git" : envRaw ? "env" : "unknown",
    detectedAt,
  };
}

function rememberLatest(
  repo: string,
  payload: LatestVersionPayload,
  ttlSeconds: number,
): LatestVersionPayload {
  latestCache = {
    repo,
    expiresAt: Date.now() + ttlSeconds * 1000,
    payload,
  };
  return payload;
}

async function fetchLatestRelease(
  repo: string,
  forceRefresh: boolean,
): Promise<LatestVersionPayload> {
  const now = Date.now();
  if (
    !forceRefresh &&
    latestCache &&
    latestCache.repo === repo &&
    latestCache.expiresAt > now
  ) {
    return latestCache.payload;
  }

  const url = `https://api.github.com/repos/${repo}/releases/latest`;

  const headers: Record<string, string> = {
    Accept: "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "deeptutor-web",
  };
  if (process.env.GITHUB_TOKEN) {
    headers.Authorization = `Bearer ${process.env.GITHUB_TOKEN}`;
  }

  try {
    const res = await fetch(url, {
      headers,
      cache: "no-store",
      signal: AbortSignal.timeout(2500),
    });
    if (!res.ok) {
      return rememberLatest(
        repo,
        { ...FALLBACK_LATEST, url: `https://github.com/${repo}/releases` },
        LATEST_FALLBACK_CACHE_SECONDS,
      );
    }
    const data = (await res.json()) as GithubRelease;
    const payload: LatestVersionPayload = {
      tag: data.tag_name ?? null,
      name: data.name ?? null,
      url: data.html_url ?? `https://github.com/${repo}/releases`,
      publishedAt: data.published_at ?? null,
      source: "github",
    };
    return rememberLatest(repo, payload, LATEST_REVALIDATE_SECONDS);
  } catch {
    return rememberLatest(
      repo,
      { ...FALLBACK_LATEST, url: `https://github.com/${repo}/releases` },
      LATEST_FALLBACK_CACHE_SECONDS,
    );
  }
}

export async function GET(request: Request) {
  const repo = process.env.NEXT_PUBLIC_GITHUB_REPO || DEFAULT_REPO;
  const { searchParams } = new URL(request.url);
  const forceRefresh = searchParams.get("refresh") === "1";

  const current = detectCurrentVersion();
  const latest = await fetchLatestRelease(repo, forceRefresh);

  return NextResponse.json(
    {
      ...latest,
      current,
      latest,
    } satisfies VersionPayload,
    {
      status: 200,
      headers: {
        // The running version is dynamic; callers should not reuse stale payloads.
        "Cache-Control": "no-store",
      },
    },
  );
}
