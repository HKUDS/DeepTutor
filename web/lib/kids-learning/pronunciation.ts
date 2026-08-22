export type KidsSpeechAccent = "en-US" | "en-GB";

export interface KidsSpeechPlaybackState {
  isPlaying: boolean;
  text: string | null;
  accent: KidsSpeechAccent | null;
}

interface KidsSpeechHandlers {
  onStart?: () => void;
  onEnd?: () => void;
  onError?: (error: Error | string) => void;
}

const DEFAULT_RATE = 0.88;
const STREAM_WORD_LIMIT = 5;
const STREAM_CHARACTER_LIMIT = 80;

let currentAudio: HTMLAudioElement | null = null;
let currentUtterance: SpeechSynthesisUtterance | null = null;
const activeUtterances = new Set<SpeechSynthesisUtterance>();
const audioCache = new Map<string, HTMLAudioElement>();

let currentState: KidsSpeechPlaybackState = {
  isPlaying: false,
  text: null,
  accent: null,
};
const stateListeners = new Set<(state: KidsSpeechPlaybackState) => void>();

function notify(next: KidsSpeechPlaybackState): void {
  currentState = { ...next };
  for (const listener of stateListeners) {
    try {
      listener(currentState);
    } catch {
      // A UI listener must never interrupt narration.
    }
  }
}

export function subscribeKidsSpeechState(
  listener: (state: KidsSpeechPlaybackState) => void,
): () => void {
  stateListeners.add(listener);
  listener(currentState);
  return () => stateListeners.delete(listener);
}

export function getKidsPronunciationAudioUrl(
  text: string,
  accent: KidsSpeechAccent = "en-US",
): string {
  const clean = text.trim().toLowerCase().replace(/[^a-z0-9'-\s]/g, "").replace(/\s+/g, " ");
  const type = accent === "en-GB" ? 1 : 2;
  return `https://dict.youdao.com/dictvoice?audio=${encodeURIComponent(clean)}&type=${type}`;
}

export function shouldUsePronunciationStream(text: string): boolean {
  const clean = text.trim().replace(/[^a-z0-9'-\s]/gi, "");
  return Boolean(clean) && clean.length <= STREAM_CHARACTER_LIMIT &&
    clean.split(/\s+/).length <= STREAM_WORD_LIMIT;
}

export function stopKidsSpeech(): void {
  if (currentAudio) {
    try {
      currentAudio.pause();
      currentAudio.currentTime = 0;
    } catch {
      // Ignore already-released audio elements.
    }
    currentAudio = null;
  }
  if (typeof window !== "undefined" && window.speechSynthesis) {
    try {
      window.speechSynthesis.cancel();
    } catch {
      // Safari can throw while a voice is being replaced.
    }
  }
  activeUtterances.clear();
  currentUtterance = null;
  if (currentState.isPlaying) notify({ isPlaying: false, text: null, accent: null });
}

function selectVoice(synthesis: SpeechSynthesis, accent: KidsSpeechAccent): SpeechSynthesisVoice | null {
  const voices = synthesis.getVoices();
  if (!voices.length) return null;
  const prefix = accent.toLowerCase();
  const english = voices
    .map((voice) => ({ voice, lang: voice.lang.toLowerCase().replace("_", "-") }))
    .sort((a, b) => a.lang.localeCompare(b.lang));
  const matched = english.filter(({ lang }) => lang.startsWith(prefix));
  const preferred =
    matched.find(({ voice }) => voice.localService && /natural|siri|enhanced/i.test(voice.name)) ??
    matched.find(({ voice }) => voice.localService) ??
    matched.find(({ voice }) => /natural|siri|enhanced|samantha|daniel|alex/i.test(voice.name)) ??
    matched[0] ??
    english.find(({ lang }) => lang.startsWith("en")) ??
    english[0] ??
    null;
  return preferred ? preferred.voice : null;
}

function speakWithWebSpeech(
  text: string,
  accent: KidsSpeechAccent,
  handlers: KidsSpeechHandlers,
): boolean {
  if (typeof window === "undefined" || !window.speechSynthesis) return false;
  const synthesis = window.speechSynthesis;
  try {
    synthesis.cancel();
    if (synthesis.paused) synthesis.resume();
  } catch {
    // Continue with a fresh utterance if cancel is rejected.
  }

  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = accent;
  utterance.rate = DEFAULT_RATE;
  const voice = selectVoice(synthesis, accent);
  if (voice) utterance.voice = voice;

  currentUtterance = utterance;
  activeUtterances.add(utterance);
  utterance.onstart = () => {
    notify({ isPlaying: true, text, accent });
    handlers.onStart?.();
  };
  utterance.onend = () => {
    activeUtterances.delete(utterance);
    if (currentUtterance === utterance) currentUtterance = null;
    notify({ isPlaying: false, text: null, accent: null });
    handlers.onEnd?.();
  };
  utterance.onerror = (event) => {
    activeUtterances.delete(utterance);
    if (currentUtterance === utterance) currentUtterance = null;
    notify({ isPlaying: false, text: null, accent: null });
    handlers.onError?.(event.error || "Speech synthesis error");
  };

  try {
    synthesis.speak(utterance);
    return true;
  } catch (error) {
    activeUtterances.delete(utterance);
    currentUtterance = null;
    handlers.onError?.(error instanceof Error ? error : String(error));
    return false;
  }
}

export function speakKidsText(
  id: string,
  text: string,
  handlers: KidsSpeechHandlers = {},
): boolean {
  const clean = text.trim();
  if (!clean) return false;
  stopKidsSpeech();
  const accent: KidsSpeechAccent = "en-US";

  if (!shouldUsePronunciationStream(clean) || typeof window === "undefined" || typeof Audio === "undefined") {
    return speakWithWebSpeech(clean, accent, handlers);
  }

  const url = getKidsPronunciationAudioUrl(clean, accent);
  let audio = audioCache.get(url);
  if (!audio) {
    audio = new Audio(url);
    audio.preload = "auto";
    audioCache.set(url, audio);
  }

  const settled = { value: false };
  const finish = () => {
    if (settled.value) return;
    settled.value = true;
    if (currentAudio === audio) currentAudio = null;
    notify({ isPlaying: false, text: null, accent: null });
    handlers.onEnd?.();
  };
  const fallback = () => {
    if (settled.value) return;
    settled.value = true;
    if (currentAudio === audio) currentAudio = null;
    audio?.removeEventListener("ended", finish);
    audio?.removeEventListener("error", fallback);
    speakWithWebSpeech(clean, accent, handlers);
  };

  audio.addEventListener("ended", finish, { once: true });
  audio.addEventListener("error", fallback, { once: true });
  currentAudio = audio;
  notify({ isPlaying: true, text: id, accent });
  handlers.onStart?.();

  try {
    audio.currentTime = 0;
    void audio.play().catch(() => fallback());
    return true;
  } catch {
    fallback();
    return speakWithWebSpeech(clean, accent, handlers);
  }
}
