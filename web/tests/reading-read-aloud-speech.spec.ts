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

function installAudio() {
  class FakeAudio {
    onended: (() => void) | null = null;
    onerror: (() => void) | null = null;
    pause = vi.fn();
    play = vi.fn().mockResolvedValue(undefined);

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
