export function parseTimedMediaRef(ref: string): {
  materialId: string;
  startSeconds: number;
  endSeconds: number;
} | null {
  const raw = String(ref || "").trim();
  if (!raw || !raw.includes("#t=")) return null;
  const [materialId, stampRaw] = raw.split("#t=");
  const material = String(materialId || "").trim();
  const stamp = String(stampRaw || "").trim();
  if (!material || !stamp) return null;
  const [startRaw, endRaw = ""] = stamp.split("-");
  const start = Number(startRaw);
  const end = endRaw ? Number(endRaw) : start;
  if (!Number.isFinite(start)) return null;
  return {
    materialId: material,
    startSeconds: Math.max(0, start),
    endSeconds: Math.max(0, Number.isFinite(end) ? end : start),
  };
}

export function watchingJumpHref(materialId: string, startSeconds: number): string {
  const start = Math.max(0, Number(startSeconds) || 0);
  const formatted = String(start.toFixed(3)).replace(/\.?0+$/, "");
  return `/home?watching_material=${encodeURIComponent(materialId)}&t=${formatted}`;
}

export function formatWatchClock(seconds: number): string {
  const total = Math.max(0, Math.round(Number(seconds) || 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  }
  return `${minutes}:${String(secs).padStart(2, "0")}`;
}
