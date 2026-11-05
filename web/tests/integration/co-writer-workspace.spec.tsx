import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const source = (relative: string) =>
  fs.readFileSync(path.resolve(process.cwd(), relative), "utf8");

describe("co-writer workspace boundaries", () => {
  it("keeps the dynamic route as composition only", () => {
    const route = source("app/(workspace)/co-writer/[docId]/page.tsx");
    expect(route).toMatch(/<NoteWorkspace[^>]*docId=/);
    expect(route).not.toMatch(/apiFetch|localStorage|useState|useEffect/);
    expect(route.split("\n").length).toBeLessThan(20);
  });

  it("uses revisioned blocks and scoped recovery", () => {
    const workspace = source("features/notes/components/NoteWorkspace.tsx");
    expect(workspace).toMatch(/reviewSuggestion/);
    expect(workspace).toMatch(/expected_revision/);
    expect(workspace).toMatch(/persistDraft/);
    expect(workspace).not.toMatch(/\.localStorage\.(?:getItem|setItem|removeItem)/);
  });
});
