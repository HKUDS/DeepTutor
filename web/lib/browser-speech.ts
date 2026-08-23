let activeUtterance: SpeechSynthesisUtterance | null = null;

export function stopBrowserSpeech(): void {
  activeUtterance = null;
  if (typeof window === "undefined") return;
  window.speechSynthesis?.cancel();
}

export function speakBrowserText(
  text: string,
  locale: string,
  handlers: { onEnd?: () => void; onError?: (message: string) => void } = {},
): boolean {
  if (typeof window === "undefined" || !window.speechSynthesis) return false;
  const clean = text.replace(/\s+/g, " ").trim();
  if (!clean) return false;
  stopBrowserSpeech();
  const utterance = new SpeechSynthesisUtterance(clean);
  utterance.lang = locale || (/\p{Script=Han}/u.test(clean) ? "zh-CN" : "en-US");
  utterance.rate = utterance.lang.startsWith("zh") ? 0.95 : 0.88;
  utterance.onend = () => {
    if (activeUtterance !== utterance) return;
    activeUtterance = null;
    handlers.onEnd?.();
  };
  utterance.onerror = (event) => {
    if (activeUtterance !== utterance) return;
    activeUtterance = null;
    if (event.error !== "canceled" && event.error !== "interrupted") {
      handlers.onError?.(event.error || "Speech playback failed.");
    }
  };
  activeUtterance = utterance;
  window.speechSynthesis.speak(utterance);
  return true;
}
