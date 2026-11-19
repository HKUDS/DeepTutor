import { render, waitFor } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";

import CodeEditor from "@/components/code/CodeEditor";

beforeAll(() => {
  Object.defineProperty(Range.prototype, "getClientRects", {
    configurable: true,
    value: () => [] as unknown as DOMRectList,
  });
  Object.defineProperty(Range.prototype, "getBoundingClientRect", {
    configurable: true,
    value: () => new DOMRect(),
  });
});

describe("CodeEditor", () => {
  it("mounts a CodeMirror view with the initial document", async () => {
    render(
      <CodeEditor
        value="print(1)"
        language="python"
        onChange={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(document.querySelector(".cm-editor")).toBeTruthy();
      expect(document.querySelector(".cm-content")?.textContent).toContain("print(1)");
    });
  });
});
