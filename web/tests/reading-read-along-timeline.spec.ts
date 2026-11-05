import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useReadAloudSpeech } from "@/components/reading/use-read-aloud-speech";
import { readReadingAloudTimed } from "@/lib/reading-api";

vi.mock("@/lib/reading-api", () => ({
  readReadingAloudAudio: vi.fn(),
  readReadingAloudTimed: vi.fn(),
}));

type FakeAudio = {
  currentTime: number;
  duration: number;
  readyState: number;
  onended: (() => void) | null;
  onerror: (() => void) | null;
  ontimeupdate: (() => void) | null;
  onloadedmetadata: (() => void) | null;
  pause: ReturnType<typeof vi.fn>;
  play: ReturnType<typeof vi.fn>;
};

let instances: FakeAudio[] = [];

function installAudio({ duration = 4, readyState = 4 } = {}) {
  instances = [];
  class AudioStub implements Partial<FakeAudio> {
    currentTime = 0;
    duration = duration;
    readyState = readyState;
    onended: (() => void) | null = null;
    onerror: (() => void) | null = null;
    ontimeupdate: (() => void) | null = null;
    onloadedmetadata: (() => void) | null = null;
    pause = vi.fn();
    play = vi.fn(() => Promise.resolve());
    constructor() {
      instances.push(this as unknown as FakeAudio);
    }
  }
  vi.stubGlobal("Audio", AudioStub);
  vi.stubGlobal("URL", { ...URL, createObjectURL: () => "blob:x", revokeObjectURL: vi.fn() });
}

const WORDS = [
  { word: "Alpha", start: 0.0, duration: 0.5 },
  { word: "bravo", start: 0.5, duration: 0.5 },
  { word: "charlie", start: 1.0, duration: 0.5 },
  { word: "delta", start: 1.5, duration: 0.5 },
];

function seek(audio: FakeAudio, time: number) {
  audio.currentTime = time;
  audio.ontimeupdate?.();
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useReadAloudSpeech word timeline", () => {
  it("asks for timings and reports the word being spoken", async () => {
    installAudio();
    vi.mocked(readReadingAloudTimed).mockResolvedValue({
      audio: new Blob(["audio"]),
      words: WORDS,
      timed: true,
    });

    const { result } = renderHook(() => useReadAloudSpeech());
    await act(async () => {
      await result.current.speak({
        materialId: "m1",
        locator: 2,
        locale: "en",
        fallbackText: "Alpha bravo charlie delta",
        timed: true,
      });
    });

    expect(readReadingAloudTimed).toHaveBeenCalledWith("m1", { locator: 2 });
    expect(result.current.timeline).toHaveLength(4);
    expect(result.current.activeWord).toBe(0);

    const audio = instances[0];
    act(() => seek(audio, 0.6));
    expect(result.current.activeWord).toBe(1);
    act(() => seek(audio, 1.4));
    expect(result.current.activeWord).toBe(2);
    act(() => seek(audio, 3.9));
    expect(result.current.activeWord).toBe(3);
  });

  it("estimates a timeline when the voice reports no boundaries", async () => {
    installAudio({ duration: 8 });
    vi.mocked(readReadingAloudTimed).mockResolvedValue({
      audio: new Blob(["audio"]),
      words: [],
      timed: false,
    });

    const { result } = renderHook(() => useReadAloudSpeech());
    await act(async () => {
      await result.current.speak({
        materialId: "m1",
        locator: 2,
        locale: "en",
        fallbackText: "one two three four",
        timed: true,
      });
    });

    // Falls back to the duration, not to nothing.
    expect(result.current.timeline).toHaveLength(4);
    expect(result.current.timeline[0].start).toBe(0);
    expect(result.current.timeline[3].start).toBeGreaterThan(0);
  });

  it("clears the highlight on stop", async () => {
    installAudio();
    vi.mocked(readReadingAloudTimed).mockResolvedValue({
      audio: new Blob(["audio"]),
      words: WORDS,
      timed: true,
    });

    const { result } = renderHook(() => useReadAloudSpeech());
    await act(async () => {
      await result.current.speak({
        materialId: "m1",
        locator: 2,
        locale: "en",
        fallbackText: "Alpha bravo charlie delta",
        timed: true,
      });
    });
    act(() => result.current.stop());

    expect(result.current.activeWord).toBe(-1);
    expect(result.current.timeline).toHaveLength(0);
    expect(result.current.speaking).toBe(false);
  });
});
