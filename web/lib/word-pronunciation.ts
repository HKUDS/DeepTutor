export type WordPronunciationAccent = "en-US" | "en-GB";

export interface WordPronunciationOptions {
  rate?: number;
  pitch?: number;
  volume?: number;
  onStart?: () => void;
  onEnd?: () => void;
  onError?: (error: Error | string) => void;
}

export interface PronunciationPlaybackState {
  isPlaying: boolean;
  word: string | null;
  accent: WordPronunciationAccent | null;
}

const DEFAULT_RATE = 0.92;
const DEFAULT_VOLUME = 1.0;

let currentAudio: HTMLAudioElement | null = null;
let currentUtterance: SpeechSynthesisUtterance | null = null;
// Keep strong references to active utterances to prevent Safari iOS GC mid-speech
const activeUtterances = new Set<SpeechSynthesisUtterance>();

let currentState: PronunciationPlaybackState = {
  isPlaying: false,
  word: null,
  accent: null,
};

const stateListeners = new Set<(state: PronunciationPlaybackState) => void>();

function notifyStateChange(nextState: PronunciationPlaybackState): void {
  currentState = { ...nextState };
  for (const listener of stateListeners) {
    try {
      listener(currentState);
    } catch {
      // Ignore listener errors
    }
  }
}

export function subscribePronunciationState(
  listener: (state: PronunciationPlaybackState) => void,
): () => void {
  stateListeners.add(listener);
  listener(currentState);
  return () => {
    stateListeners.delete(listener);
  };
}

export function getPronunciationState(): PronunciationPlaybackState {
  return { ...currentState };
}

export function isPronouncingWord(
  word: string,
  accent?: WordPronunciationAccent,
): boolean {
  if (!currentState.isPlaying || !currentState.word) return false;
  const matchWord = currentState.word.toLowerCase() === word.trim().toLowerCase();
  return accent ? matchWord && currentState.accent === accent : matchWord;
}

/** Check whether audio pronunciation is supported in the current environment. */
export function wordPronunciationSupported(): boolean {
  if (typeof window === "undefined") return false;
  const hasSpeech = typeof window.speechSynthesis !== "undefined";
  return hasSpeech;
}

export function preloadWordAudio(
  word: string,
  accent: WordPronunciationAccent = "en-US",
): void {
  if (typeof window === "undefined" || !window.speechSynthesis) return;
  try {
    window.speechSynthesis.getVoices();
  } catch {
    // Ignore pre-warm failures.
  }
}

export function stopPronunciation(): void {
  if (currentAudio) {
    try {
      currentAudio.pause();
      currentAudio.currentTime = 0;
    } catch {
      // Ignore pause failures
    }
    currentAudio = null;
  }
  if (typeof window !== "undefined" && window.speechSynthesis) {
    try {
      window.speechSynthesis.cancel();
    } catch {
      // Ignore cancel failures
    }
  }
  activeUtterances.clear();
  currentUtterance = null;
  if (currentState.isPlaying) {
    notifyStateChange({ isPlaying: false, word: null, accent: null });
  }
}

/** Play speech synthesis fallback with voice optimization for iOS Safari and desktop. */
function speakWithSpeechSynthesis(
  cleanWord: string,
  accent: WordPronunciationAccent,
  options: WordPronunciationOptions = {},
): Promise<boolean> {
  return new Promise((resolve) => {
    if (typeof window === "undefined" || !window.speechSynthesis) {
      resolve(false);
      return;
    }

    const synthesis = window.speechSynthesis;
    try {
      synthesis.cancel();
      // iOS Safari bug fix: resume paused speech synthesis
      if (synthesis.paused) synthesis.resume();
    } catch {
      // Ignore
    }

    const utterance = new SpeechSynthesisUtterance(cleanWord);
    utterance.lang = accent;
    utterance.rate = options.rate ?? DEFAULT_RATE;
    utterance.volume = options.volume ?? DEFAULT_VOLUME;
    if (options.pitch != null) utterance.pitch = options.pitch;

    const voices = synthesis.getVoices();
    if (voices && voices.length > 0) {
      const prefix = accent.toLowerCase().replace("_", "-");
      const matched = voices.filter((v) =>
        v.lang.toLowerCase().replace("_", "-").startsWith(prefix),
      );
      // Prefer natural/local service voices on iOS / macOS
      const preferred =
        matched.find((v) => v.localService && !v.name.includes("Bad")) ??
        matched.find((v) => /natural|siri|samantha|daniel|alex|enhanced/i.test(v.name)) ??
        matched[0] ??
        voices.find((v) => v.lang.toLowerCase().startsWith("en")) ??
        voices[0];
      if (preferred) utterance.voice = preferred;
    }

    currentUtterance = utterance;
    activeUtterances.add(utterance);

    utterance.onstart = () => {
      notifyStateChange({ isPlaying: true, word: cleanWord, accent });
      options.onStart?.();
    };

    utterance.onend = () => {
      activeUtterances.delete(utterance);
      if (currentUtterance === utterance) currentUtterance = null;
      notifyStateChange({ isPlaying: false, word: null, accent: null });
      options.onEnd?.();
      resolve(true);
    };

    utterance.onerror = (event) => {
      activeUtterances.delete(utterance);
      if (currentUtterance === utterance) currentUtterance = null;
      notifyStateChange({ isPlaying: false, word: null, accent: null });
      options.onError?.(event.error || "Speech synthesis error");
      resolve(false);
    };

    try {
      synthesis.speak(utterance);
    } catch (err) {
      activeUtterances.delete(utterance);
      currentUtterance = null;
      notifyStateChange({ isPlaying: false, word: null, accent: null });
      options.onError?.(err instanceof Error ? err : String(err));
      resolve(false);
    }
  });
}

/**
 * Play standard pronunciation for a given word.
 * Tries high-quality native audio stream first, falling back to Web Speech API / TTS.
 */
export async function playWordPronunciation(
  word: string,
  accent: WordPronunciationAccent = "en-US",
  options: WordPronunciationOptions = {},
): Promise<boolean> {
  const cleanWord = word.trim().replace(/^[^a-zA-Z0-9]+|[^a-zA-Z0-9]+$/g, "");
  if (!cleanWord) return false;

  stopPronunciation();
  const hasSpeech = typeof window !== "undefined" && window.speechSynthesis;
  if (!hasSpeech) {
    options.onError?.("No local speech engine available. Add/enable a system voice.");
    return false;
  }

  return await speakWithSpeechSynthesis(cleanWord, accent, options);
}

/** Synchronously trigger word pronunciation (returns boolean whether execution started). */
export function speakWord(
  word: string,
  accent: WordPronunciationAccent = "en-US",
  options: WordPronunciationOptions = {},
): boolean {
  if (!wordPronunciationSupported()) return false;
  void playWordPronunciation(word, accent, options);
  return true;
}
