import type {
  TimedSegment,
  TranscriptCue,
  VideoLearningMark,
  VideoMarkKind,
} from "./video-learning-api";

export const VIDEO_MARK_KINDS = ["key_point", "question", "review"] as const;

export const VIDEO_MARK_COLORS: Record<VideoMarkKind, string> = {
  key_point: "#b45309",
  question: "#1d4ed8",
  review: "#be123c",
};

export function uniqueSortedIndexes(values: number[]): number[] {
  return [...new Set(values.filter((value) => Number.isInteger(value) && value >= 0))].sort(
    (left, right) => left - right,
  );
}

export function rangeFromCues(
  cues: TranscriptCue[],
  indexes: number[],
): { start_seconds: number; end_seconds: number; quote: string } | null {
  const selected = uniqueSortedIndexes(indexes)
    .map((index) => cues[index])
    .filter((cue): cue is TranscriptCue => Boolean(cue));
  if (!selected.length) return null;
  return {
    start_seconds: Math.min(...selected.map((cue) => cue.start)),
    end_seconds: Math.max(...selected.map((cue) => cue.end)),
    quote: selected
      .map((cue) => cue.text.trim())
      .filter(Boolean)
      .join(" "),
  };
}

export function locatorsForRange(
  segments: TimedSegment[],
  start: number,
  end: number,
): { start_locator: number; end_locator: number } {
  const overlapping = segments.filter(
    (segment) => segment.end >= start && segment.start <= end,
  );
  if (!overlapping.length) return { start_locator: 0, end_locator: 0 };
  return {
    start_locator: overlapping[0].locator,
    end_locator: overlapping[overlapping.length - 1].locator,
  };
}

export function markCoversTime(
  mark: Pick<VideoLearningMark, "start_seconds" | "end_seconds">,
  time: number,
): boolean {
  if (mark.end_seconds <= mark.start_seconds) {
    return Math.abs(time - mark.start_seconds) <= 1;
  }
  return time >= mark.start_seconds && time <= mark.end_seconds;
}

export function filterMarks(
  marks: VideoLearningMark[],
  kind: VideoMarkKind | "all",
): VideoLearningMark[] {
  const sorted = [...marks].sort(
    (left, right) =>
      left.start_seconds - right.start_seconds ||
      left.end_seconds - right.end_seconds ||
      left.mark_id.localeCompare(right.mark_id),
  );
  return kind === "all" ? sorted : sorted.filter((mark) => mark.kind === kind);
}

export function cueIndexesFromSelection(
  root: ParentNode | null,
  selection: Selection | null,
): number[] {
  if (!root || !selection || selection.rangeCount === 0 || selection.isCollapsed) {
    return [];
  }
  const indexes: number[] = [];
  for (let rangeIndex = 0; rangeIndex < selection.rangeCount; rangeIndex += 1) {
    const range = selection.getRangeAt(rangeIndex);
    const ancestor = range.commonAncestorContainer;
    const ancestorElement =
      ancestor instanceof Element ? ancestor : ancestor.parentElement;
    if (!ancestorElement || !root.contains(ancestorElement)) continue;
    const nodes = ancestorElement.querySelectorAll("[data-cue-index]");
    const candidates = [ancestorElement, ...Array.from(nodes)];
    for (const node of candidates) {
      if (
        !(node instanceof HTMLElement) ||
        !node.hasAttribute("data-cue-index") ||
        !range.intersectsNode(node)
      ) {
        continue;
      }
      const index = Number(node.getAttribute("data-cue-index"));
      if (Number.isInteger(index)) indexes.push(index);
    }
  }
  return uniqueSortedIndexes(indexes);
}

export function formatMarkRange(
  mark: Pick<VideoLearningMark, "start_seconds" | "end_seconds">,
): string {
  if (mark.end_seconds <= mark.start_seconds) {
    return formatMarkTime(mark.start_seconds);
  }
  return `${formatMarkTime(mark.start_seconds)} - ${formatMarkTime(mark.end_seconds)}`;
}

export function formatMarkTime(value: number): string {
  const total = Math.max(0, Math.floor(value));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  return hours
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`
    : `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

export const cuesToRange = rangeFromCues;

export function cuesToSegmentLocators(
  indexes: number[],
  cues: TranscriptCue[],
): { start_locator: number; end_locator: number } {
  const range = rangeFromCues(cues, indexes);
  if (!range) return { start_locator: 0, end_locator: 0 };
  const segments = cues.map((cue, index) => ({ ...cue, locator: index + 1 }));
  return locatorsForRange(segments, range.start_seconds, range.end_seconds);
}
