import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * The phone sign-in card (Phase 2, D-005).
 *
 * Behaviour is what is under test here, not markup: which request is made, what
 * happens to the resend button while the server says wait, and where the user
 * lands afterwards. The card is the only place a phone user meets the product,
 * so a regression here is a regression in the front door.
 *
 * `window.location.assign` is the one thing that cannot be observed through
 * React, because a real assignment would tear down the test page. It is
 * replaced with a recorder; everything else runs for real.
 */

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts && "seconds" in opts ? `${key}:${opts.seconds}` : key,
    i18n: { language: "fa" },
  }),
}));

const assign = vi.fn();

beforeEach(() => {
  assign.mockReset();
  Object.defineProperty(window, "location", {
    value: { ...window.location, assign },
    writable: true,
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

/** One stubbed HTTP answer. `body` is the parsed JSON the endpoint returns. */
interface StubResponse {
  ok?: boolean;
  status?: number;
  headers?: Record<string, string>;
  body?: unknown;
}

/** Build a fetch stub that answers in order, like the real endpoints would. */
function stubFetch(...responses: StubResponse[]) {
  const fn = vi.fn();
  for (const response of responses) {
    fn.mockResolvedValueOnce({
      ok: response.ok ?? true,
      status: response.status ?? 200,
      headers: new Headers(response.headers ?? {}),
      json: async () => response.body ?? {},
    });
  }
  vi.stubGlobal("fetch", fn);
  return fn;
}

async function openCard() {
  const { LoginPhone } = await import("@/components/auth/LoginPhone");
  render(<LoginPhone />);
}

describe("phone entry", () => {
  it("asks for a phone number before anything else", async () => {
    await openCard();
    expect(screen.getByLabelText("Phone number")).toBeTruthy();
    expect(screen.queryByLabelText("Verification code")).toBeNull();
  });

  it("keeps the submit button disabled until a number is typed", async () => {
    await openCard();
    const button = screen.getByRole("button", { name: "Send code" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);

    fireEvent.change(screen.getByLabelText("Phone number"), {
      target: { value: "09123456789" },
    });
    expect(button.disabled).toBe(false);
  });

  it("posts the number and moves to the code step", async () => {
    const fetchStub = stubFetch({
      body: { ok: true, expires_in: 120, resend_in: 60 },
    });
    await openCard();

    fireEvent.change(screen.getByLabelText("Phone number"), {
      target: { value: "09123456789" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send code" }));

    await waitFor(() => expect(fetchStub).toHaveBeenCalled());

    const [url, init] = fetchStub.mock.calls[0];
    expect(String(url)).toContain("/api/auth/otp/request");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ phone: "09123456789" });

    expect(await screen.findByLabelText("Verification code")).toBeTruthy();
  });

  it("shows the server's refusal instead of pretending it sent", async () => {
    stubFetch({
      ok: false,
      status: 400,
      body: { detail: "That does not look like a valid phone number." },
    });
    await openCard();

    fireEvent.change(screen.getByLabelText("Phone number"), {
      target: { value: "not-a-phone" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send code" }));

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toContain(
      "That does not look like a valid phone number.",
    );
    // Still on step one: a failed request must not advance the card.
    expect(screen.queryByLabelText("Verification code")).toBeNull();
  });
});

describe("code entry", () => {
  async function reachCodeStep() {
    stubFetch({ body: { ok: true, expires_in: 120, resend_in: 60 } });
    await openCard();
    fireEvent.change(screen.getByLabelText("Phone number"), {
      target: { value: "09123456789" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send code" }));
    await screen.findByLabelText("Verification code");
  }

  it("strips anything that is not a digit from the code", async () => {
    await reachCodeStep();
    const input = screen.getByLabelText("Verification code") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "12a3-45" } });
    expect(input.value).toBe("12345");
  });

  it("signs in and navigates when the code is accepted", async () => {
    await reachCodeStep();
    stubFetch({ body: { ok: true, is_admin: false } });

    fireEvent.change(screen.getByLabelText("Verification code"), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => expect(assign).toHaveBeenCalledWith("/"));
  });

  it("sends an administrator to the admin panel, not the app", async () => {
    await reachCodeStep();
    stubFetch({ body: { ok: true, is_admin: true } });

    fireEvent.change(screen.getByLabelText("Verification code"), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => expect(assign).toHaveBeenCalledWith("/admin"));
  });

  it("clears the code and reports a rejection", async () => {
    await reachCodeStep();
    stubFetch({ ok: false, status: 401, body: { detail: "The code is incorrect or has expired." } });

    const input = screen.getByLabelText("Verification code") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "999999" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toBeTruthy();
    // The wrong code is gone, so the next attempt starts clean.
    await waitFor(() => expect(input.value).toBe(""));
    expect(assign).not.toHaveBeenCalled();
  });

  it("disables resend while the server's cooldown runs", async () => {
    await reachCodeStep();
    const resend = screen.getByRole("button", { name: /Resend in .*60/ }) as HTMLButtonElement;
    expect(resend.disabled).toBe(true);
  });

  it("lets the user go back and correct the number", async () => {
    await reachCodeStep();
    fireEvent.click(screen.getByRole("button", { name: "Change number" }));
    expect(await screen.findByLabelText("Phone number")).toBeTruthy();
    expect(screen.queryByLabelText("Verification code")).toBeNull();
  });
});
