"use client";

import { useState } from "react";
import { Volume2, VolumeX } from "lucide-react";
import type { KidsLearnResult } from "@/lib/kids-api";
import type { KidsLearningCopy } from "@/lib/kids-learning/learn-language";

interface GuidedLearnModalProps {
  result: KidsLearnResult | null;
  loading: boolean;
  error: string;
  copy: KidsLearningCopy;
  speakingId: string | null;
  onSpeak: (id: string, text: string) => void;
  onClose: () => void;
  onRetry: () => void;
}

const sectionStyle: React.CSSProperties = {
  padding: 14,
  borderRadius: 12,
  border: "1px solid #e2e8f0",
  background: "#f8fafc",
  marginBottom: 12,
  textAlign: "left",
};

const titleRowStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  marginBottom: 8,
};

const titleStyle: React.CSSProperties = {
  fontSize: 16,
  fontWeight: 800,
  color: "#1f2937",
  margin: 0,
  flex: 1,
};

const bodyStyle: React.CSSProperties = {
  fontSize: 16,
  lineHeight: 1.6,
  color: "#374151",
  margin: 0,
};

const speechStyle: React.CSSProperties = {
  width: 36,
  height: 36,
  flexShrink: 0,
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  border: "2px solid #e2e8f0",
  borderRadius: 10,
  background: "white",
  color: "#4338ca",
  cursor: "pointer",
};

const actionStyle: React.CSSProperties = {
  border: "none",
  borderRadius: 12,
  padding: "10px 16px",
  fontSize: 15,
  fontWeight: 700,
  cursor: "pointer",
  color: "#374151",
  background: "#e2e8f0",
};

function SpeechButton({
  id,
  text,
  label,
  stopLabel,
  speakingId,
  onSpeak,
}: {
  id: string;
  text: string;
  label: string;
  stopLabel: string;
  speakingId: string | null;
  onSpeak: (id: string, text: string) => void;
}) {
  return (
    <button
      type="button"
      style={speechStyle}
      title={speakingId === id ? stopLabel : label}
      aria-label={speakingId === id ? stopLabel : label}
      onClick={() => onSpeak(id, text)}
    >
      {speakingId === id ? <VolumeX size={15} /> : <Volume2 size={15} />}
    </button>
  );
}

export function GuidedLearnModal({
  result,
  loading,
  error,
  copy,
  speakingId,
  onSpeak,
  onClose,
  onRetry,
}: GuidedLearnModalProps) {
  const [showHint, setShowHint] = useState(false);
  const [showAnswer, setShowAnswer] = useState(false);

  return (
    <div style={{ textAlign: "left" }}>
      <h2 style={{ fontSize: 24, fontWeight: 800, color: "#1f2937", marginBottom: 16 }}>
        {copy.learn}
      </h2>

      {loading ? (
        <div aria-busy="true" style={{ textAlign: "center", padding: 32 }}>
          <div style={{ fontSize: 40 }}>📖</div>
          <p style={{ fontSize: 18, color: "#4338ca" }}>{copy.learnLoading}</p>
          <div style={{ maxWidth: 220, margin: "16px auto 0", display: "grid", gap: 8 }}>
            <div style={{ height: 14, borderRadius: 7, background: "#e2e8f0" }} />
            <div style={{ height: 14, width: "80%", borderRadius: 7, background: "#e2e8f0" }} />
            <div style={{ height: 14, width: "60%", borderRadius: 7, background: "#e2e8f0" }} />
          </div>
        </div>
      ) : error ? (
        <div style={{ textAlign: "center", padding: 32 }}>
          <p style={{ fontSize: 18, color: "#c53030" }}>{copy.learnError}</p>
          <button type="button" style={actionStyle} onClick={onRetry}>
            {copy.retry}
          </button>
        </div>
      ) : result ? (
        <>
          <section style={sectionStyle}>
            <div style={titleRowStyle}>
              <h3 style={titleStyle}>{copy.pageOverview}</h3>
              <SpeechButton
                id="learn-overview"
                text={result.overview}
                label={copy.readOverview}
                stopLabel={copy.stopOverview}
                speakingId={speakingId}
                onSpeak={onSpeak}
              />
            </div>
            <p style={bodyStyle}>{result.overview}</p>
          </section>

          <section style={sectionStyle}>
            <h3 style={{ ...titleStyle, marginBottom: 10 }}>{copy.keyConcepts}</h3>
            <div style={{ display: "grid", gap: 10 }}>
              {result.concepts.map((concept, index) => (
                <div key={`${concept.term}-${index}`}>
                  <div style={titleRowStyle}>
                    <strong style={{ color: "#1f2937", fontSize: 17 }}>{concept.term}</strong>
                    <SpeechButton
                      id={`learn-concept-${index}`}
                      text={`${concept.term}. ${concept.explanation}${concept.analogy ? ` ${concept.analogy}` : ""}`}
                      label={copy.readConcept}
                      stopLabel={copy.stopConcept}
                      speakingId={speakingId}
                      onSpeak={onSpeak}
                    />
                  </div>
                  <p style={{ ...bodyStyle, fontSize: 15, margin: 0 }}>{concept.explanation}</p>
                  {concept.analogy && (
                    <p style={{ ...bodyStyle, fontSize: 15, margin: "6px 0 0", color: "#4c51bf" }}>
                      {concept.analogy}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </section>

          <section style={{ ...sectionStyle, background: "#fffbeb", borderColor: "#fbd38d" }}>
            <div style={titleRowStyle}>
              <h3 style={titleStyle}>{copy.reflection}</h3>
              <SpeechButton
                id="learn-reflection"
                text={`${result.reflection.prompt}${showHint ? ` ${result.reflection.hint}` : ""}${showAnswer ? ` ${result.reflection.answer}` : ""}`}
                label={copy.readReflection}
                stopLabel={copy.stopReflection}
                speakingId={speakingId}
                onSpeak={onSpeak}
              />
            </div>
            <p style={bodyStyle}>{result.reflection.prompt}</p>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 12 }}>
              <button type="button" style={actionStyle} onClick={() => setShowHint(true)}>
                {copy.showHint}
              </button>
              <button type="button" style={actionStyle} onClick={() => setShowAnswer(true)}>
                {copy.showAnswer}
              </button>
            </div>
            {showHint && (
              <p style={{ ...bodyStyle, marginTop: 10, color: "#4c51bf" }}>{result.reflection.hint}</p>
            )}
            {showAnswer && <p style={bodyStyle}>{result.reflection.answer}</p>}
          </section>
        </>
      ) : (
        <p style={bodyStyle}>{copy.learnError}</p>
      )}
    </div>
  );
}
