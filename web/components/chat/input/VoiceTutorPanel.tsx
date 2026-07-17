"use client";
import React from "react";
import { useVoiceTutor } from "@/hooks/useVoiceTutor";
import { motion } from "framer-motion";
import { Mic, Square, Loader2, Volume2 } from "lucide-react";
import { useEffect, useRef } from "react";
import { useUnifiedChat } from "@/context/UnifiedChatContext";

export default function VoiceTutorPanel({
    onSend,
}: {
    onSend?: (text: string) => void;
}) {
    const { tutorState, startListening, stopListening, speakResponse } = useVoiceTutor(onSend);

    const { state: { isStreaming, messages } } = useUnifiedChat();
    const wasStreamingRef = useRef(false);

    useEffect(() => {
        if (isStreaming) {
            wasStreamingRef.current = true;
        } else if (wasStreamingRef.current && !isStreaming) {
            wasStreamingRef.current = false;
            
            if (tutorState === "thinking") {
                const sonMesaj = messages[messages.length - 1];
                if (sonMesaj && sonMesaj.role === "assistant") {
                    speakResponse(sonMesaj.content);
                } else {
                    // Yapay zeka cevap veremedi veya hata oldu, tekrar dinlemeye başla
                    startListening();
                }
            }
        }
    }, [isStreaming, tutorState, messages, speakResponse, startListening]);


    return (
        <div className="flex flex-col items-center justify-center p-12 bg-white/5 border border-white/10 shadow-2xl backdrop-blur-xl rounded-[26px] w-full max-w-lg mx-auto overflow-hidden relative">
            {/* Arka plan renk cümbüşü (Gradient Glow) */}
            <div className="absolute inset-0 bg-gradient-to-br from-indigo-500/10 via-purple-500/5 to-pink-500/10 pointer-events-none" />

            <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                className="relative z-10 flex flex-col items-center gap-8"
            >
                {/* 1. IDLE (Bekleme) Durumu */}
                {tutorState === "idle" && (
                    <button
                        onClick={startListening}
                        className="group relative flex items-center justify-center w-28 h-28 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-full shadow-[0_0_40px_rgba(99,102,241,0.4)] hover:shadow-[0_0_60px_rgba(99,102,241,0.6)] transition-all duration-300 hover:scale-105"
                    >
                        <Mic size={44} className="text-white drop-shadow-md" />
                    </button>
                )}

                {/* 2. LISTENING (Dinleme) Durumu */}
                {tutorState === "listening" && (
                    <button
                        onClick={stopListening}
                        className="group relative flex items-center justify-center w-28 h-28 bg-red-500/10 border-2 border-red-500/50 rounded-full hover:bg-red-500/20 transition-all duration-300 hover:scale-105"
                    >
                        <span className="absolute w-28 h-28 bg-red-500/30 rounded-full animate-ping" />
                        <Square size={34} className="text-red-500 drop-shadow-md fill-current" />
                    </button>
                )}

                {/* 3. THINKING (Düşünme) Durumu */}
                {tutorState === "thinking" && (
                    <div className="flex items-center justify-center w-28 h-28 rounded-full bg-white/5 border border-white/10 shadow-[0_0_30px_rgba(255,255,255,0.05)]">
                        <Loader2 size={44} className="text-indigo-400 animate-spin" />
                    </div>
                )}

                {/* 4. SPEAKING (Konuşma) Durumu */}
                {tutorState === "speaking" && (
                    <div className="flex items-center justify-center w-28 h-28 rounded-full bg-gradient-to-tr from-emerald-400 to-teal-500 shadow-[0_0_60px_rgba(52,211,153,0.5)] animate-pulse">
                        <Volume2 size={44} className="text-white" />
                    </div>
                )}

                {/* Alt Kısım Yazı (Durum Bildirimi) */}
                <div className="h-8 flex items-center justify-center">
                    {tutorState === "idle" && <p className="text-xl font-medium text-white/80 tracking-wide">Tap to start speaking</p>}
                    {tutorState === "listening" && <p className="text-xl font-medium text-red-400 animate-pulse tracking-wide">Listening to you...</p>}
                    {tutorState === "thinking" && <p className="text-xl font-medium text-indigo-300 tracking-wide">Processing...</p>}
                    {tutorState === "speaking" && <p className="text-xl font-medium text-teal-300 tracking-wide">Tutor is speaking...</p>}
                </div>
            </motion.div>
        </div>
    );
}
