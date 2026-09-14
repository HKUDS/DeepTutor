"use client";

import { AlertCircle, Loader2, Mic, RotateCcw, Square } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  bookApi,
  type RecitationAttempt,
  type RecitationLineResult,
  type RecitationSummary,
} from "@/lib/book-api";

interface PoetryRecitationLine {
  id: string;
  text: string;
}

interface PoetryRecitationPanelProps {
  bookId: string | null;
  blockId: string;
  lines: PoetryRecitationLine[];
  initialSummary?: RecitationSummary | null;
}

export default function PoetryRecitationPanel({
  bookId,
  blockId,
  lines,
  initialSummary = null,
}: PoetryRecitationPanelProps) {
  const [attempt, setAttempt] = useState<RecitationAttempt | null>(null);
  const [summary, setSummary] = useState<RecitationSummary | null>(initialSummary);
  const [recordingLineIds, setRecordingLineIds] = useState<string[] | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const targetLineIdsRef = useRef<string[]>([]);
  const mountedRef = useRef(true);

  const releaseStream = useCallback(() => {
    for (const track of streamRef.current?.getTracks() ?? []) track.stop();
    streamRef.current = null;
  }, []);

  const submitAudio = useCallback(
    async (audio: Blob, lineIds: string[]) => {
      if (!bookId) return;
      if (!audio.size) {
        setError("没有录到声音，请重试");
        return;
      }
      setSubmitting(true);
      setError("");
      try {
        const result = await bookApi.submitRecitation({
          book_id: bookId,
          block_id: blockId,
          line_ids: lineIds,
          audio,
        });
        if (!mountedRef.current) return;
        setAttempt(result.attempt);
        setSummary(result.summary);
      } catch (caught) {
        if (!mountedRef.current) return;
        setError(caught instanceof Error ? caught.message : "提交失败，请稍后重试");
      } finally {
        if (mountedRef.current) setSubmitting(false);
      }
    },
    [blockId, bookId],
  );

  const startRecording = useCallback(
    async (lineIds: string[]) => {
      if (!bookId) {
        setError("请先打开要练习的书籍");
        return;
      }
      if (!navigator.mediaDevices?.getUserMedia || !("MediaRecorder" in window)) {
        setError("当前浏览器不支持录音，请更换浏览器后重试");
        return;
      }

      setError("");
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        streamRef.current = stream;
        chunksRef.current = [];
        targetLineIdsRef.current = lineIds;
        const recorder = new MediaRecorder(stream);
        recorderRef.current = recorder;
        recorder.ondataavailable = (event) => {
          if (event.data.size) chunksRef.current.push(event.data);
        };
        recorder.onerror = () => {
          recorder.onstop = null;
          releaseStream();
          recorderRef.current = null;
          setRecordingLineIds(null);
          setError("录音中断，请重试");
        };
        recorder.onstop = () => {
          const audio = new Blob(chunksRef.current, {
            type: recorder.mimeType || "audio/webm",
          });
          const targetIds = targetLineIdsRef.current;
          chunksRef.current = [];
          recorderRef.current = null;
          releaseStream();
          if (mountedRef.current) {
            setRecordingLineIds(null);
            void submitAudio(audio, targetIds);
          }
        };
        recorder.start();
        setRecordingLineIds(lineIds);
      } catch {
        releaseStream();
        recorderRef.current = null;
        setRecordingLineIds(null);
        setError("无法使用麦克风，请检查浏览器权限");
      }
    },
    [bookId, releaseStream, submitAudio],
  );

  const stopRecording = useCallback(() => {
    if (recorderRef.current?.state === "recording") recorderRef.current.stop();
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      const recorder = recorderRef.current;
      if (recorder?.state === "recording") {
        recorder.onstop = null;
        recorder.stop();
      }
      releaseStream();
    };
  }, [releaseStream]);

  const allLineIds = lines.map((line) => line.id);
  const isRecording = recordingLineIds !== null;

  return (
    <div className="mt-4 border-t border-[var(--border)]/50 pt-4">
      <div className="flex flex-wrap items-center justify-center gap-2">
        <button
          type="button"
          onClick={() =>
            isRecording ? stopRecording() : void startRecording(allLineIds)
          }
          disabled={submitting || !bookId}
          aria-label={isRecording ? "完成跟读并评分" : "开始跟读"}
          className="inline-flex items-center gap-1.5 rounded-full bg-[var(--primary)] px-3 py-1.5 text-xs font-medium text-[var(--primary-foreground)] transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {submitting ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : isRecording ? (
            <Square className="h-3 w-3 fill-current" />
          ) : (
            <Mic className="h-3.5 w-3.5" />
          )}
          {submitting ? "评分中" : isRecording ? "完成并评分" : "开始跟读"}
        </button>
        {isRecording && (
          <span className="text-xs text-rose-600 dark:text-rose-300" aria-live="polite">
            正在录音…
          </span>
        )}
      </div>

      {summary && summary.attempt_count > 0 && (
        <div className="mt-3 flex flex-wrap justify-center gap-x-4 gap-y-1 text-xs text-[var(--muted-foreground)]">
          <span>练习 {summary.attempt_count} 次</span>
          <span>最近 {formatAccuracy(summary.latest_accuracy)}</span>
          <span>最佳 {formatAccuracy(summary.best_accuracy)}</span>
        </div>
      )}

      {error && (
        <div
          role="alert"
          className="mx-auto mt-3 flex max-w-md items-start gap-2 rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-700 dark:bg-rose-500/10 dark:text-rose-200"
        >
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {attempt?.data_state === "stt_failed" && (
        <div
          className="mx-auto mt-3 max-w-md rounded-lg bg-[var(--background)] px-3 py-2 text-center text-sm text-[var(--muted-foreground)]"
          aria-live="polite"
        >
          <p className="font-medium text-[var(--foreground)]">暂不能评分</p>
          <p className="mt-1 text-xs">语音转写暂不可用，你仍可继续示范朗读和自练。</p>
        </div>
      )}

      {attempt?.data_state === "scored" && (
        <div className="mx-auto mt-4 max-w-md space-y-2" aria-live="polite">
          <p className="text-center text-sm font-medium text-[var(--foreground)]">
            本次文字准确率 {formatAccuracy(attempt.overall_accuracy)}
          </p>
          {attempt.line_results.map((result) => (
            <LineFeedback
              key={result.line_id}
              result={result}
              recording={
                recordingLineIds?.length === 1 &&
                recordingLineIds.includes(result.line_id)
              }
              disabled={submitting || isRecording}
              onRetry={() => void startRecording([result.line_id])}
              onStop={stopRecording}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function LineFeedback({
  result,
  recording,
  disabled,
  onRetry,
  onStop,
}: {
  result: RecitationLineResult;
  recording: boolean;
  disabled: boolean;
  onRetry: () => void;
  onStop: () => void;
}) {
  const tone =
    result.character_accuracy >= 0.9
      ? "border-emerald-300/70 bg-emerald-50 text-emerald-900 dark:border-emerald-500/40 dark:bg-emerald-500/10 dark:text-emerald-100"
      : result.character_accuracy >= 0.6
        ? "border-amber-300/70 bg-amber-50 text-amber-900 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-100"
        : "border-[var(--border)] bg-[var(--background)] text-[var(--foreground)]";

  return (
    <div className={`rounded-xl border px-3 py-2 text-sm ${tone}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-medium">{result.expected_text}</p>
          <p className="mt-0.5 text-xs opacity-75">
            识别：{result.recognized_text || "（未识别到文字）"}
          </p>
          {(result.omissions.length > 0 || result.insertions.length > 0) && (
            <p className="mt-1 text-xs opacity-80">
              {result.omissions.length > 0 &&
                `漏读：${result.omissions.join("、")}`}
              {result.omissions.length > 0 && result.insertions.length > 0 && " · "}
              {result.insertions.length > 0 &&
                `多读：${result.insertions.join("、")}`}
            </p>
          )}
        </div>
        <div className="shrink-0 text-right">
          <p className="text-xs font-semibold">
            {formatAccuracy(result.character_accuracy)}
          </p>
          <button
            type="button"
            onClick={recording ? onStop : onRetry}
            disabled={disabled && !recording}
            className="mt-1 inline-flex items-center gap-1 rounded-md border border-current/30 px-2 py-1 text-[11px] font-medium transition hover:bg-white/40 disabled:cursor-not-allowed disabled:opacity-50 dark:hover:bg-white/10"
          >
            {recording ? (
              <Square className="h-3 w-3 fill-current" />
            ) : (
              <RotateCcw className="h-3 w-3" />
            )}
            {recording ? "完成本句" : "重读本句"}
          </button>
        </div>
      </div>
    </div>
  );
}

function formatAccuracy(value: number | null): string {
  return value === null ? "未评分" : `${Math.round(value * 100)}%`;
}
