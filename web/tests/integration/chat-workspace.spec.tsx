import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const source = (relative: string) =>
  fs.readFileSync(path.resolve(process.cwd(), relative), "utf8");

describe("chat workspace composition", () => {
  it("keeps the route as a small composition boundary", () => {
    const route = [
      source("app/(workspace)/chat/page.tsx"),
      source("app/(workspace)/chat/[sessionId]/page.tsx"),
    ].join("\n");
    expect(route).toMatch(/<ChatWorkspace/);
    expect(route).not.toMatch(
      /apiFetch|localStorage|useState|useEffect|modal/i,
    );
    expect(route.split("\n").length).toBeLessThan(20);
  });

  it("moves session resolution behind its route controller", () => {
    const workspace = source("features/chat/components/ChatWorkspace.tsx");
    expect(workspace).toMatch(/useChatRouteSession/);
    expect(workspace).not.toMatch(/useParams|useRouter/);
  });
});
