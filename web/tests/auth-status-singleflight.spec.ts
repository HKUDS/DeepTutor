import { afterEach, describe, expect, it, vi } from "vitest";

import {
  fetchAuthStatus,
  invalidateAuthStatusCache,
} from "@/lib/auth";

describe("fetchAuthStatus single-flight cache", () => {
  afterEach(() => {
    invalidateAuthStatusCache();
    vi.unstubAllGlobals();
  });

  it("shares concurrent and near-term status reads", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(
        JSON.stringify({
          enabled: true,
          authenticated: true,
          role: "admin",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const [first, second] = await Promise.all([
      fetchAuthStatus(),
      fetchAuthStatus(),
    ]);
    const cached = await fetchAuthStatus();

    expect(first?.role).toBe("admin");
    expect(second).toEqual(first);
    expect(cached).toEqual(first);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("can be invalidated after an auth mutation", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ enabled: false, authenticated: false }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await fetchAuthStatus();
    invalidateAuthStatusCache();
    await fetchAuthStatus();

    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
