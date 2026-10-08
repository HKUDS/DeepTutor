import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { useAuthStatus } from "@/hooks/useAuthStatus";
import { PRIMARY_NAV_HREFS, navVisibleUnderPolicy } from "@/components/sidebar/nav-entries";
import { fetchAuthStatus } from "@/lib/auth";

vi.mock("@/lib/auth", () => ({ fetchAuthStatus: vi.fn() }));
beforeEach(() => vi.mocked(fetchAuthStatus).mockReset());

it.each([
  [["reading"], ["/learning"]],
  [["books"], ["/learning"]],
  [["chat"], ["/chat", "/learning", "/kanban"]],
  [[], []],
] as [string[], string[]][])("filters the actual nav entries for %j", (allowed, expected) => {
  expect(PRIMARY_NAV_HREFS.filter((href) => navVisibleUnderPolicy(href, allowed))).toEqual(expected);
  expect(navVisibleUnderPolicy("/settings", allowed)).toBe(true);
});

it("keeps the full navigation for accounts without a learning policy", () => {
  expect(PRIMARY_NAV_HREFS.every((href) => navVisibleUnderPolicy(href, null))).toBe(true);
});

it.each([undefined, [], ["reading"]])("loads policy surfaces and mirrors backend defaults for %j", async (surfaces) => {
  vi.mocked(fetchAuthStatus).mockResolvedValue({
    enabled: true,
    authenticated: true,
    role: "user",
    learning_policy: {
      age_band: "13-15", locked_persona: "", allowed_capabilities: [], default_capability: "chat",
      allowed_surfaces: surfaces,
    },
  });
  const { result } = renderHook(() => useAuthStatus());
  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(result.current.learningPolicy?.allowedSurfaces).toEqual(surfaces?.length ? surfaces : ["chat", "reading"]);
});
