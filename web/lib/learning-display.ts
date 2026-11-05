import { recoveryPrincipal } from "@/lib/recovery-principal";

/** Server-authoritative learning typography. No browser persistence. */
export const CONTENT_FONT_SCALES = [90, 100, 110, 125, 150] as const;
export type ContentFontScale = (typeof CONTENT_FONT_SCALES)[number];
export const CONTENT_LINE_SPACING = {
  compact: 1.5,
  normal: 1.75,
  relaxed: 2,
} as const;
export type ContentLineSpacing = keyof typeof CONTENT_LINE_SPACING;
export type LearningDisplay = {
  content_font_scale: ContentFontScale;
  content_line_spacing: ContentLineSpacing;
};
export const DEFAULT_LEARNING_DISPLAY: LearningDisplay = {
  content_font_scale: 100,
  content_line_spacing: "normal",
};
export const LEARNING_DISPLAY_APPLIED = "deeptutor:learning-display-applied";
export function normalizeLearningDisplay(
  value: Partial<LearningDisplay> | null | undefined,
): LearningDisplay {
  return {
    content_font_scale: CONTENT_FONT_SCALES.includes(
      value?.content_font_scale as ContentFontScale,
    )
      ? value!.content_font_scale!
      : 100,
    content_line_spacing: Object.hasOwn(
      CONTENT_LINE_SPACING,
      value?.content_line_spacing ?? "",
    )
      ? value!.content_line_spacing!
      : "normal",
  };
}
export function publishLearningDisplay(
  value: LearningDisplay,
  principal = recoveryPrincipal(),
): void {
  window.dispatchEvent(
    new CustomEvent(LEARNING_DISPLAY_APPLIED, {
      detail: { preferences: normalizeLearningDisplay(value), principal },
    }),
  );
}
