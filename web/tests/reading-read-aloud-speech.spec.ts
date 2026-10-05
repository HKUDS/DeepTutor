import { act, renderHook } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { useReadAloudSpeech } from "@/components/reading/use-read-aloud-speech";
import { readReadingAloudAudio } from "@/lib/reading-api";

vi.mock("@/lib/reading-api", () => ({
  readReadingAloudAudio: vi.fn(),
}));

const audioInstances: {
  pause: ReturnType<typeof vi.fn>;
  play: ReturnType<typeof vi.fn>;
}[] = [];

function installAudio(play = () => Promise.resolve()) {
  class FakeAudio {
    onended: (() => void) | null = null;
    onerror: (() => void) | null = null;
    pause = vi.fn();
    play = vi.fn(play);

    constructor() {
      audioInstances.push(this);
    }
  }
  vi.stubGlobal("Audio", FakeAudio);
}

function installObjectUrls() {
  const createObjectURL = vi.fn(() => "blob:reading-audio");
  const revokeObjectURL = vi.fn();
  vi.stubGlobal("URL", {
    ...URL,
    createObjectURL,
    revokeObjectURL,
  });
  return { createObjectURL, revokeObjectURL };
}

function installBrowserSpeech() {
  const speechSynthesis = {
    cancel: vi.fn(),
    speak: vi.fn(),
  };
  Object.defineProperty(window, "speechSynthesis", {
    configurable: true,
    writable: true,
    value: speechSynthesis,
  });
  return speechSynthesis;
}

function installSpeechUtterance() {
  vi.stubGlobal(
    "SpeechSynthesisUtterance",
    class {
      lang = "";
      onend: (() => void) | null = null;
      onerror: (() => void) | null = null;
      text = "";

      constructor(text: string) {
        this.text = text;
      }
    },
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  audioInstances.length = 0;
});

it("prefers server audio and sends only the material locator and locale", async () => {
  installAudio();
  installObjectUrls();
  vi.mocked(readReadingAloudAudio).mockResolvedValueOnce({
    size: 5,
  } as Blob);
  const speechSynthesis = installBrowserSpeech();

  const { result } = renderHook(() => useReadAloudSpeech());
  let played = false;
  await act(async () => {
    played = await result.current.speak({
      materialId: "material-1",
      locator: 3,
      locale: "zh-CN",
      fallbackText: "Verified fallback",
    });
  });
  expect(played).toBe(true);

  expect(readReadingAloudAudio).toHaveBeenCalledWith("material-1", { locator: 3 });
  expect(audioInstances).toHaveLength(1);
  expect(audioInstances[0].play).toHaveBeenCalledTimes(1);
  expect(speechSynthesis.speak).not.toHaveBeenCalled();
  expect(result.current.speaking).toBe(true);
});

it("falls back to verified browser speech when server audio fails", async () => {
  installAudio();
  installSpeechUtterance();
  const speechSynthesis = installBrowserSpeech();
  vi.mocked(readReadingAloudAudio).mockRejectedValueOnce(
    new Error("speech provider unavailable"),
  );

  const { result } = renderHook(() => useReadAloudSpeech());
  let played = false;
  await act(async () => {
    played = await result.current.speak({
      materialId: "material-1",
      locator: 2,
      locale: "en",
      fallbackText: "Verified fallback",
    });
  });
  expect(played).toBe(true);

  expect(speechSynthesis.speak).toHaveBeenCalledTimes(1);
  const utterance = vi.mocked(speechSynthesis.speak).mock.calls[0][0];
  expect(utterance.text).toBe("Verified fallback");
  expect(utterance.lang).toBe("en");
  expect(result.current.speaking).toBe(true);
});

it("stops server audio and releases its object URL", async () => {
  installAudio();
  const { revokeObjectURL } = installObjectUrls();
  vi.mocked(readReadingAloudAudio).mockResolvedValueOnce({
    size: 5,
  } as Blob);

  const { result } = renderHook(() => useReadAloudSpeech());
  await act(async () => {
    await result.current.speak({
      materialId: "material-1",
      locator: 1,
      locale: "en",
      fallbackText: "Verified fallback",
    });
  });

  act(() => {
    result.current.stop();
  });

  expect(audioInstances[0].pause).toHaveBeenCalledTimes(1);
  expect(revokeObjectURL).toHaveBeenCalledWith("blob:reading-audio");
  expect(result.current.speaking).toBe(false);
});


it.each(["resolve", "reject"])("keeps newer audio playing when an older play promise later %ss", async (outcome) => {
  let resolve!: () => void;
  let reject!: (error: Error) => void;
  const pending = new Promise<void>((yes, no) => { resolve = yes; reject = no; });
  let plays = 0;
  installAudio(() => ++plays === 1 ? pending : Promise.resolve());
  const { createObjectURL, revokeObjectURL } = installObjectUrls();
  createObjectURL.mockReturnValueOnce("blob:first").mockReturnValueOnce("blob:second");
  vi.mocked(readReadingAloudAudio).mockResolvedValue({ size: 5 } as Blob);
  const speech = installBrowserSpeech();
  const { result } = renderHook(() => useReadAloudSpeech());
  const request = { materialId: "material-1", locator: 1, locale: "en", fallbackText: "fallback" };
  let first!: Promise<boolean>;
  await act(async () => { first = result.current.speak(request); });
  await act(async () => { await result.current.speak({ ...request, locator: 2 }); });
  expect(result.current.speaking).toBe(true);
  await act(async () => {
    if (outcome === "resolve") resolve(); else reject(new Error("late playback failure"));
    await first;
  });
  expect(audioInstances[1].pause).not.toHaveBeenCalled();
  expect(revokeObjectURL).not.toHaveBeenCalledWith("blob:second");
  expect(revokeObjectURL.mock.calls.filter(([url]) => url === "blob:first")).toHaveLength(1);
  expect(speech.speak).not.toHaveBeenCalled();
  expect(result.current.speaking).toBe(true);
});

it("does not start a late server response after unmount", async () => {
  installAudio();
  const { createObjectURL } = installObjectUrls();
  let resolve!: (blob: Blob) => void;
  vi.mocked(readReadingAloudAudio).mockReturnValueOnce(new Promise<Blob>((yes) => { resolve = yes; }));
  const { result, unmount } = renderHook(() => useReadAloudSpeech());
  let pending!: Promise<boolean>;
  await act(async () => { pending = result.current.speak({ materialId: "material-1", locator: 1, locale: "en", fallbackText: "fallback" }); });
  unmount();
  await act(async () => { resolve({ size: 5 } as Blob); await pending; });
  expect(createObjectURL).not.toHaveBeenCalled();
  expect(audioInstances).toHaveLength(0);
});
