"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { BookOpen, Video, ChevronRight, Search, Filter, Loader2 } from "lucide-react";

interface Problem {
  id: string;
  country: string;
  competition: string;
  topics: string[];
  tier: string | null;
  has_architecture: boolean;
  step_count: number;
}

interface ProblemListResponse {
  total: number;
  page: number;
  page_size: number;
  problems: Problem[];
}

export default function MathNetVideoPage() {
  const router = useRouter();
  const [problems, setProblems] = useState<Problem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState("");
  const [selectedTier, setSelectedTier] = useState<string>("");

  const pageSize = 20;

  useEffect(() => {
    fetchProblems();
  }, [page, selectedTier]);

  const fetchProblems = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      params.append("page", page.toString());
      params.append("page_size", pageSize.toString());
      if (selectedTier) params.append("tier", selectedTier);

      const res = await fetch(`/api/v1/mathnet/problems?${params}`);
      if (!res.ok) throw new Error("Failed to fetch problems");

      const data: ProblemListResponse = await res.json();
      setProblems(data.problems);
      setTotal(data.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  };

  const handleGenerateVideo = (problemId: string) => {
    router.push(`/mathnet-video/generate?problem=${problemId}`);
  };

  const getTierColor = (tier: string | null) => {
    switch (tier) {
      case "L1": return "bg-green-100 text-green-800";
      case "L2": return "bg-blue-100 text-blue-800";
      case "L3": return "bg-orange-100 text-orange-800";
      case "L4": return "bg-red-100 text-red-800";
      default: return "bg-gray-100 text-gray-800";
    }
  };

  const getTierLabel = (tier: string | null) => {
    switch (tier) {
      case "L1": return "基础入门";
      case "L2": return "初级竞赛";
      case "L3": return "中级竞赛";
      case "L4": return "高级竞赛";
      default: return "未分类";
    }
  };

  const totalPages = Math.ceil(total / pageSize);

  return (
    <div className="min-h-screen bg-[var(--background)]">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-[var(--foreground)] mb-2">
            MathNet 视频讲题
          </h1>
          <p className="text-[var(--muted-foreground)]">
            基于 MathNet 竞赛数学题库，AI 自动生成讲解视频
          </p>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
          <div className="bg-[var(--card)] rounded-lg p-4 border border-[var(--border)]">
            <div className="text-2xl font-bold text-[var(--foreground)]">{total.toLocaleString()}</div>
            <div className="text-sm text-[var(--muted-foreground)]">总题目数</div>
          </div>
          <div className="bg-[var(--card)] rounded-lg p-4 border border-[var(--border)]">
            <div className="text-2xl font-bold text-green-600">L1-L2</div>
            <div className="text-sm text-[var(--muted-foreground)]">基础难度</div>
          </div>
          <div className="bg-[var(--card)] rounded-lg p-4 border border-[var(--border)]">
            <div className="text-2xl font-bold text-blue-600">L3</div>
            <div className="text-sm text-[var(--muted-foreground)]">中级难度</div>
          </div>
          <div className="bg-[var(--card)] rounded-lg p-4 border border-[var(--border)]">
            <div className="text-2xl font-bold text-red-600">L4</div>
            <div className="text-sm text-[var(--muted-foreground)]">高级难度</div>
          </div>
        </div>

        {/* Filters */}
        <div className="flex flex-wrap gap-4 mb-6">
          <div className="relative flex-1 min-w-[200px]">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--muted-foreground)]" />
            <input
              type="text"
              placeholder="搜索题目..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full pl-10 pr-4 py-2 bg-[var(--card)] border border-[var(--border)] rounded-lg text-[var(--foreground)] placeholder:text-[var(--muted-foreground)] focus:outline-none focus:ring-2 focus:ring-[var(--ring)]"
            />
          </div>
          <select
            value={selectedTier}
            onChange={(e) => setSelectedTier(e.target.value)}
            className="px-4 py-2 bg-[var(--card)] border border-[var(--border)] rounded-lg text-[var(--foreground)] focus:outline-none focus:ring-2 focus:ring-[var(--ring)]"
          >
            <option value="">所有难度</option>
            <option value="L1">基础入门</option>
            <option value="L2">初级竞赛</option>
            <option value="L3">中级竞赛</option>
            <option value="L4">高级竞赛</option>
          </select>
        </div>

        {/* Error */}
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-6 text-red-700">
            {error}
          </div>
        )}

        {/* Loading */}
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="w-8 h-8 animate-spin text-[var(--primary)]" />
            <span className="ml-3 text-[var(--muted-foreground)]">加载中...</span>
          </div>
        ) : (
          <>
            {/* Problem List */}
            <div className="space-y-3">
              {problems.map((problem) => (
                <div
                  key={problem.id}
                  className="bg-[var(--card)] border border-[var(--border)] rounded-lg p-4 hover:shadow-md transition-shadow"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-2">
                        <span className="text-sm font-mono text-[var(--muted-foreground)]">
                          #{problem.id}
                        </span>
                        <span className={`text-xs px-2 py-0.5 rounded-full ${getTierColor(problem.tier)}`}>
                          {getTierLabel(problem.tier)}
                        </span>
                        {problem.has_architecture && (
                          <span className="text-xs px-2 py-0.5 rounded-full bg-purple-100 text-purple-800">
                            已解析
                          </span>
                        )}
                      </div>
                      <h3 className="text-lg font-medium text-[var(--foreground)] mb-1">
                        {problem.competition}
                      </h3>
                      <p className="text-sm text-[var(--muted-foreground)] mb-2">
                        {problem.country}
                      </p>
                      <div className="flex flex-wrap gap-1">
                        {problem.topics.slice(0, 3).map((topic, idx) => (
                          <span
                            key={idx}
                            className="text-xs px-2 py-1 bg-[var(--muted)] rounded text-[var(--muted-foreground)]"
                          >
                            {topic.split(">").pop()?.trim()}
                          </span>
                        ))}
                        {problem.topics.length > 3 && (
                          <span className="text-xs px-2 py-1 text-[var(--muted-foreground)]">
                            +{problem.topics.length - 3}
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="flex flex-col items-end gap-2">
                      {problem.has_architecture ? (
                        <button
                          onClick={() => handleGenerateVideo(problem.id)}
                          className="flex items-center gap-2 px-4 py-2 bg-[var(--primary)] text-white rounded-lg hover:opacity-90 transition-opacity"
                        >
                          <Video className="w-4 h-4" />
                          生成视频
                        </button>
                      ) : (
                        <span className="text-xs text-[var(--muted-foreground)] px-3 py-2">
                          解析中...
                        </span>
                      )}
                      <span className="text-xs text-[var(--muted-foreground)]">
                        {problem.step_count} 步骤
                      </span>
                    </div>
                  </div>
                </div>
              ))}
            </div>

            {/* Pagination */}
            <div className="flex items-center justify-between mt-8">
              <div className="text-sm text-[var(--muted-foreground)]">
                共 {total} 题，第 {page}/{totalPages} 页
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setPage(p => Math.max(1, p - 1))}
                  disabled={page === 1}
                  className="px-4 py-2 bg-[var(--card)] border border-[var(--border)] rounded-lg text-[var(--foreground)] disabled:opacity-50 disabled:cursor-not-allowed hover:bg-[var(--muted)] transition-colors"
                >
                  上一页
                </button>
                <button
                  onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                  className="px-4 py-2 bg-[var(--card)] border border-[var(--border)] rounded-lg text-[var(--foreground)] disabled:opacity-50 disabled:cursor-not-allowed hover:bg-[var(--muted)] transition-colors"
                >
                  下一页
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
