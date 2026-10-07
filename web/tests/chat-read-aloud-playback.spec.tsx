import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { PlayAudioButton } from "@/features/chat/messages/ChatMessageList";
import { apiFetch } from "@/lib/api";
import { notify } from "@/lib/notifications";
import { initI18n } from "@/i18n/init";

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  apiFetch: vi.fn(),
}));
vi.mock("@/hooks/useVoiceAutoplay", () => ({
  useVoiceAutoplay: () => ({ autoplayEnabled: false }),
}));
vi.mock("@/lib/notifications", () => ({ notify: vi.fn() }));
initI18n("en");
const instances: FakeAudio[] = [];
class FakeAudio {
  pause = vi.fn();
  play = vi.fn().mockResolvedValue(undefined);
  onended: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor() { instances.push(this); }
}
function installAudio() {
  vi.stubGlobal("Audio", FakeAudio);
  Object.defineProperty(URL, "createObjectURL", { configurable: true, value: vi.fn(() => "blob:test") });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
}
afterEach(() => { vi.unstubAllGlobals(); instances.length = 0; });

it("switches between reply buttons without overlapping speech or a first-click prompt", async () => {
  installAudio();
  vi.mocked(apiFetch).mockResolvedValue({ ok: true, blob: async () => new Blob(["audio"]) } as Response);
  render(<><PlayAudioButton content="First" autoPlayFresh={false} /><PlayAudioButton content="Second" autoPlayFresh={false} /></>);
  const user = userEvent.setup();
  await user.click(screen.getAllByRole("button", { name: "Play aloud" })[0]);
  expect(await screen.findByRole("button", { name: "Stop" })).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Play aloud" }));
  expect(instances).toHaveLength(2);
  expect(instances[0].pause).toHaveBeenCalled();
  expect(instances[1].pause).not.toHaveBeenCalled();
  expect(screen.getAllByRole("button", { name: "Stop" })).toHaveLength(1);
  expect(screen.queryByText(/Automatically read/)).toBeNull();
});

it("does not play a late response body after leaving the chat", async () => {
  installAudio();
  let resolve!: (blob: Blob) => void;
  const body = new Promise<Blob>((yes) => { resolve = yes; });
  vi.mocked(apiFetch).mockResolvedValueOnce({ ok: true, blob: () => body } as Response);
  const { unmount } = render(<PlayAudioButton content="First" autoPlayFresh={false} />);
  await userEvent.setup().click(screen.getByRole("button", { name: "Play aloud" }));
  unmount();
  await act(async () => { resolve(new Blob(["audio"])); });
  expect(instances).toHaveLength(0);
  expect(URL.createObjectURL).not.toHaveBeenCalled();
});

it("does not show a late speech error after playback is cancelled", async () => {
  let resolve!: (body: { detail: string }) => void;
  const body = new Promise<{ detail: string }>((yes) => { resolve = yes; });
  vi.mocked(apiFetch).mockResolvedValueOnce({
    ok: false,
    status: 504,
    json: () => body,
  } as Response);
  render(<PlayAudioButton content="First" autoPlayFresh={false} />);
  const user = userEvent.setup();
  const button = screen.getByRole("button", { name: "Play aloud" });
  await user.click(button);
  await user.click(button);
  await act(async () => { resolve({ detail: "Speech synthesis timed out." }); });
  expect(notify).not.toHaveBeenCalled();
});
