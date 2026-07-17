"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import { apiFetch, apiUrl } from "@/lib/api";

export type VoiceTutorState = "idle" | "listening" | "thinking" | "speaking";

// TypeScript için Web Speech API tiplerini tanımlıyoruz
declare global {
  interface Window {
    SpeechRecognition: typeof SpeechRecognition;
    webkitSpeechRecognition: typeof SpeechRecognition;
  }
}

export function useVoiceTutor(
  onSendMessage: ((text: string) => void) | undefined
) {
  const [tutorState, setTutorState] = useState<VoiceTutorState>("idle");
  const recognitionRef = useRef<SpeechRecognition | null>(null);
  // speakResponse içinde startListening'i çağırabilmek için ref kullanıyoruz
  const startListeningRef = useRef<() => void>(() => {});

  const startListening = useCallback(() => {
    const SpeechRecognitionClass =
      window.SpeechRecognition || window.webkitSpeechRecognition;

    if (!SpeechRecognitionClass) {
      console.error("Web Speech API this browser does not support.");
      return;
    }

    // Önceki oturumu temizle
    if (recognitionRef.current) {
      recognitionRef.current.onresult = null;
      recognitionRef.current.onend = null;
      recognitionRef.current.onerror = null;
      try { recognitionRef.current.abort(); } catch {}
    }

    const recognition = new SpeechRecognitionClass();
    recognition.continuous = false;       // Bir cümle bitince otomatik durur
    recognition.interimResults = false;   // Sadece nihai sonuçları al
    recognition.lang = "tr-TR";           // Türkçe — gerekirse "en-US" yap

    recognition.onresult = (event: SpeechRecognitionEvent) => {
      const transcript = event.results[0]?.[0]?.transcript?.trim();
      if (transcript && onSendMessage) {
        setTutorState("thinking");
        onSendMessage(transcript);
      }
    };

    recognition.onend = () => {
      // Eğer hala "listening" modundaysak (konuşma algılanmadı), yeniden başlat
      setTutorState((prev) => {
        if (prev === "listening") {
          // Kısa bir gecikme ile yeniden başlat
          setTimeout(() => startListeningRef.current(), 300);
        }
        return prev;
      });
    };

    recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
      console.error("Speech recognition error:", event.error);
      if (event.error === "no-speech") {
        // Konuşma algılanmadı, tekrar dinle
        setTimeout(() => startListeningRef.current(), 300);
      } else {
        setTutorState("idle");
      }
    };

    recognitionRef.current = recognition;
    setTutorState("listening");
    recognition.start();
  }, [onSendMessage]);

  // ref'i her zaman güncel tut
  useEffect(() => {
    startListeningRef.current = startListening;
  }, [startListening]);

  const stopListening = useCallback(() => {
    try {
      recognitionRef.current?.abort();
    } catch {}
    setTutorState("idle");
  }, []);

  const speakResponse = useCallback(
    async (text: string) => {
      setTutorState("speaking");
      try {
        const response = await apiFetch(apiUrl("/api/v1/voice/tts"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text }),
        });
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);
        audio.onended = () => {
          URL.revokeObjectURL(url);
          startListeningRef.current(); // AI bitince tekrar dinle
        };
        audio.onerror = () => {
          URL.revokeObjectURL(url);
          startListeningRef.current();
        };
        audio.play();
      } catch (err) {
        console.error("TTS error:", err);
        startListeningRef.current(); // Hata olsa da tekrar dinle
      }
    },
    []
  );

  // Bileşen unmount olunca temizle
  useEffect(() => {
    return () => {
      try { recognitionRef.current?.abort(); } catch {}
    };
  }, []);

  return {
    tutorState,
    startListening,
    stopListening,
    speakResponse,
  };
}
