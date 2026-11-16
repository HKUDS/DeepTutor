import { act, cleanup, render, waitFor } from "@testing-library/react";
import { useEffect, useState } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

// A renderer that finishes asynchronously, the way the real one does: it
// re-renders itself after mount (the real one loads math plugins in an effect
// and code/diagram blocks as lazy chunks). Reconciling that re-render against
// the read-along's annotated DOM is what threw
// `NotFoundError: Failed to execute 'removeChild'`.
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: "en" } }),
}));
vi.mock("@/components/common/RichMarkdownRenderer", () => ({
  default: function AsyncBody() {
    const [tick, setTick] = useState(0);
    useEffect(() => {
      const timer = setTimeout(() => setTick(1), 60);
      return () => clearTimeout(timer);
    }, []);
    return (
      <div>
        <p>Recursion needs a base case. Otherwise it never stops.</p>
        <pre>def f(): pass</pre>
        <span data-tick={tick} />
      </div>
    );
  },
}));

import ReadAlongArticle from "@/components/space/learning/ReadAlongArticle";

beforeEach(() => {
  window.HTMLElement.prototype.scrollIntoView = vi.fn();
});
afterEach(cleanup);

it("keeps the annotation when the renderer re-renders itself", async () => {
  const { container } = render(
    <ReadAlongArticle content="x" title="t" onClose={() => {}} />,
  );

  // The body is measured, frozen to HTML, then annotated.
  await waitFor(
    () =>
      expect(container.querySelectorAll(".ra-sentence").length).toBeGreaterThan(
        0,
      ),
    { timeout: 2000 },
  );

  // The renderer keeps re-rendering its own (un-annotated) copy; the annotated,
  // frozen DOM must be untouched by it.
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 300));
  });

  expect(container.querySelectorAll(".ra-sentence").length).toBeGreaterThan(0);
  expect(container.querySelector(".ra-unit[data-kind='code']")).not.toBeNull();
});
