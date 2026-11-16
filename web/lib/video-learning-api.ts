import { apiFetch, apiUrl } from "@/lib/api";

export type VideoProvider = "youtube" | "invidious";

export interface TranscriptCue {
  start: number;
  end: number;
  text: string;
}

export interface TimedSegment extends TranscriptCue {
  locator: number;
}

export type VideoMarkKind = "key_point" | "question" | "review";
export type VideoMarkAuthor = "user" | "assistant";
export type VideoMarkSource = "immersive";

export interface VideoLearningMark {
  mark_id: string;
  kind: VideoMarkKind;
  start_seconds: number;
  end_seconds: number;
  start_locator: number;
  end_locator: number;
  quote: string;
  note: string;
  author: VideoMarkAuthor;
  source?: VideoMarkSource;
  metadata?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  reviewed_at?: string;
}

export interface VideoLearningSettings {
  version: 1;
  default_provider: VideoProvider;
  youtube: { transcript_provider: "youtube_transcript_api" | "none" };
  invidious: { api_base_url: string; public_base_url: string };
}

async function unwrap<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw await responseError(response);
  }
  return (await response.json()) as T;
}

async function responseError(response: Response): Promise<Error> {
  const payload = await response.json().catch(() => ({}));
  const detail = (payload as { detail?: unknown })?.detail;
  const message =
    typeof detail === "string"
      ? detail
      : typeof (detail as { message?: unknown } | undefined)?.message ===
          "string"
        ? (detail as { message: string }).message
        : null;
  return new Error(message || `Request failed (${response.status})`);
}

export async function getVideoLearningSettings(): Promise<VideoLearningSettings> {
  return unwrap(
    await apiFetch(apiUrl("/api/settings/video-learning"), {
      cache: "no-store",
    }),
  );
}

export async function testInvidious(
  settings: VideoLearningSettings,
): Promise<{ ok: boolean; message: string }> {
  return unwrap(
    await apiFetch(apiUrl("/api/settings/video-learning/test-invidious"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(settings),
    }),
  );
}

export interface InvidiousAccountStatus {
  connected: boolean;
  needs_reauthorization?: boolean;
}
export interface InvidiousVideo {
  videoId: string;
  title: string;
  author: string;
  lengthSeconds: number;
  videoThumbnails?: { url: string }[];
}
export interface InvidiousPlaylist {
  playlistId: string;
  title: string;
  videoCount: number;
  videos?: InvidiousVideo[];
}
export interface InvidiousCatalog {
  videos?: InvidiousVideo[];
}
export async function invidiousAccount(
  action: "status" | "authorize" | "disconnect",
) {
  return unwrap<InvidiousAccountStatus & { authorize_url?: string }>(
    await apiFetch(`/api/video-learning/invidious/account/${action}`, {
      method: action === "status" ? "GET" : "POST",
      cache: "no-store",
    }),
  );
}
export async function browseInvidious(
  kind: string,
  query: string,
  page: number,
  playlistId: string,
  signal: AbortSignal,
) {
  const params = new URLSearchParams({
    q: query,
    page: String(page),
    playlist_id: playlistId,
  });
  return unwrap<InvidiousVideo[] | InvidiousPlaylist[] | InvidiousCatalog>(
    await apiFetch(`/api/video-learning/invidious/browse/${kind}?${params}`, {
      signal,
      cache: "no-store",
    }),
  );
}
