export interface EditorHistoryState {
  content: string;
  undoStack: string[];
  redoStack: string[];
  activeGroup: string | null;
}

export interface SelectedTextRange {
  start: number;
  end: number;
  text: string;
  snapshot: string;
}

export interface ScrollMarker {
  source: number;
  target: number;
}

const DEFAULT_HISTORY_LIMIT = 50;

export function createEditorHistory(content = ""): EditorHistoryState {
  return { content, undoStack: [], redoStack: [], activeGroup: null };
}

export function applyEditorEdit(
  state: EditorHistoryState,
  content: string,
  options: { group?: string; limit?: number } = {},
): EditorHistoryState {
  if (content === state.content) return state;
  const group = options.group ?? null;
  const limit = Math.max(1, options.limit ?? DEFAULT_HISTORY_LIMIT);
  const startsGroup = group === null || group !== state.activeGroup;
  const undoStack = startsGroup
    ? [...state.undoStack, state.content].slice(-limit)
    : state.undoStack;
  return { content, undoStack, redoStack: [], activeGroup: group };
}

export function closeEditorEditGroup(
  state: EditorHistoryState,
): EditorHistoryState {
  return state.activeGroup === null ? state : { ...state, activeGroup: null };
}

export function undoEditorEdit(state: EditorHistoryState): EditorHistoryState {
  const previous = state.undoStack.at(-1);
  if (previous === undefined) return closeEditorEditGroup(state);
  return {
    content: previous,
    undoStack: state.undoStack.slice(0, -1),
    redoStack: [...state.redoStack, state.content],
    activeGroup: null,
  };
}

export function redoEditorEdit(state: EditorHistoryState): EditorHistoryState {
  const next = state.redoStack.at(-1);
  if (next === undefined) return closeEditorEditGroup(state);
  return {
    content: next,
    undoStack: [...state.undoStack, state.content],
    redoStack: state.redoStack.slice(0, -1),
    activeGroup: null,
  };
}

export function replaceSelectedText(
  content: string,
  range: SelectedTextRange,
  replacement: string,
): string | null {
  if (range.snapshot !== content) return null;
  if (
    range.start < 0 ||
    range.end < range.start ||
    range.end > content.length
  ) {
    return null;
  }
  if (content.slice(range.start, range.end) !== range.text) return null;
  return `${content.slice(0, range.start)}${replacement}${content.slice(range.end)}`;
}

export function clampPanelRatio(ratio: number, min = 0.18, max = 0.82): number {
  if (!Number.isFinite(ratio)) return 0.5;
  const lower = Math.min(min, max);
  const upper = Math.max(min, max);
  return Math.min(upper, Math.max(lower, ratio));
}

export function interpolateScrollMarker(
  markers: readonly ScrollMarker[],
  sourcePosition: number,
): number {
  if (markers.length === 0 || !Number.isFinite(sourcePosition)) return 0;
  const sorted = [...markers].sort((a, b) => a.source - b.source);
  if (sourcePosition <= sorted[0].source) return sorted[0].target;
  const last = sorted.at(-1)!;
  if (sourcePosition >= last.source) return last.target;

  for (let index = 1; index < sorted.length; index += 1) {
    const right = sorted[index];
    const left = sorted[index - 1];
    if (sourcePosition > right.source) continue;
    const span = right.source - left.source;
    if (span <= 0) return right.target;
    const progress = (sourcePosition - left.source) / span;
    return left.target + (right.target - left.target) * progress;
  }
  return last.target;
}

export function shouldCommitAutosave(
  requestRevision: number,
  currentRevision: number,
): boolean {
  return requestRevision === currentRevision;
}
