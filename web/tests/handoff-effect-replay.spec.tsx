import { render, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import HandoffPage from "@/app/handoff/page";

const runtime = vi.hoisted(() => ({ fetch: vi.fn(), replace: vi.fn() }));
vi.mock("@/lib/api", () => ({ apiFetch: runtime.fetch, apiUrl: (url: string) => url }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: runtime.replace }),
  useSearchParams: () => new URLSearchParams("code=example-code&next=%2Fprofile"),
}));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (value: string) => value }) }));

describe("automatic handoff sign-in", () => {
  it.each([false, true])("completes a code sign-in with strict mode %s", async strict => {
    runtime.replace.mockReset();
    runtime.fetch.mockReset().mockImplementation((url: string) => Promise.resolve(
      new Response(JSON.stringify(url.endsWith("/exchange") ? { ticket: "example-ticket" } : {})),
    ));
    render(<HandoffPage />, { reactStrictMode: strict });
    await waitFor(() => expect(runtime.replace).toHaveBeenCalledWith("/profile"));
    expect(runtime.fetch).toHaveBeenCalledTimes(2);
    expect(JSON.parse(runtime.fetch.mock.calls[0][1].body)).toEqual({ code: "example-code" });
    expect(JSON.parse(runtime.fetch.mock.calls[1][1].body)).toEqual({ ticket: "example-ticket" });
  });

  it("does not exchange the code after unmount before the deferred start", async () => {
    runtime.fetch.mockReset();
    vi.useFakeTimers();
    try {
      const { unmount } = render(<HandoffPage />);
      unmount();
      await vi.runAllTimersAsync();
      expect(runtime.fetch).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });
});
