export interface ReadingHistoryEntry {
  locator: number;
  quote?: string;
  headingId?: string;
}

export interface ReadingHistoryState {
  back: ReadingHistoryEntry[];
  current: ReadingHistoryEntry | null;
  forward: ReadingHistoryEntry[];
}

function sameEntry(
  left: ReadingHistoryEntry | null,
  right: ReadingHistoryEntry,
): boolean {
  return (
    left?.locator === right.locator &&
    left?.quote === right.quote &&
    left?.headingId === right.headingId
  );
}

export function pushReadingHistory(
  state: ReadingHistoryState,
  next: ReadingHistoryEntry,
): ReadingHistoryState {
  if (sameEntry(state.current, next)) return state;
  if (!state.current) {
    return { back: [], current: next, forward: [] };
  }
  return {
    back: [...state.back, state.current],
    current: next,
    forward: [],
  };
}

export function goBackReadingHistory(
  state: ReadingHistoryState,
): ReadingHistoryState {
  const previous = state.back.at(-1);
  if (!previous || !state.current) return state;
  return {
    back: state.back.slice(0, -1),
    current: previous,
    forward: [state.current, ...state.forward],
  };
}

export function goForwardReadingHistory(
  state: ReadingHistoryState,
): ReadingHistoryState {
  const next = state.forward[0];
  if (!next || !state.current) return state;
  return {
    back: [...state.back, state.current],
    current: next,
    forward: state.forward.slice(1),
  };
}
