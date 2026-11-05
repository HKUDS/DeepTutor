import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  ANNOTATION_DEFAULT,
  ANNOTATION_MAX,
  ANNOTATION_MIN,
  useAnnotationPanelWidth,
} from "@/components/reading/useAnnotationPanelWidth";

/**
 * The docked annotation column used to be a fixed 248px — a guess about how
 * much of a note is worth showing. A reader who writes paragraphs wants more;
 * one who only highlights wants the page back.
 */
describe("annotation panel width", () => {
  beforeEach(() => {
    localStorage.clear();
  });
  afterEach(() => {
    localStorage.clear();
  });

  it("starts at the width the column always had", () => {
    const { result } = renderHook(() => useAnnotationPanelWidth());
    expect(result.current.width).toBe(ANNOTATION_DEFAULT);
    expect(ANNOTATION_DEFAULT).toBe(248);
  });

  it("clamps a drag to the supported range", () => {
    const { result } = renderHook(() => useAnnotationPanelWidth());
    act(() => result.current.resize(10));
    expect(result.current.width).toBe(ANNOTATION_MIN);
    act(() => result.current.resize(9999));
    expect(result.current.width).toBe(ANNOTATION_MAX);
  });

  it("rounds a fractional drag", () => {
    const { result } = renderHook(() => useAnnotationPanelWidth());
    act(() => result.current.resize(311.7));
    expect(result.current.width).toBe(312);
  });

  it("remembers the width for the next visit", async () => {
    const first = renderHook(() => useAnnotationPanelWidth());
    act(() => first.result.current.resize(400));
    // The write is debounced so a drag does not hit localStorage per frame.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 200));
    });
    expect(localStorage.getItem("dt.reader.annotationWidth")).toBe("400");

    const second = renderHook(() => useAnnotationPanelWidth());
    expect(second.result.current.width).toBe(400);
  });

  it("ignores a stored width outside the range", () => {
    localStorage.setItem("dt.reader.annotationWidth", "9999");
    const { result } = renderHook(() => useAnnotationPanelWidth());
    // A value from an older layout must not produce an unusable column.
    expect(result.current.width).toBe(ANNOTATION_DEFAULT);
  });

  it("ignores a stored value that is not a number", () => {
    localStorage.setItem("dt.reader.annotationWidth", "wide");
    const { result } = renderHook(() => useAnnotationPanelWidth());
    expect(result.current.width).toBe(ANNOTATION_DEFAULT);
  });
});
