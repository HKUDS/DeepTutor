import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const source = (relative: string) =>
  fs.readFileSync(path.resolve(process.cwd(), relative), "utf8");

describe("co-writer workspace boundaries", () => {
  it("keeps the dynamic route as composition only", () => {
    const route = source("app/(workspace)/co-writer/[docId]/page.tsx");
    expect(route).toMatch(/<CoWriterWorkspace docId=/);
    expect(route).not.toMatch(/apiFetch|localStorage|useState|useEffect/);
    expect(route.split("\n").length).toBeLessThan(20);
  });

  it("delegates storage, selection cancellation, split panes, and scroll lifecycle", () => {
    const workspace = source(
      "features/co-writer/components/CoWriterWorkspace.tsx",
    );
    expect(workspace).toMatch(/useSelectionEdit\(\)/);
    expect(workspace).toMatch(/useDocumentLifecycle\(\)/);
    expect(workspace).toMatch(/useSplitPane\(splitContainerRef\)/);
    expect(workspace).toMatch(/useSynchronizedScroll\(\)/);
    expect(workspace).toMatch(/saveDraft/);
    expect(workspace).not.toMatch(
      /\.localStorage\.(?:getItem|setItem|removeItem)/,
    );
  });
});
