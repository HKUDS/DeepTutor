export const WATCHING_CAPABILITY = "immersive_watching";
export const WATCHING_ASK_EVENT = "dt:watching-ask";

const state = { materialId: null as string | null, timeSeconds: 0, locator: 0 };
let modeActive = false;
const modeListeners = new Set<() => void>();

export function setWatchingModeActive(active: boolean): void {
  if (modeActive === active) return;
  modeActive = active;
  modeListeners.forEach((listener) => listener());
}

export function getWatchingModeActive(): boolean { return modeActive; }
export function subscribeWatchingMode(listener: () => void): () => void {
  modeListeners.add(listener);
  return () => modeListeners.delete(listener);
}

export function setWatchingMaterial(materialId: string | null): void {
  state.materialId = materialId;
  if (!materialId) { state.timeSeconds = 0; state.locator = 0; }
}

export function setWatchingViewport(next: { timeSeconds?: number; locator?: number }): void {
  if (typeof next.timeSeconds === "number" && Number.isFinite(next.timeSeconds)) state.timeSeconds = Math.max(0, next.timeSeconds);
  if (typeof next.locator === "number" && Number.isFinite(next.locator)) state.locator = Math.max(0, Math.floor(next.locator));
}

export function watchingTurnFields(capability: string | null | undefined): { timed_media_id?: string; timed_media_viewport?: { time_seconds: number; locator?: number } } {
  if (capability !== WATCHING_CAPABILITY || !state.materialId) return {};
  return { timed_media_id: state.materialId, timed_media_viewport: { time_seconds: state.timeSeconds, ...(state.locator > 0 ? { locator: state.locator } : {}) } };
}

export function resetWatchingTurnState(): void { state.materialId = null; state.timeSeconds = 0; state.locator = 0; }
