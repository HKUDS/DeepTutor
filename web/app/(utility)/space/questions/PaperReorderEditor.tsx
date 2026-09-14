"use client";

import { FormEvent, useMemo, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  Download,
  GripVertical,
  Loader2,
  Plus,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { useAuthStatus } from "@/hooks/useAuthStatus";
import { apiFetch, apiUrl } from "@/lib/api";
import PaperPreview from "./PaperPreview";
import type {
  PaperExportFormat,
  PaperReorderPayload,
  PaperSectionEditorValue,
  ReorderedPaper,
  UnassignedPolicy,
} from "./types";

const QUESTION_TYPES = [
  ["", "全部题型"],
  ["choice", "选择题"],
  ["concept", "判断题"],
  ["fill_in_blank", "填空题"],
  ["short_answer", "简答题"],
  ["written", "解答题"],
  ["coding", "编程题"],
] as const;

const DIFFICULTIES = [
  ["", "全部难度"],
  ["easy", "简单"],
  ["medium", "中等"],
  ["hard", "困难"],
] as const;

const INITIAL_SECTION: PaperSectionEditorValue = {
  key: "section-1",
  id: "section-1",
  title: "第一部分",
  questionType: "",
  difficulty: "",
  knowledgePointIds: "",
  order: "source",
  questionIds: "",
};

function splitIds(value: string): string[] {
  return value
    .split(/[\s,，]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function errorDetail(payload: unknown): string {
  if (!payload || typeof payload !== "object" || !("detail" in payload))
    return "请求失败";
  const detail = (payload as { detail: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "message" in detail)
    return String((detail as { message: unknown }).message);
  return "请求参数无效";
}

export default function PaperReorderEditor() {
  const { role } = useAuthStatus();
  const canViewAnswers = role === "admin" || role === "teacher";
  const [sourceId, setSourceId] = useState("");
  const [sections, setSections] = useState<PaperSectionEditorValue[]>([
    INITIAL_SECTION,
  ]);
  const [unassignedPolicy, setUnassignedPolicy] =
    useState<UnassignedPolicy>("append");
  const [includeAnswerSheet, setIncludeAnswerSheet] = useState(false);
  const [paper, setPaper] = useState<ReorderedPaper | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"preview" | PaperExportFormat | null>(null);
  const [dragged, setDragged] = useState<{ key: string; index: number } | null>(
    null,
  );

  const sourceOrderIds = useMemo(() => {
    if (!paper) return [];
    const questions = paper.sections
      .flatMap((section) => section.questions)
      .sort((a, b) => a.original_index - b.original_index);
    return [...new Set(questions.map((question) => question.source_question_id))];
  }, [paper]);

  const payload = useMemo<PaperReorderPayload>(
    () => ({
      source_id: sourceId.trim(),
      rules: {
        sections: sections.map((section) => ({
          id: section.id.trim(),
          title: section.title.trim(),
          filter: {
            question_type: section.questionType || null,
            difficulty: section.difficulty || null,
            knowledge_point_ids: splitIds(section.knowledgePointIds),
          },
          order: section.order,
          question_ids: splitIds(section.questionIds),
        })),
        unassigned_policy: unassignedPolicy,
      },
      include_answer_sheet: canViewAnswers && includeAnswerSheet,
    }),
    [canViewAnswers, includeAnswerSheet, sections, sourceId, unassignedPolicy],
  );

  const exportBlocked =
    !paper ||
    paper.audit.input_count !== paper.audit.output_count ||
    paper.audit.unassigned_ids.length > 0 ||
    paper.audit.duplicate_ids.length > 0 ||
    paper.missing_image_refs.length > 0;

  function updateSection(
    key: string,
    update: Partial<PaperSectionEditorValue>,
  ) {
    setSections((current) =>
      current.map((section) =>
        section.key === key ? { ...section, ...update } : section,
      ),
    );
  }

  function addSection() {
    const sequence = sections.length + 1;
    setSections((current) => [
      ...current,
      {
        ...INITIAL_SECTION,
        key: `section-${Date.now()}`,
        id: `section-${sequence}`,
        title: `第${sequence}部分`,
      },
    ]);
  }

  function moveManualId(sectionKey: string, from: number, to: number) {
    const section = sections.find((item) => item.key === sectionKey);
    if (!section) return;
    const ids = splitIds(section.questionIds);
    if (from < 0 || to < 0 || from >= ids.length || to >= ids.length) return;
    const [moved] = ids.splice(from, 1);
    ids.splice(to, 0, moved);
    updateSection(sectionKey, { questionIds: ids.join("\n") });
  }

  async function requestPreview(event?: FormEvent) {
    event?.preventDefault();
    setBusy("preview");
    setError(null);
    try {
      const response = await apiFetch(
        apiUrl("/api/question/paper-reorder/preview"),
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        },
      );
      const data: unknown = await response.json().catch(() => null);
      if (!response.ok) throw new Error(errorDetail(data));
      setPaper(data as ReorderedPaper);
    } catch (caught) {
      setPaper(null);
      setError(caught instanceof Error ? caught.message : "预览失败");
    } finally {
      setBusy(null);
    }
  }

  async function exportPaper(format: PaperExportFormat) {
    setBusy(format);
    setError(null);
    try {
      const response = await apiFetch(
        apiUrl("/api/question/paper-reorder/export"),
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ...payload, format }),
        },
      );
      if (!response.ok) {
        const data: unknown = await response.json().catch(() => null);
        throw new Error(errorDetail(data));
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${paper?.id ?? "reordered-paper"}.${format === "html" ? "html" : "md"}`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "导出失败");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-xl font-semibold text-[var(--foreground)]">题卷重排</h2>
        <p className="mt-1 text-sm text-[var(--muted-foreground)]">
          从当前用户的题目工作区读取 extractor JSON，按题型、难度、知识点或手动顺序重组；原题内容与图片引用不会被改写。
        </p>
      </div>

      <form
        onSubmit={(event) => void requestPreview(event)}
        className="space-y-4 rounded-xl border border-[var(--border)] bg-[var(--card)] p-5 shadow-sm"
      >
        <label className="block">
          <span className="text-sm font-medium text-[var(--foreground)]">来源 ID</span>
          <input
            required
            value={sourceId}
            onChange={(event) => {
              setSourceId(event.target.value);
              setPaper(null);
            }}
            placeholder="例如 mimic_papers/mimic_.../exam_questions.json"
            className="mt-1.5 w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm text-[var(--foreground)] outline-none transition focus:border-[var(--primary)] focus:ring-2 focus:ring-[var(--primary)]/15"
          />
          <span className="mt-1 block text-xs text-[var(--muted-foreground)]">
            仅接受相对路径，且必须位于当前账号的 deep_question 工作区。
          </span>
        </label>

        <div className="space-y-3">
          <div className="flex items-center justify-between gap-3">
            <h3 className="text-sm font-semibold text-[var(--foreground)]">章节与排序规则</h3>
            <button
              type="button"
              onClick={addSection}
              className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs font-medium text-[var(--foreground)] transition hover:bg-[var(--muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]"
            >
              <Plus size={14} /> 新建章节
            </button>
          </div>

          {sections.map((section, sectionIndex) => {
            const manualIds = splitIds(section.questionIds);
            return (
              <fieldset
                key={section.key}
                className="rounded-xl border border-[var(--border)] bg-[var(--muted)]/20 p-4"
              >
                <legend className="px-1 text-xs font-semibold text-[var(--muted-foreground)]">
                  章节 {sectionIndex + 1}
                </legend>
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  <label className="text-xs text-[var(--muted-foreground)]">
                    标题
                    <input
                      required
                      value={section.title}
                      onChange={(event) =>
                        updateSection(section.key, { title: event.target.value })
                      }
                      className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-2.5 py-2 text-sm text-[var(--foreground)] outline-none focus:border-[var(--primary)]"
                    />
                  </label>
                  <label className="text-xs text-[var(--muted-foreground)]">
                    章节 ID
                    <input
                      required
                      value={section.id}
                      onChange={(event) =>
                        updateSection(section.key, { id: event.target.value })
                      }
                      className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-2.5 py-2 font-mono text-sm text-[var(--foreground)] outline-none focus:border-[var(--primary)]"
                    />
                  </label>
                  <label className="text-xs text-[var(--muted-foreground)]">
                    题型
                    <select
                      value={section.questionType}
                      onChange={(event) =>
                        updateSection(section.key, {
                          questionType: event.target.value,
                        })
                      }
                      className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-2.5 py-2 text-sm text-[var(--foreground)] outline-none focus:border-[var(--primary)]"
                    >
                      {QUESTION_TYPES.map(([value, label]) => (
                        <option key={value} value={value}>
                          {label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="text-xs text-[var(--muted-foreground)]">
                    难度
                    <select
                      value={section.difficulty}
                      onChange={(event) =>
                        updateSection(section.key, {
                          difficulty: event.target.value,
                        })
                      }
                      className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-2.5 py-2 text-sm text-[var(--foreground)] outline-none focus:border-[var(--primary)]"
                    >
                      {DIFFICULTIES.map(([value, label]) => (
                        <option key={value} value={value}>
                          {label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="text-xs text-[var(--muted-foreground)] sm:col-span-2">
                    知识点 ID（逗号分隔，匹配任一）
                    <input
                      value={section.knowledgePointIds}
                      onChange={(event) =>
                        updateSection(section.key, {
                          knowledgePointIds: event.target.value,
                        })
                      }
                      className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-2.5 py-2 text-sm text-[var(--foreground)] outline-none focus:border-[var(--primary)]"
                    />
                  </label>
                  <label className="text-xs text-[var(--muted-foreground)]">
                    排序
                    <select
                      value={section.order}
                      onChange={(event) =>
                        updateSection(section.key, {
                          order: event.target.value as PaperSectionEditorValue["order"],
                        })
                      }
                      className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-2.5 py-2 text-sm text-[var(--foreground)] outline-none focus:border-[var(--primary)]"
                    >
                      <option value="source">原卷顺序</option>
                      <option value="easy_to_hard">由易到难</option>
                      <option value="manual">手动拖拽</option>
                    </select>
                  </label>
                  <div className="flex items-end justify-end">
                    <button
                      type="button"
                      disabled={sections.length === 1}
                      onClick={() =>
                        setSections((current) =>
                          current.filter((item) => item.key !== section.key),
                        )
                      }
                      className="inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs text-red-600 transition hover:bg-red-500/10 disabled:cursor-not-allowed disabled:opacity-30"
                    >
                      <Trash2 size={14} /> 删除章节
                    </button>
                  </div>
                </div>

                {section.order === "manual" && (
                  <div className="mt-4 border-t border-[var(--border)] pt-4">
                    <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                      <p className="text-xs text-[var(--muted-foreground)]">
                        每行一个 source_question_id；可拖动或用上下按钮调整。
                      </p>
                      <button
                        type="button"
                        disabled={sourceOrderIds.length === 0}
                        onClick={() =>
                          updateSection(section.key, {
                            questionIds: sourceOrderIds.join("\n"),
                          })
                        }
                        className="rounded-md border border-[var(--border)] px-2 py-1 text-[11px] text-[var(--foreground)] hover:bg-[var(--muted)] disabled:opacity-40"
                      >
                        载入原题顺序
                      </button>
                    </div>
                    <textarea
                      value={section.questionIds}
                      onChange={(event) =>
                        updateSection(section.key, {
                          questionIds: event.target.value,
                        })
                      }
                      rows={Math.max(3, Math.min(7, manualIds.length || 3))}
                      className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 font-mono text-xs text-[var(--foreground)] outline-none focus:border-[var(--primary)]"
                    />
                    {manualIds.length > 0 && (
                      <ol className="mt-2 space-y-1" aria-label="手动题目顺序">
                        {manualIds.map((id, index) => (
                          <li
                            key={`${id}-${index}`}
                            draggable
                            onDragStart={() =>
                              setDragged({ key: section.key, index })
                            }
                            onDragOver={(event) => event.preventDefault()}
                            onDrop={() => {
                              if (dragged?.key === section.key)
                                moveManualId(section.key, dragged.index, index);
                              setDragged(null);
                            }}
                            className="flex items-center gap-2 rounded-md border border-[var(--border)] bg-[var(--background)] px-2 py-1.5"
                          >
                            <GripVertical
                              size={14}
                              className="cursor-grab text-[var(--muted-foreground)]"
                            />
                            <code className="min-w-0 flex-1 truncate text-xs">{id}</code>
                            <button
                              type="button"
                              aria-label={`上移 ${id}`}
                              disabled={index === 0}
                              onClick={() => moveManualId(section.key, index, index - 1)}
                              className="rounded p-1 hover:bg-[var(--muted)] disabled:opacity-30"
                            >
                              <ArrowUp size={13} />
                            </button>
                            <button
                              type="button"
                              aria-label={`下移 ${id}`}
                              disabled={index === manualIds.length - 1}
                              onClick={() => moveManualId(section.key, index, index + 1)}
                              className="rounded p-1 hover:bg-[var(--muted)] disabled:opacity-30"
                            >
                              <ArrowDown size={13} />
                            </button>
                          </li>
                        ))}
                      </ol>
                    )}
                  </div>
                )}
              </fieldset>
            );
          })}
        </div>

        <div className="flex flex-wrap items-center gap-5 rounded-lg bg-[var(--muted)]/30 px-4 py-3">
          <label className="text-xs text-[var(--muted-foreground)]">
            未分配题目
            <select
              value={unassignedPolicy}
              onChange={(event) =>
                setUnassignedPolicy(event.target.value as UnassignedPolicy)
              }
              className="ml-2 rounded-md border border-[var(--border)] bg-[var(--background)] px-2 py-1.5 text-xs text-[var(--foreground)]"
            >
              <option value="append">追加到未分组章节</option>
              <option value="reject">拒绝预览</option>
            </select>
          </label>
          {canViewAnswers && (
            <label className="inline-flex items-center gap-2 text-xs text-[var(--foreground)]">
              <input
                type="checkbox"
                checked={includeAnswerSheet}
                onChange={(event) => setIncludeAnswerSheet(event.target.checked)}
                className="h-4 w-4 rounded border-[var(--border)] accent-[var(--primary)]"
              />
              生成受控教师答案页
            </label>
          )}
        </div>

        {error && (
          <div
            role="alert"
            className="rounded-lg border border-red-300/60 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-200"
          >
            {error}
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="submit"
            disabled={busy !== null}
            className="inline-flex items-center gap-2 rounded-lg bg-[var(--primary)] px-4 py-2 text-sm font-medium text-[var(--primary-foreground)] transition hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)] disabled:opacity-50"
          >
            {busy === "preview" ? (
              <Loader2 size={16} className="animate-spin" />
            ) : (
              <RefreshCw size={16} />
            )}
            生成预览
          </button>
          {(["html", "markdown"] as const).map((format) => (
            <button
              key={format}
              type="button"
              disabled={exportBlocked || busy !== null}
              onClick={() => void exportPaper(format)}
              className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--background)] px-4 py-2 text-sm font-medium text-[var(--foreground)] transition hover:bg-[var(--muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)] disabled:cursor-not-allowed disabled:opacity-40"
            >
              {busy === format ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <Download size={16} />
              )}
              导出 {format === "html" ? "HTML" : "Markdown"}
            </button>
          ))}
        </div>
      </form>

      {paper && <PaperPreview paper={paper} />}
    </div>
  );
}
