import type { TimedCue, TimedSegment, VideoLearningMark, VideoMarkKind, VideoNote } from "./video-learning-api";

export const VIDEO_MARK_KINDS = ["key_point", "question", "review"] as const;

export const VIDEO_MARK_COLORS: Record<VideoMarkKind, string> = {
  key_point: "#b45309",
  question: "#1d4ed8",
  review: "#be123c",
};

export function findActiveCueIndex(cues: TimedCue[], currentTime: number): number {
  let low = 0;
  let high = cues.length - 1;
  let candidate = -1;
  while (low <= high) {
    const middle = Math.floor((low + high) / 2);
    if (cues[middle].start <= currentTime) {
      candidate = middle;
      low = middle + 1;
    } else {
      high = middle - 1;
    }
  }
  return candidate >= 0 && currentTime <= cues[candidate].end ? candidate : -1;
}

export function normalizeCueQuote(value: string): string {
  const entities: Record<string, string> = {
    amp: "&",
    apos: "'",
    gt: ">",
    lt: "<",
    nbsp: " ",
    quot: '"',
  };
  return value
    .replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (match, entity: string) => {
      if (entity[0] !== "#") return entities[entity.toLowerCase()] ?? match;
      const hex = entity[1]?.toLowerCase() === "x";
      const codePoint = Number.parseInt(entity.slice(hex ? 2 : 1), hex ? 16 : 10);
      return Number.isFinite(codePoint) ? String.fromCodePoint(codePoint) : match;
    })
    .replace(/\s+/g, " ")
    .trim()
    .toLocaleLowerCase();
}

export function noteMatchesCue(note: VideoNote, cue: TimedCue): boolean {
  if (note.time_seconds >= cue.start - 0.5 && note.time_seconds <= cue.end + 0.5) return true;
  const noteQuote = normalizeCueQuote(note.quote || "");
  const cueQuote = normalizeCueQuote(cue.text);
  return Boolean(noteQuote) && (
    noteQuote === cueQuote || noteQuote.includes(cueQuote) || cueQuote.includes(noteQuote)
  );
}

export function uniqueSortedIndexes(values: number[]): number[] {
  return [...new Set(values.filter((value) => Number.isInteger(value) && value >= 0))].sort(
    (left, right) => left - right
  );
}

export function rangeFromCues(
  cues: TimedCue[],
  indexes: number[]
): { start_seconds: number; end_seconds: number; quote: string } | null {
  const selected = uniqueSortedIndexes(indexes)
    .map((index) => cues[index])
    .filter((cue): cue is TimedCue => Boolean(cue));
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
  end: number
): { start_locator: number; end_locator: number } {
  const overlapping = segments.filter((segment) => segment.end >= start && segment.start <= end);
  if (!overlapping.length) return { start_locator: 0, end_locator: 0 };
  return {
    start_locator: overlapping[0].locator,
    end_locator: overlapping[overlapping.length - 1].locator,
  };
}

export function isPointMark(mark: Pick<VideoLearningMark, "start_seconds" | "end_seconds">): boolean {
  return mark.end_seconds <= mark.start_seconds;
}

export function markCoversTime(
  mark: Pick<VideoLearningMark, "start_seconds" | "end_seconds">,
  time: number
): boolean {
  if (isPointMark(mark)) return Math.abs(time - mark.start_seconds) <= 1;
  return time >= mark.start_seconds && time <= mark.end_seconds;
}

export function marksAtTime(marks: VideoLearningMark[], time: number): VideoLearningMark[] {
  return marks.filter((mark) => markCoversTime(mark, time));
}

export function sortMarks(marks: VideoLearningMark[]): VideoLearningMark[] {
  return [...marks].sort(
    (left, right) =>
      left.start_seconds - right.start_seconds ||
      left.end_seconds - right.end_seconds ||
      left.mark_id.localeCompare(right.mark_id)
  );
}

export function filterMarks(
  marks: VideoLearningMark[],
  kind: VideoMarkKind | "all"
): VideoLearningMark[] {
  const sorted = sortMarks(marks);
  return kind === "all" ? sorted : sorted.filter((mark) => mark.kind === kind);
}

export function timelineStyle(
  mark: Pick<VideoLearningMark, "start_seconds" | "end_seconds">,
  duration: number
): { left: string; width: string } {
  const total = Math.max(duration, 1);
  const left = (Math.max(0, mark.start_seconds) / total) * 100;
  const span = Math.max(mark.end_seconds - mark.start_seconds, 0);
  const width = Math.max((span / total) * 100, 0.8);
  return { left: asPercent(left), width: asPercent(width) };
}

function asPercent(value: number): string {
  return `${Math.round(value * 10000) / 10000}%`;
}

export function cueIndexesFromSelection(root: ParentNode | null, selection: Selection | null): number[] {
  if (!root || !selection || selection.rangeCount === 0 || selection.isCollapsed) return [];
  const indexes: number[] = [];
  for (let rangeIndex = 0; rangeIndex < selection.rangeCount; rangeIndex += 1) {
    const range = selection.getRangeAt(rangeIndex);
    const ancestor = range.commonAncestorContainer;
    const ancestorElement = ancestor instanceof Element ? ancestor : ancestor.parentElement;
    if (!ancestorElement || !root.contains(ancestorElement)) continue;
    const nodes = ancestorElement.querySelectorAll("[data-cue-index]");
    const candidates = [ancestorElement, ...Array.from(nodes)];
    for (const node of candidates) {
      if (!(node instanceof HTMLElement)) continue;
      if (!node.hasAttribute("data-cue-index")) continue;
      if (!range.intersectsNode(node)) continue;
      const index = Number(node.getAttribute("data-cue-index"));
      if (Number.isInteger(index)) indexes.push(index);
    }
  }
  return uniqueSortedIndexes(indexes);
}

export function formatWatchTime(value: number): string {
  const total = Math.max(0, Math.floor(value));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  return hours
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`
    : `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

export function formatMarkRange(mark: Pick<VideoLearningMark, "start_seconds" | "end_seconds">): string {
  if (isPointMark(mark)) return formatWatchTime(mark.start_seconds);
  return `${formatWatchTime(mark.start_seconds)} – ${formatWatchTime(mark.end_seconds)}`;
}
