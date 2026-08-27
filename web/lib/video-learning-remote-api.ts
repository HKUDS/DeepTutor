import { apiFetch } from "@/lib/api";
import type { VideoLearningMark, VideoMarkKind } from "@/lib/video-learning-api";

export type PlaybackState = "playing" | "paused" | "buffering" | "ended" | "unknown";

export interface RemoteSession {
  session_id: string;
  owner_id?: string;
  device_id: string;
  instance_origin: string;
  video_id: string;
  material_id?: string;
  title: string;
  position_ms: number;
  duration_ms: number;
  playback_state: PlaybackState | string;
  playback_rate: number;
  updated_at: string;
  last_heartbeat_at: string;
  online: boolean;
}

export type RemoteAnnotation = VideoLearningMark;

export interface RemoteNote {
  note_id: string;
  video_id: string;
  title: string;
  position_ms: number;
  body: string;
  source: string;
  instance_origin: string;
  created_at: string;
  updated_at: string;
}

export interface RemoteCommand {
  command_id: string;
  type: string;
  payload: Record<string, unknown>;
  status: string;
  created_at: string;
  acked_at?: string | null;
  error?: string | null;
}

export interface RendererLaunch {
  bootstrap_id: string;
  ticket: string;
  expires_at: string;
  launch_url: string;
  qr_data_url: string;
  invidious_login_available: boolean;
}

async function readError(response: Response): Promise<string> {
  try {
    const data = await response.json();
    if (typeof data?.detail === "string") return data.detail;
    return JSON.stringify(data);
  } catch {
    return response.statusText || `HTTP ${response.status}`;
  }
}

export async function claimPairingCode(code: string, deviceName = "iPad") {
  const response = await apiFetch("/api/v1/video-learning/pairings/claim", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code, device_name: deviceName, device_kind: "ipad" }),
  });
  if (!response.ok) throw new Error(await readError(response));
  return response.json();
}

export async function createRendererLaunch(options?: {
  deviceName?: string;
  videoId?: string;
  positionSeconds?: number;
  materialId?: string;
}): Promise<RendererLaunch> {
  const response = await apiFetch("/api/v1/video-learning/renderers", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      device_name: options?.deviceName ?? "This device",
      device_kind: "current-device",
      video_id: options?.videoId,
      position_seconds: options?.positionSeconds ?? 0,
      material_id: options?.materialId,
    }),
  });
  if (!response.ok) throw new Error(await readError(response));
  return response.json();
}

export async function listRemoteSessions(): Promise<RemoteSession[]> {
  const response = await apiFetch("/api/v1/video-learning/sessions");
  if (!response.ok) throw new Error(await readError(response));
  const data = await response.json();
  return data.sessions || [];
}

export async function listDevices() {
  const response = await apiFetch("/api/v1/video-learning/devices");
  if (!response.ok) throw new Error(await readError(response));
  return response.json();
}

export async function sendDeviceCommand(deviceId: string, videoId: string): Promise<RemoteCommand> {
  const response = await apiFetch(`/api/v1/video-learning/devices/${encodeURIComponent(deviceId)}/commands`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ type: "open_video", video_id: videoId }),
  });
  if (!response.ok) throw new Error(await readError(response));
  return response.json();
}

export async function getDeviceCommand(deviceId: string, commandId: string): Promise<RemoteCommand> {
  const response = await apiFetch(
    `/api/v1/video-learning/devices/${encodeURIComponent(deviceId)}/commands/${encodeURIComponent(commandId)}`,
  );
  if (!response.ok) throw new Error(await readError(response));
  return response.json();
}

export async function revokeDevice(deviceId: string) {
  const response = await apiFetch(`/api/v1/video-learning/devices/${deviceId}`, {
    method: "DELETE",
  });
  if (!response.ok) throw new Error(await readError(response));
  return response.json();
}

export async function sendSessionCommand(
  sessionId: string,
  payload: {
    type: string;
    position_ms?: number;
    delta_ms?: number;
    volume?: number;
    muted?: boolean;
    playback_rate?: number;
    command_id?: string;
  },
): Promise<RemoteCommand> {
  const response = await apiFetch(`/api/v1/video-learning/sessions/${sessionId}/commands`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(await readError(response));
  return response.json();
}

export async function getSessionCommand(sessionId: string, commandId: string): Promise<RemoteCommand> {
  const response = await apiFetch(`/api/v1/video-learning/sessions/${sessionId}/commands/${commandId}`);
  if (!response.ok) throw new Error(await readError(response));
  return response.json();
}

export async function listVideoNotes(videoId: string): Promise<RemoteNote[]> {
  const response = await apiFetch(`/api/v1/video-learning/videos/${encodeURIComponent(videoId)}/notes`);
  if (!response.ok) throw new Error(await readError(response));
  const data = await response.json();
  return data.notes || [];
}

export async function createVideoNote(
  videoId: string,
  payload: { body: string; session_id?: string; position_ms?: number; title?: string },
): Promise<RemoteNote> {
  const response = await apiFetch(`/api/v1/video-learning/videos/${encodeURIComponent(videoId)}/notes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(await readError(response));
  return response.json();
}

export async function updateVideoNote(noteId: string, body: string): Promise<RemoteNote> {
  const response = await apiFetch(`/api/v1/video-learning/notes/${noteId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ body }),
  });
  if (!response.ok) throw new Error(await readError(response));
  return response.json();
}

export async function deleteVideoNote(noteId: string): Promise<void> {
  const response = await apiFetch(`/api/v1/video-learning/notes/${noteId}`, {
    method: "DELETE",
  });
  if (!response.ok) throw new Error(await readError(response));
}

export async function listSessionAnnotations(sessionId: string): Promise<RemoteAnnotation[]> {
  const response = await apiFetch(`/api/v1/video-learning/sessions/${encodeURIComponent(sessionId)}/annotations`);
  if (!response.ok) throw new Error(await readError(response));
  const data = await response.json();
  return data.annotations || [];
}

export async function createSessionAnnotation(
  sessionId: string,
  payload: { kind: VideoMarkKind; note?: string },
): Promise<RemoteAnnotation> {
  const response = await apiFetch(`/api/v1/video-learning/sessions/${encodeURIComponent(sessionId)}/annotations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(await readError(response));
  return response.json();
}

export async function updateSessionAnnotation(
  sessionId: string,
  markId: string,
  payload: { note: string; reviewed?: boolean },
): Promise<RemoteAnnotation> {
  const response = await apiFetch(
    `/api/v1/video-learning/sessions/${encodeURIComponent(sessionId)}/annotations/${encodeURIComponent(markId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  if (!response.ok) throw new Error(await readError(response));
  return response.json();
}

export async function deleteSessionAnnotation(sessionId: string, markId: string): Promise<void> {
  const response = await apiFetch(
    `/api/v1/video-learning/sessions/${encodeURIComponent(sessionId)}/annotations/${encodeURIComponent(markId)}`,
    { method: "DELETE" },
  );
  if (!response.ok) throw new Error(await readError(response));
}

export function parseVideoIdInput(raw: string): string | null {
  const value = raw.trim();
  if (!value) return null;
  if (/^[A-Za-z0-9_-]{11}$/.test(value)) return value;
  try {
    const url = new URL(value);
    if (url.protocol !== "http:" && url.protocol !== "https:") return null;
    if (url.hostname === "youtu.be") {
      const candidate = url.pathname.split("/").filter(Boolean)[0] || "";
      return /^[A-Za-z0-9_-]{11}$/.test(candidate) ? candidate : null;
    }
    const candidate = url.searchParams.get("v") || "";
    return /^[A-Za-z0-9_-]{11}$/.test(candidate) ? candidate : null;
  } catch {
    return null;
  }
}

export function formatPosition(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return `${m}:${String(s).padStart(2, "0")}`;
}
