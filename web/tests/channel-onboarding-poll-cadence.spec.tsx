import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import ChannelOnboardingPanel from "@/components/partners/ChannelOnboardingPanel";
import { applyChannelOnboarding, getChannelOnboarding, startChannelOnboarding, type PartnerChannelOnboardingSession } from "@/lib/partners-api";

const { t } = vi.hoisted(() => ({ t: (key: string) => key }));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t }) }));
vi.mock("@/lib/partners-api", () => ({ startChannelOnboarding: vi.fn(), getChannelOnboarding: vi.fn(), applyChannelOnboarding: vi.fn(), cancelChannelOnboarding: vi.fn() }));
afterEach(() => { cleanup(); vi.useRealTimers(); vi.resetAllMocks(); });

const session: PartnerChannelOnboardingSession = {
  session_id: "scan", partner_id: "partner", channel: "feishu", status: "pending_scan",
  qr_payload: "scan-code", qr_data_url: null, fallback_url: "https://example.com/scan",
  poll_interval_seconds: 5, expires_at: "2030-01-01T00:00:00Z",
};

async function startPanel() {
  vi.useFakeTimers();
  vi.mocked(startChannelOnboarding).mockResolvedValue(session);
  const callbacks = { onApplied: vi.fn(), onToast: vi.fn() };
  const view = render(<ChannelOnboardingPanel partnerId="partner" channel="feishu" {...callbacks} />);
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Start" })));
  return { view, ...callbacks };
}

it("waits for the advertised interval after a pending-scan response", async () => {
  vi.mocked(getChannelOnboarding).mockResolvedValueOnce({ ...session }).mockImplementation(() => new Promise(() => undefined));
  await startPanel();
  expect(getChannelOnboarding).toHaveBeenCalledTimes(1);
  await act(async () => vi.advanceTimersByTimeAsync(4_999));
  expect(getChannelOnboarding).toHaveBeenCalledTimes(1);
  await act(async () => vi.advanceTimersByTimeAsync(1));
  expect(getChannelOnboarding).toHaveBeenCalledTimes(2);
});

it("stops polling when the panel unmounts", async () => {
  vi.mocked(getChannelOnboarding).mockImplementation(() => new Promise(() => undefined));
  const { view } = await startPanel();
  expect(getChannelOnboarding).toHaveBeenCalledTimes(1);
  view.unmount();
  await act(async () => vi.advanceTimersByTimeAsync(10_000));
  expect(getChannelOnboarding).toHaveBeenCalledTimes(1);
});

it("applies a ready session once and stops polling after connection", async () => {
  vi.mocked(getChannelOnboarding).mockResolvedValue({ ...session, status: "ready" });
  vi.mocked(applyChannelOnboarding).mockResolvedValue({ session: { ...session, status: "applied" } });
  const { onApplied } = await startPanel();
  expect(applyChannelOnboarding).toHaveBeenCalledTimes(1);
  expect(onApplied).toHaveBeenCalledTimes(1);
  await act(async () => vi.advanceTimersByTimeAsync(10_000));
  expect(getChannelOnboarding).toHaveBeenCalledTimes(1);
});
