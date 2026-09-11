export const WATCHING_CAPABILITY = "immersive_watching";

interface WatchingTurnState {
  materialId: string | null;
  timeSeconds: number;
}

const state: WatchingTurnState = { materialId: null, timeSeconds: 0 };

export function setWatchingMaterial(materialId: string | null): void {
  state.materialId = materialId;
  if (!materialId) state.timeSeconds = 0;
}

export function setWatchingViewport(timeSeconds: number): void {
  if (Number.isFinite(timeSeconds))
    state.timeSeconds = Math.max(0, timeSeconds);
}

export function watchingTurnFields(capability: string | null | undefined): {
  timed_media_id?: string;
  timed_media_viewport?: { time_seconds: number };
} {
  if (capability !== WATCHING_CAPABILITY || !state.materialId) return {};
  return {
    timed_media_id: state.materialId,
    timed_media_viewport: { time_seconds: state.timeSeconds },
  };
}

export function resetWatchingTurnState(): void {
  state.materialId = null;
  state.timeSeconds = 0;
}
