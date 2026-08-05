/**
 * Epoch-based path guard for cross-path async races (UI-02 round-1).
 *
 * ``useKnowledgeCards`` receives a new ``pathId`` while a mutation or refresh
 * from the previous path may still be in flight. Every async dispatch therefore
 * carries a snapshot captured when the work began; the guard rejects the
 * dispatch once the path has changed (or the epoch advanced), so an old path's
 * load, mutation merge/error/end, or post-mutation refresh can never mutate the
 * new path's state.
 *
 * Pure and React-free so node tests exercise the race deterministically.
 */

export interface PathSnapshot {
  pathId: string;
  epoch: number;
}

export interface PathEpoch {
  /** Transition to a path; bumps the epoch only when the path actually changes. */
  set(pathId: string): void;
  /** Snapshot the current path/epoch to guard async work that starts now. */
  snapshot(): PathSnapshot;
  /** True when the snapshot still matches the active path/epoch. */
  isCurrent(snapshot: PathSnapshot): boolean;
  /** The path currently being rendered. */
  pathIdOf(): string;
}

export function createPathEpoch(): PathEpoch {
  let state: PathSnapshot = { pathId: "", epoch: 0 };
  return {
    set(pathId: string) {
      if (state.pathId !== pathId) {
        state = { pathId, epoch: state.epoch + 1 };
      }
    },
    snapshot() {
      return { ...state };
    },
    isCurrent(snapshot) {
      return state.pathId === snapshot.pathId && state.epoch === snapshot.epoch;
    },
    pathIdOf() {
      return state.pathId;
    },
  };
}
