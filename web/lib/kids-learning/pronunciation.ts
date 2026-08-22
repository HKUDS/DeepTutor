export type KidsSpeechAccent = "en-US" | "en-GB" | "zh-CN";

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
const CHINESE_RATE = 0.95;
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

// Pre-warm browser voices table if available
if (typeof window !== "undefined" && window.speechSynthesis) {
  try {
    window.speechSynthesis.getVoices();
    window.speechSynthesis.onvoiceschanged = () => {
      window.speechSynthesis?.getVoices();
    };
  } catch {
    // Ignore non-standard speech synthesis implementations.
  }
}

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

export function cleanTextForSpeech(text: string): string {
  if (!text) return "";
  return text
    // Strip markdown code fences and inline code
    .replace(/```[\s\S]*?```/g, " 代码示例 ")
    .replace(/`([^`]+)`/g, "$1")
    // Strip markdown headers
    .replace(/^#{1,6}\s+/gm, "")
    // Strip markdown bold / italic
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/\*([^*]+)\*/g, "$1")
    .replace(/__([^_]+)__/g, "$1")
    .replace(/_([^_]+)_/g, "$1")
    // Strip markdown bullet points, numbers and blockquotes
    .replace(/^\s*[-*+]\s+/gm, "")
    .replace(/^\s*\d+\.\s+/gm, "")
    .replace(/^\s*>\s+/gm, "")
    // Strip emojis & decorative symbols that cause robotic pauses
    .replace(/[💡⭐🎉❓🍎🪙🌕🚀⏹🔄✨🔍🔢📖•]/g, "")
    // Strip LaTeX math delimiters
    .replace(/\$([^$]+)\$/g, "$1")
    // Clean up excessive whitespace & line breaks into natural pauses
    .replace(/\n+/g, "，")
    .replace(/\s+/g, " ")
    .trim();
}

export function detectTextLanguage(text: string): "zh-CN" | "en-US" {
  return /[\u4e00-\u9fa5]/.test(text) ? "zh-CN" : "en-US";
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

function selectVoice(synthesis: SpeechSynthesis, lang: string): SpeechSynthesisVoice | null {
  const voices = synthesis.getVoices();
  if (!voices.length) return null;
  const isChinese = lang.startsWith("zh");
  const targetPrefix = isChinese ? "zh" : "en";

  const matching = voices.filter((v) => {
    const vLang = v.lang.toLowerCase().replace("_", "-");
    return vLang.startsWith(targetPrefix);
  });

  if (isChinese) {
    // Select natural, clear Chinese voices across OS/browsers
    const preferredChinese =
      matching.find((v) => /natural|neural/i.test(v.name) && /xiaoxiao|yunxi|yunjian|xiaoyi|zhiwei/i.test(v.name)) ??
      matching.find((v) => /tingting|ting-ting|meijia|yu-shu|sin-ji/i.test(v.name)) ??
      matching.find((v) => /google.*普通话|google.*國語/i.test(v.name)) ??
      matching.find((v) => /natural|enhanced/i.test(v.name)) ??
      matching.find((v) => v.localService && (v.lang.toLowerCase() === "zh-cn" || v.lang.toLowerCase() === "zh_cn")) ??
      matching.find((v) => v.lang.toLowerCase().startsWith("zh-cn")) ??
      matching[0] ??
      voices.find((v) => v.lang.toLowerCase().startsWith("zh")) ??
      null;
    if (preferredChinese) return preferredChinese;
  } else {
    // Select natural, clear English voices
    const preferredEnglish =
      matching.find((v) => /natural|neural/i.test(v.name) && /jenny|guy|aria/i.test(v.name)) ??
      matching.find((v) => /natural|siri|enhanced/i.test(v.name)) ??
      matching.find((v) => /google.*us english|samantha|daniel|alex/i.test(v.name)) ??
      matching.find((v) => v.localService) ??
      matching[0] ??
      voices.find((v) => v.lang.toLowerCase().startsWith("en")) ??
      null;
    if (preferredEnglish) return preferredEnglish;
  }

  return voices.find((v) => v.default) || voices[0] || null;
}

function speakWithWebSpeech(
  text: string,
  lang: KidsSpeechAccent,
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

  const cleaned = cleanTextForSpeech(text);
  if (!cleaned) return false;

  const effectiveLang = detectTextLanguage(cleaned);
  const utterance = new SpeechSynthesisUtterance(cleaned);
  utterance.lang = effectiveLang;
  utterance.rate = effectiveLang.startsWith("zh") ? CHINESE_RATE : DEFAULT_RATE;
  utterance.pitch = 1.0;
  const voice = selectVoice(synthesis, effectiveLang);
  if (voice) utterance.voice = voice;

  currentUtterance = utterance;
  activeUtterances.add(utterance);
  utterance.onstart = () => {
    notify({ isPlaying: true, text: cleaned, accent: effectiveLang });
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
  const isChinese = /[\u4e00-\u9fa5]/.test(clean);
  const accent: KidsSpeechAccent = isChinese ? "zh-CN" : "en-US";

  if (isChinese || !shouldUsePronunciationStream(clean) || typeof window === "undefined" || typeof Audio === "undefined") {
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
