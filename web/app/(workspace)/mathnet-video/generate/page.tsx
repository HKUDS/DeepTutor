"use client";

import { useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { ArrowLeft, Play, Download, Loader2, CheckCircle, AlertCircle } from "lucide-react";

interface ProblemDetail {
  problem: {
    id: string;
    problem_markdown: string;
    country: string;
    competition: string;
  };
  architecture: {
    solution_strategy_zh: string;
    step_count: number;
  } | null;
  steps: Array<{
    step_index: number;
    title_zh: string;
    text_zh: string;
  }>;
}

interface GenerationStatus {
  status: string;
  video_url: string | null;
  duration_seconds: number;
  generation_time_seconds: number;
}

export default function GenerateVideoPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const problemId = searchParams.get("problem");

  const [problem, setProblem] = useState<ProblemDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [status, setStatus] = useState<GenerationStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    if (problemId) {
      fetchProblemDetail();
    }
  }, [problemId]);

  const fetchProblemDetail = async () => {
    try {
      const res = await fetch(`/api/v1/mathnet/problem/${problemId}`);
      if (!res.ok) throw new Error("Failed to fetch problem");
      const data = await res.json();
      setProblem(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  };

  const handleGenerate = async () => {
    if (!problemId) return;

    setGenerating(true);
    setProgress(0);

    // Simulate progress
    const progressInterval = setInterval(() => {
      setProgress(p => Math.min(p + 10, 90));
    }, 2000);

    try {
      const res = await fetch("/api/v1/mathnet-video/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          problem_id: problemId,
          tts_provider: "edge",
          quality: "medium",
        }),
      });

      clearInterval(progressInterval);
      setProgress(100);

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Generation failed");
      }

      const data = await res.json();
      setStatus(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Generation failed");
    } finally {
      setGenerating(false);
      clearInterval(progressInterval);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-[var(--background)] flex items-center justify-center">
        <Loader2 className="w-8 h-8 animate-spin text-[var(--primary)]" />
      </div>
    );
  }

  if (!problemId) {
    return (
      <div className="min-h-screen bg-[var(--background)] flex items-center justify-center">
        <div className="text-center">
          <AlertCircle className="w-12 h-12 text-red-500 mx-auto mb-4" />
          <p className="text-[var(--muted-foreground)]">请选择一道题目</p>
          <button
            onClick={() => router.push("/mathnet-video")}
            className="mt-4 px-4 py-2 bg-[var(--primary)] text-white rounded-lg"
          >
            返回题库
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[var(--background)]">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="flex items-center gap-4 mb-8">
          <button
            onClick={() => router.push("/mathnet-video")}
            className="p-2 hover:bg-[var(--muted)] rounded-lg transition-colors"
          >
            <ArrowLeft className="w-5 h-5" />
          </button>
          <h1 className="text-2xl font-bold text-[var(--foreground)]">
            生成讲解视频
          </h1>
        </div>

        {problem && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
            {/* Left: Problem Info */}
            <div className="space-y-6">
              <div className="bg-[var(--card)] border border-[var(--border)] rounded-lg p-6">
                <div className="text-sm text-[var(--muted-foreground)] mb-2">
                  #{problem.problem.id} · {problem.problem.country}
                </div>
                <h2 className="text-xl font-semibold text-[var(--foreground)] mb-4">
                  {problem.problem.competition}
                </h2>
                <div className="prose dark:prose-invert max-w-none">
                  <div className="text-[var(--foreground)] whitespace-pre-wrap">
                    {problem.problem.problem_markdown}
                  </div>
                </div>
              </div>

              {problem.architecture && (
                <div className="bg-[var(--card)] border border-[var(--border)] rounded-lg p-6">
                  <h3 className="text-lg font-medium text-[var(--foreground)] mb-3">
                    解题策略
                  </h3>
                  <p className="text-[var(--muted-foreground)]">
                    {problem.architecture.solution_strategy_zh}
                  </p>
                  <div className="mt-4 text-sm text-[var(--muted-foreground)]">
                    共 {problem.architecture.step_count} 个步骤
                  </div>
                </div>
              )}

              {/* Steps Preview */}
              {problem.steps.length > 0 && (
                <div className="bg-[var(--card)] border border-[var(--border)] rounded-lg p-6">
                  <h3 className="text-lg font-medium text-[var(--foreground)] mb-4">
                    解题步骤
                  </h3>
                  <div className="space-y-3">
                    {problem.steps.slice(0, 5).map((step) => (
                      <div
                        key={step.step_index}
                        className="flex items-start gap-3 p-3 bg-[var(--muted)] rounded-lg"
                      >
                        <span className="flex-shrink-0 w-6 h-6 bg-[var(--primary)] text-white rounded-full flex items-center justify-center text-sm">
                          {step.step_index}
                        </span>
                        <div>
                          <div className="font-medium text-[var(--foreground)]">
                            {step.title_zh}
                          </div>
                          <div className="text-sm text-[var(--muted-foreground)] mt-1 line-clamp-2">
                            {step.text_zh}
                          </div>
                        </div>
                      </div>
                    ))}
                    {problem.steps.length > 5 && (
                      <div className="text-center text-sm text-[var(--muted-foreground)]">
                        还有 {problem.steps.length - 5} 个步骤...
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>

            {/* Right: Generation Panel */}
            <div className="space-y-6">
              <div className="bg-[var(--card)] border border-[var(--border)] rounded-lg p-6">
                <h3 className="text-lg font-medium text-[var(--foreground)] mb-4">
                  视频生成
                </h3>

                {error && (
                  <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-4 text-red-700">
                    {error}
                  </div>
                )}

                {!status ? (
                  <div className="space-y-4">
                    <div className="text-sm text-[var(--muted-foreground)]">
                      <p className="mb-2">将生成以下内容：</p>
                      <ul className="list-disc list-inside space-y-1">
                        <li>AI 讲解音频（中文）</li>
                        <li>步骤拆解动画</li>
                        <li>字幕同步显示</li>
                      </ul>
                    </div>

                    {generating ? (
                      <div className="space-y-3">
                        <div className="h-2 bg-[var(--muted)] rounded-full overflow-hidden">
                          <div
                            className="h-full bg-[var(--primary)] transition-all duration-500"
                            style={{ width: `${progress}%` }}
                          />
                        </div>
                        <div className="text-center text-sm text-[var(--muted-foreground)]">
                          {progress < 30 && "正在生成讲解脚本..."}
                          {progress >= 30 && progress < 60 && "正在合成语音..."}
                          {progress >= 60 && progress < 90 && "正在渲染动画..."}
                          {progress >= 90 && "正在合成视频..."}
                        </div>
                      </div>
                    ) : (
                      <button
                        onClick={handleGenerate}
                        className="w-full flex items-center justify-center gap-2 px-6 py-3 bg-[var(--primary)] text-white rounded-lg hover:opacity-90 transition-opacity"
                      >
                        <Play className="w-5 h-5" />
                        开始生成
                      </button>
                    )}
                  </div>
                ) : (
                  <div className="space-y-4">
                    <div className="flex items-center gap-2 text-green-600">
                      <CheckCircle className="w-5 h-5" />
                      <span>生成完成！</span>
                    </div>

                    <div className="text-sm text-[var(--muted-foreground)]">
                      <p>时长：{status.duration_seconds.toFixed(1)} 秒</p>
                      <p>耗时：{status.generation_time_seconds.toFixed(1)} 秒</p>
                    </div>

                    {status.video_url && (
                      <div className="space-y-3">
                        <video
                          src={status.video_url}
                          controls
                          className="w-full rounded-lg"
                        />
                        <a
                          href={status.video_url}
                          download
                          className="flex items-center justify-center gap-2 px-4 py-2 bg-[var(--muted)] text-[var(--foreground)] rounded-lg hover:bg-[var(--muted-foreground)]/20 transition-colors"
                        >
                          <Download className="w-4 h-4" />
                          下载视频
                        </a>
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* Tips */}
              <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 text-sm text-blue-700">
                <p className="font-medium mb-1">提示</p>
                <p>MVP 版本当前生成的是音频 + 测试视频。完整动画版本正在开发中。</p>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
