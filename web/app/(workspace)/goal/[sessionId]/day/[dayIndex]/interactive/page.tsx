"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, Send } from "lucide-react";

import {
  askGoalDayInteractiveAssistant,
  generateGoalDayInteractivePage,
} from "@/lib/goal-api";

type ChatMsg = {
  id: string;
  role: "user" | "assistant";
  content: string;
};

export default function GoalDayInteractivePage() {
  const { t } = useTranslation();
  const params = useParams<{ sessionId: string; dayIndex: string }>();
  const sessionId = params.sessionId;
  const dayIndex = Number(params.dayIndex);

  const [html, setHtml] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [messages, setMessages] = useState<ChatMsg[]>([
    {
      id: "assistant-welcome",
      role: "assistant",
      content: "I am your daily learning assistant. Ask me about frequent exam points, knowledge structure, common mistakes, and score-improvement strategies.",
    },
  ]);
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);

  const loadPage = async (force = false) => {
    setLoading(true);
    setError("");
    try {
      const payload = await generateGoalDayInteractivePage(sessionId, dayIndex, { force });
      const data = payload.data as { html?: string };
      setHtml(data.html || "");
    } catch (err) {
      setError(err instanceof Error ? err.message : t("Failed to generate interactive page"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadPage();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, dayIndex]);

  const askAssistant = async () => {
    const text = question.trim();
    if (!text || asking) return;
    const userMsg: ChatMsg = {
      id: `user-${Date.now()}`,
      role: "user",
      content: text,
    };
    setMessages((prev) => [...prev, userMsg]);
    setQuestion("");
    setAsking(true);
    try {
      const payload = await askGoalDayInteractiveAssistant(sessionId, dayIndex, {
        question: text,
      });
      const answer = (payload.data as { answer?: string }).answer || t("No response");
      setMessages((prev) => [
        ...prev,
        {
          id: `assistant-${Date.now()}`,
          role: "assistant",
          content: answer,
        },
      ]);
    } catch (err) {
      const message = err instanceof Error ? err.message : t("Failed to ask interactive assistant");
      setMessages((prev) => [
        ...prev,
        {
          id: `assistant-error-${Date.now()}`,
          role: "assistant",
          content: message,
        },
      ]);
    } finally {
      setAsking(false);
    }
  };

  return (
    <div className="h-screen overflow-y-auto bg-[radial-gradient(circle_at_top_left,_rgba(195,90,44,0.12),_transparent_28%),linear-gradient(180deg,_rgba(255,255,255,0.25),_transparent_40%)] px-6 py-8">
      <div className="mx-auto flex max-w-7xl flex-col gap-5">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-[var(--foreground)]">
              {t("Interactive Lesson")} · {t("Day {{count}}", { count: dayIndex })}
            </h1>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void loadPage(true)}
              className="rounded-xl border px-4 py-2 text-sm text-[var(--muted-foreground)] transition hover:bg-[var(--secondary)]"
            >
              {t("Regenerate Lesson")}
            </button>
            <Link
              href={`/goal/${sessionId}/day/${dayIndex}`}
              className="rounded-xl border px-4 py-2 text-sm text-[var(--muted-foreground)] transition hover:bg-[var(--secondary)]"
            >
              {t("Back to Day Plan")}
            </Link>
          </div>
        </div>

        {loading ? (
          <div className="rounded-2xl border bg-[var(--card)] px-4 py-3 text-sm text-[var(--muted-foreground)]">
            {t("Generating interactive lesson...")}
          </div>
        ) : null}

        {error ? (
          <div className="rounded-2xl border border-[var(--destructive)]/20 bg-[var(--destructive)]/5 px-4 py-3 text-sm text-[var(--destructive)]">
            {error}
          </div>
        ) : null}

        {!loading && !error && html ? (
          <div className="grid h-[78vh] gap-4 lg:grid-cols-[340px_1fr]">
            <aside className="flex h-full flex-col overflow-hidden rounded-2xl border bg-white">
              <div className="border-b px-4 py-3 text-sm font-medium text-[var(--foreground)]">
                {t("Learning Assistant")}
              </div>
              <div className="flex-1 space-y-3 overflow-y-auto p-4">
                {messages.map((msg) => (
                  <div
                    key={msg.id}
                    className={`max-w-[95%] rounded-xl px-3 py-2 text-sm leading-6 ${
                      msg.role === "user"
                        ? "ml-auto bg-[var(--primary)] text-white"
                        : "bg-[var(--secondary)] text-[var(--foreground)]"
                    }`}
                  >
                    {msg.content}
                  </div>
                ))}
              </div>
              <div className="border-t p-3">
                <div className="flex items-center gap-2">
                  <input
                    value={question}
                    onChange={(event) => setQuestion(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && !event.shiftKey) {
                        event.preventDefault();
                        void askAssistant();
                      }
                    }}
                    placeholder={t("Ask about key points, framework, or pitfalls...")}
                    className="flex-1 rounded-xl border px-3 py-2 text-sm outline-none transition focus:border-[var(--ring)] focus:ring-2 focus:ring-[var(--ring)]/10"
                  />
                  <button
                    type="button"
                    onClick={() => void askAssistant()}
                    disabled={!question.trim() || asking}
                    className="rounded-xl bg-[var(--primary)] p-2 text-white transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {asking ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                  </button>
                </div>
              </div>
            </aside>

            <div className="h-full overflow-hidden rounded-2xl border bg-white">
              <iframe
                className="h-full w-full border-0"
                title={t("Interactive Lesson")}
                sandbox="allow-scripts allow-same-origin"
                srcDoc={html}
              />
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
