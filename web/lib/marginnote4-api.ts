import { apiFetch, apiUrl } from "@/lib/api";
import { readErrorDetail } from "@/lib/knowledge-api";

/**
 * Device bridge for a connected MarginNote 4 library.
 *
 * A library holds no documents of its own: the MN4 Add-on pushes notes,
 * excerpts, cards and mindmap nodes into it, authenticating with a token this
 * module hands out at pairing time. Every call names the library through
 * `X-MN4-KB`, which is what makes that token findable by the Add-on's later
 * syncs — the backend resolves one store from that same name (see
 * `capabilities/marginnote4/store.resolve_db_path`).
 *
 * Shapes are the wire shapes, matching the router's `DeviceInfo` /
 * `PairResponse` rather than restating them in another casing.
 */

const BASE = "/api/v1/marginnote4";

export interface MarginNoteDevice {
  device_id: string;
  device_name: string;
  device_kind: string;
  paired_at: string;
  last_seen: string;
  active: boolean;
}

/** Returned once, at pairing. The server keeps only a hash of `token`. */
export interface MarginNotePairing {
  device_id: string;
  token: string;
  device_name: string;
  device_kind: string;
}

export interface MarginNoteLibraryStatus {
  status: string;
  devices: number;
  objects: number;
}

const libraryHeaders = (kbName: string): HeadersInit => ({
  "Content-Type": "application/json",
  "X-MN4-KB": kbName,
});

export async function pairMarginNote4Device(payload: {
  kbName: string;
  deviceName: string;
  deviceKind?: string;
}): Promise<MarginNotePairing> {
  const res = await apiFetch(apiUrl(`${BASE}/pair`), {
    method: "POST",
    headers: libraryHeaders(payload.kbName),
    body: JSON.stringify({
      device_name: payload.deviceName,
      device_kind: payload.deviceKind || "macos",
    }),
  });
  if (!res.ok) {
    throw new Error(await readErrorDetail(res, "Failed to pair the device"));
  }
  return (await res.json()) as MarginNotePairing;
}

export async function listMarginNote4Devices(
  kbName: string,
): Promise<MarginNoteDevice[]> {
  const res = await apiFetch(apiUrl(`${BASE}/devices`), {
    headers: libraryHeaders(kbName),
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(
      await readErrorDetail(res, "Failed to load paired devices"),
    );
  }
  const data = await res.json();
  return Array.isArray(data) ? (data as MarginNoteDevice[]) : [];
}

export async function revokeMarginNote4Device(payload: {
  kbName: string;
  deviceId: string;
}): Promise<void> {
  const res = await apiFetch(
    apiUrl(`${BASE}/devices/${encodeURIComponent(payload.deviceId)}`),
    { method: "DELETE", headers: libraryHeaders(payload.kbName) },
  );
  if (!res.ok) {
    throw new Error(await readErrorDetail(res, "Failed to revoke the device"));
  }
}

export async function getMarginNote4Status(
  kbName: string,
): Promise<MarginNoteLibraryStatus> {
  const res = await apiFetch(apiUrl(`${BASE}/status`), {
    headers: libraryHeaders(kbName),
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(
      await readErrorDetail(res, "Failed to load the library status"),
    );
  }
  return (await res.json()) as MarginNoteLibraryStatus;
}
