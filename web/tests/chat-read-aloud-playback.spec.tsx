import { act, render, renderHook, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { PlayAudioButton } from "@/features/chat/messages/ChatMessageList";
import { useVoicePlaybackRate } from "@/hooks/useVoicePlaybackRate";
import { apiFetch } from "@/lib/api";
import { notify } from "@/lib/notifications";
import { initI18n } from "@/i18n/init";
import { browserStorage } from "@/shared/storage";

const autoplay = vi.hoisted(() => ({ enabled: false }));

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  apiFetch: vi.fn(),
}));
vi.mock("@/hooks/useVoiceAutoplay", () => ({
  useVoiceAutoplay: () => ({ autoplayEnabled: autoplay.enabled }),
}));
vi.mock("@/lib/notifications", () => ({ notify: vi.fn() }));
initI18n("en");
const instances: FakeAudio[] = [];
class FakeAudio {
  src = "";
  playbackRate = 1;
  pause = vi.fn();
  play = vi.fn().mockResolvedValue(undefined);
  load = vi.fn();
  onended: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(src?: string) {
    this.src = src ?? "";
    instances.push(this);
  }
}
function installAudio() {
  vi.stubGlobal("Audio", FakeAudio);
  Object.defineProperty(URL, "createObjectURL", { configurable: true, value: vi.fn(() => "blob:test") });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
}
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); instances.length = 0; autoplay.enabled = false; });

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

it("unlocks the audio element during the click before speech synthesis resolves", async () => {
  installAudio();
  let resolveFetch!: (resp: Response) => void;
  const fetchBody = new Promise<Response>((yes) => { resolveFetch = yes; });
  vi.mocked(apiFetch).mockReturnValueOnce(fetchBody);
  render(<PlayAudioButton content="First" autoPlayFresh={false} />);
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Play aloud" }));

  expect(instances).toHaveLength(1);
  expect(instances[0].play).toHaveBeenCalledTimes(1);
  expect(instances[0].src).toContain("data:audio/wav");
  const bytes = Uint8Array.from(atob(instances[0].src.split(",")[1]), (c) => c.charCodeAt(0));
  const wav = new DataView(bytes.buffer);
  expect(wav.getUint32(40, true)).toBeGreaterThan(0);
  expect(bytes.length).toBe(44 + wav.getUint32(40, true));
  expect(URL.createObjectURL).not.toHaveBeenCalled();

  await act(async () => {
    resolveFetch({ ok: true, blob: async () => new Blob(["audio"]) } as Response);
  });

  expect(await screen.findByRole("button", { name: "Stop" })).toBeVisible();
  expect(instances).toHaveLength(1);
  expect(instances[0].load).toHaveBeenCalled();
  expect(instances[0].play).toHaveBeenCalledTimes(2);
  expect(instances[0].src).toBe("blob:test");
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
  expect(instances).toHaveLength(1);
  expect(instances[0].pause).toHaveBeenCalled();
  expect(URL.createObjectURL).not.toHaveBeenCalled();
});

it("does not show a late speech error after playback is cancelled", async () => {
  installAudio();
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

it("uses the latest rate after synthesis and changes active playback without refetching", async () => {
  installAudio();
  vi.mocked(apiFetch).mockClear();
  let resolve!: (response: Response) => void;
  vi.mocked(apiFetch).mockReturnValueOnce(new Promise<Response>((done) => { resolve = done; }));
  const { rerender } = render(<PlayAudioButton content="Hello" autoPlayFresh={false} />);
  await userEvent.setup().click(screen.getByRole("button", { name: "Play aloud" }));
  rerender(<PlayAudioButton content="Hello" autoPlayFresh={false} playbackRate={1.5} />);
  await act(async () => {
    resolve({ ok: true, blob: async () => new Blob(["audio"]) } as Response);
  });
  expect(instances[0].playbackRate).toBe(1.5);
  rerender(<PlayAudioButton content="Hello" autoPlayFresh={false} playbackRate={0.75} />);
  expect(instances[0].playbackRate).toBe(0.75);
  expect(instances[0].play).toHaveBeenCalledTimes(2);
  expect(apiFetch).toHaveBeenCalledTimes(1);
});

it("restores the rate per conversation and falls back for an invalid rate", () => {
  const { result, rerender, unmount } = renderHook(
    ({ scope }) => useVoicePlaybackRate(scope),
    { initialProps: { scope: "rate-test-a" } },
  );
  act(() => result.current.setRate(1.5));
  rerender({ scope: "rate-test-b" });
  expect(result.current.rate).toBe(1);
  act(() => result.current.setRate(2));
  unmount();
  const restored = renderHook(() => useVoicePlaybackRate("rate-test-a"));
  expect(restored.result.current.rate).toBe(1.5);
  act(() => restored.result.current.setRate(Number.NaN));
  expect(restored.result.current.rate).toBe(1);
});

it("keeps autoplay at the selected rate without restarting when the rate changes", async () => {
  installAudio();
  autoplay.enabled = true;
  vi.mocked(apiFetch).mockClear();
  vi.mocked(apiFetch).mockResolvedValue({ ok: true, blob: async () => new Blob(["audio"]) } as Response);
  const { rerender } = render(<PlayAudioButton content="Hello" autoPlayFresh playbackRate={1.5} />);
  expect(await screen.findByRole("button", { name: "Stop" })).toBeVisible();
  expect(instances[0].playbackRate).toBe(1.5);
  rerender(<PlayAudioButton content="Hello" autoPlayFresh playbackRate={2} />);
  expect(instances[0].playbackRate).toBe(2);
  expect(instances[0].pause).not.toHaveBeenCalled();
  expect(apiFetch).toHaveBeenCalledTimes(1);
});

it("defaults to normal speed for corrupt storage and still changes speed when storage is unavailable", () => {
  vi.spyOn(browserStorage, "readRaw").mockReturnValue("corrupt");
  vi.spyOn(browserStorage, "writeRaw").mockReturnValue(false);
  const { result } = renderHook(() => useVoicePlaybackRate("unavailable-storage"));
  expect(result.current.rate).toBe(1);
  act(() => result.current.setRate(1.25));
  expect(result.current.rate).toBe(1.25);
});

it("keeps an unsaved conversation's speed in memory without persisting it", () => {
  const write = vi.spyOn(browserStorage, "writeRaw");
  const { result, unmount } = renderHook(() => useVoicePlaybackRate());
  act(() => result.current.setRate(0.75));
  expect(result.current.rate).toBe(0.75);
  expect(write).not.toHaveBeenCalled();
  unmount();
  const fresh = renderHook(() => useVoicePlaybackRate());
  expect(fresh.result.current.rate).toBe(1);
});
