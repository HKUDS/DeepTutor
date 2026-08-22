export interface KidsChapterCheckInput {
  currentSectionId: string;
  previousSectionId?: string;
  sectionKind: string;
  previousSectionKind?: string;
  atEnd: boolean;
  percentage: number;
  completedSectionIds: string[];
  shownSectionIds: string[];
}

export type KidsChapterCheckTarget = "current" | "previous" | null;

export function shouldOpenChapterCheck(input: KidsChapterCheckInput): KidsChapterCheckTarget {
  const completed = new Set(input.completedSectionIds);
  const shown = new Set(input.shownSectionIds);

  if (input.previousSectionId && input.previousSectionId !== input.currentSectionId) {
    const kind = input.previousSectionKind || "chapter";
    if (kind !== "none" && !completed.has(input.previousSectionId) && !shown.has(input.previousSectionId)) {
      return "previous";
    }
  }

  const reachedEnd = input.atEnd || input.percentage >= 0.98;
  if (
    input.currentSectionId &&
    input.sectionKind !== "none" &&
    reachedEnd &&
    !completed.has(input.currentSectionId) &&
    !shown.has(input.currentSectionId)
  ) {
    return "current";
  }

  return null;
}
