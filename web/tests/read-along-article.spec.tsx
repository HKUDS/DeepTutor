import { cleanup, fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "en" },
  }),
}));

// The real renderer pulls in KaTeX, Mermaid and the code theme; this test only
// needs the DOM shape the read-along walks (a paragraph and a code block).
vi.mock("@/components/common/RichMarkdownRenderer", () => ({
  default: () => (
    <div>
      <p>Recursion needs a base case. Otherwise it never stops.</p>
      <pre>def f(): pass</pre>
    </div>
  ),
}));

import ReadAlongArticle from "@/components/space/learning/ReadAlongArticle";

beforeEach(() => {
  // jsdom has no layout; scrollIntoView is called when a unit is focused.
  window.HTMLElement.prototype.scrollIntoView = vi.fn();
});

afterEach(cleanup);

it("tags sentences and code blocks as read-along units", async () => {
  const { container } = render(
    <ReadAlongArticle content="x" title="Recursion" onClose={() => {}} />,
  );
  await waitFor(() =>
    expect(container.querySelectorAll(".ra-sentence").length).toBeGreaterThan(0),
  );
  expect(container.querySelector(".ra-unit[data-kind='code']")).not.toBeNull();
});

it("starts from a clicked sentence and marks a key point on a second click", async () => {
  const { container } = render(
    <ReadAlongArticle content="x" title="Recursion" onClose={() => {}} />,
  );
  const sentence = await waitFor(() => {
    const el = container.querySelector<HTMLElement>(".ra-sentence");
    if (!el) throw new Error("no sentence yet");
    return el;
  });

  fireEvent.click(sentence);
  expect(sentence.classList.contains("ra-active")).toBe(true);

  fireEvent.click(sentence);
  expect(sentence.classList.contains("ra-signal")).toBe(true);
});
