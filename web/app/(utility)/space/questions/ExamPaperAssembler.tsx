"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  BookOpen,
  CheckSquare,
  ChevronDown,
  ChevronRight,
  Download,
  FileText,
  FolderOpen,
  Loader2,
  Square,
} from "lucide-react";
import SpaceSectionHeader from "@/components/space/SpaceSectionHeader";
import { useAuthStatus } from "@/hooks/useAuthStatus";
import { listKnowledgeBases, type KnowledgeBaseSummary } from "@/features/knowledge/api/catalog";
import {
  assembleExamPaper,
  getQuestionsByStruct,
  getTextbookTree,
  mergeQuestions,
} from "@/lib/exam-paper-api";
import type {
  StructQuestion,
  TextbookSummary,
  TextbookTreeNode,
} from "./types";

const TEACHER_ROLES = ["admin", "teacher"];

function nodePath(parent: string, title: string): string {
  return parent ? `${parent}/${title}` : title;
}

function collectNodeIds(
  questions: StructQuestion[],
  underPath: string,
): Set<string> {
  return new Set(
    questions
      .filter(
        (q) =>
          q.struct_path === underPath || q.struct_path.startsWith(`${underPath}/`),
      )
      .map((q) => q.node_id),
  );
}

export default function ExamPaperAssembler() {
  const { role } = useAuthStatus();
  const isTeacher = TEACHER_ROLES.includes(role);

  const [kbs, setKbs] = useState<KnowledgeBaseSummary[]>([]);
  const [kbName, setKbName] = useState("");
  const [textbooks, setTextbooks] = useState<TextbookSummary[]>([]);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [checkedPaths, setCheckedPaths] = useState<Set<string>>(new Set());
  const [questionsByPath, setQuestionsByPath] = useState<
    Map<string, StructQuestion[]>
  >(new Map());
  const [selectedNodeIds, setSelectedNodeIds] = useState<Set<string>>(new Set());
  const [title, setTitle] = useState("");
  const [includeAnswers, setIncludeAnswers] = useState(false);

  const [loadingKbs, setLoadingKbs] = useState(true);
  const [loadingTree, setLoadingTree] = useState(false);
  const [loadingPaths, setLoadingPaths] = useState<Set<string>>(new Set());
  const [exporting, setExporting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [kbHint, setKbHint] = useState("");

  const checkedPathsRef = useRef(checkedPaths);
  checkedPathsRef.current = checkedPaths;

  const questions = useMemo(
    () =>
      mergeQuestions(
        Array.from(questionsByPath.entries()).map(([structPath, qs]) => ({
          structPath,
          questions: qs,
        })),
      ),
    [questionsByPath],
  );

  const loadKbs = useCallback(async () => {
    setLoadingKbs(true);
    try {
      const items = await listKnowledgeBases({ force: true });
      const usable = items.filter(
        (kb) => kb.available !== false && kb.status !== "error",
      );
      setKbs(usable);
      setKbName((prev) =>
        prev && usable.some((kb) => kb.name === prev)
          ? prev
          : (usable[0]?.name ?? ""),
      );
    } catch (caught) {
      setErrorMsg(String(caught instanceof Error ? caught.message : caught));
    } finally {
      setLoadingKbs(false);
    }
  }, []);

  useEffect(() => {
    void loadKbs();
  }, [loadKbs]);

  const resetSelections = useCallback(() => {
    setTextbooks([]);
    setExpanded(new Set());
    setCheckedPaths(new Set());
    setQuestionsByPath(new Map());
    setSelectedNodeIds(new Set());
    setKbHint("");
  }, []);

  const loadTree = useCallback(
    async (name: string) => {
      setLoadingTree(true);
      setErrorMsg(null);
      try {
        const payload = await getTextbookTree(name);
        setTextbooks(payload.textbooks);
        setExpanded(
          new Set(
            payload.textbooks.flatMap((book) => {
              const first: string[] = [];
              if (book.tree?.title) first.push(book.tree.title);
              return first;
            }),
          ),
        );
      } catch (caught) {
        setErrorMsg(String(caught instanceof Error ? caught.message : caught));
      } finally {
        setLoadingTree(false);
      }
    },
    [],
  );

  const handleKbChange = useCallback(
    (name: string) => {
      setKbName(name);
      resetSelections();
      void loadTree(name);
    },
    [loadTree, resetSelections],
  );

  const toggleExpanded = useCallback((path: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }, []);

  const toggleChapter = useCallback(
    async (path: string) => {
      setErrorMsg(null);
      if (checkedPaths.has(path)) {
        // Uncheck: drop the chapter and the questions it contributed.
        setCheckedPaths((prev) => {
          const next = new Set(prev);
          next.delete(path);
          return next;
        });
        setQuestionsByPath((prev) => {
          const next = new Map(prev);
          next.delete(path);
          return next;
        });
        const dropped = collectNodeIds(questionsByPath.get(path) ?? [], path);
        setSelectedNodeIds((prev) => {
          const next = new Set(prev);
          for (const nodeId of dropped) next.delete(nodeId);
          return next;
        });
        return;
      }
      if (!kbName) return;

      setCheckedPaths((prev) => {
        const next = new Set(prev);
        next.add(path);
        return next;
      });
      setLoadingPaths((prev) => new Set(prev).add(path));
      try {
        const payload = await getQuestionsByStruct(kbName, path);
        if (!checkedPathsRef.current.has(path)) return; // unchecked meanwhile
        setQuestionsByPath((prev) => {
          const next = new Map(prev);
          next.set(path, payload.questions);
          return next;
        });
        if (!payload.has_doc_intel && payload.hint) {
          setKbHint(payload.hint);
        }
      } catch (caught) {
        setErrorMsg(String(caught instanceof Error ? caught.message : caught));
        setCheckedPaths((prev) => {
          const next = new Set(prev);
          next.delete(path);
          return next;
        });
      } finally {
        setLoadingPaths((prev) => {
          const next = new Set(prev);
          next.delete(path);
          return next;
        });
      }
    },
    [checkedPaths, kbName, questionsByPath],
  );

  const toggleQuestion = useCallback((nodeId: string) => {
    setSelectedNodeIds((prev) => {
      const next = new Set(prev);
      if (next.has(nodeId)) next.delete(nodeId);
      else next.add(nodeId);
      return next;
    });
  }, []);

  const toggleAll = useCallback(
    (checked: boolean) => {
      setSelectedNodeIds(checked ? new Set(questions.map((q) => q.node_id)) : new Set());
    },
    [questions],
  );

  const handleExport = useCallback(async () => {
    if (!kbName || selectedNodeIds.size === 0) return;
    setExporting(true);
    setErrorMsg(null);
    try {
      const response = await assembleExamPaper({
        kb_name: kbName,
        q_ids: Array.from(selectedNodeIds),
        title: title.trim() || undefined,
        include_answers: includeAnswers,
      });
      if (!response.ok) {
        const data: unknown = await response.json().catch(() => null);
        const detail =
          (data as { detail?: string } | null)?.detail ?? `导出失败 (${response.status})`;
        throw new Error(detail);
      }
      const blob = await response.blob();
      const disposition = response.headers.get("content-disposition") ?? "";
      const rfc5987 = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
      const filename = rfc5987
        ? decodeURIComponent(rfc5987[1])
        : (disposition.match(/filename="?([^";]+)"?/i)?.[1] ?? "exam-paper.docx");
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (caught) {
      setErrorMsg(String(caught instanceof Error ? caught.message : caught));
    } finally {
      setExporting(false);
    }
  }, [includeAnswers, kbName, selectedNodeIds, title]);

  const renderTree = useCallback(
    (node: TextbookTreeNode, parentPath: string, depth: number) => {
      const path = nodePath(parentPath, node.title);
      const hasChildren = Boolean(node.children?.length);
      const isExpanded = expanded.has(path);
      const isChecked = checkedPaths.has(path);
      const isLoading = loadingPaths.has(path);
      return (
        <div key={path} className="select-none">
          <div
            className="flex items-center gap-1.5 rounded-md px-2 py-1.5 transition-colors hover:bg-[var(--muted)]/40"
            style={{ paddingLeft: 8 + depth * 18 }}
          >
            <button
              type="button"
              onClick={() => hasChildren && toggleExpanded(path)}
              className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)] disabled:opacity-30"
              disabled={!hasChildren}
              aria-label={isExpanded ? "折叠" : "展开"}
            >
              {hasChildren ? (
                isExpanded ? (
                  <ChevronDown size={13} />
                ) : (
                  <ChevronRight size={13} />
                )
              ) : (
                <span className="h-1 w-1 rounded-full bg-[var(--border)]" />
              )}
            </button>
            <button
              type="button"
              onClick={() => void toggleChapter(path)}
              className="flex h-5 w-5 shrink-0 items-center justify-center text-[var(--muted-foreground)] transition-colors hover:text-[var(--primary)]"
              aria-label={isChecked ? "取消勾选章节" : "勾选章节"}
            >
              {isLoading ? (
                <Loader2 size={13} className="animate-spin" />
              ) : isChecked ? (
                <CheckSquare size={15} className="text-[var(--primary)]" />
              ) : (
                <Square size={15} />
              )}
            </button>
            <span
              className={`truncate text-[13px] ${
                isChecked
                  ? "font-medium text-[var(--primary)]"
                  : "text-[var(--foreground)]"
              }`}
            >
              {node.title}
            </span>
          </div>
          {hasChildren && isExpanded && (
            <div>{node.children!.map((child) => renderTree(child, path, depth + 1))}</div>
          )}
        </div>
      );
    },
    [checkedPaths, expanded, loadingPaths, toggleChapter, toggleExpanded],
  );

  const selectedCount = selectedNodeIds.size;
  const totalCount = questions.length;

  return (
    <div className="space-y-4">
      <SpaceSectionHeader
        icon={FileText}
        title="组卷"
        description="按教材章节勾选题目，一键导出 Word 试卷（可附带参考答案）。"
      />

      {errorMsg && (
        <div className="flex items-center gap-2 rounded-xl border border-red-200 bg-red-50/60 px-4 py-3 text-[13px] text-red-600 dark:border-red-900/40 dark:bg-red-950/20 dark:text-red-400">
          <AlertTriangle size={15} className="shrink-0" />
          <span>{errorMsg}</span>
        </div>
      )}

      {!isTeacher && (
        <div className="rounded-xl border border-[var(--border)] bg-[var(--muted)]/30 px-4 py-3 text-[13px] text-[var(--muted-foreground)]">
          组卷功能仅对教师与管理员开放。
        </div>
      )}

      {/* Knowledge base picker */}
      <div className="flex items-center gap-3 rounded-xl border border-[var(--border)] bg-[var(--card)] px-4 py-3 shadow-sm">
        <label className="shrink-0 text-[13px] font-medium text-[var(--foreground)]">
          知识库
        </label>
        {loadingKbs ? (
          <Loader2 size={15} className="animate-spin text-[var(--muted-foreground)]" />
        ) : (
          <select
            value={kbName}
            onChange={(event) => handleKbChange(event.target.value)}
            disabled={kbs.length === 0}
            className="min-w-0 flex-1 rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-1.5 text-[13px] text-[var(--foreground)] outline-none focus:border-[var(--primary)] disabled:opacity-40"
          >
            {kbs.length === 0 && <option value="">（暂无可用知识库）</option>}
            {kbs.map((kb) => (
              <option key={kb.name} value={kb.name}>
                {kb.name}
                {kb.is_default ? "（默认）" : ""}
              </option>
            ))}
          </select>
        )}
      </div>

      {kbHint && (
        <div className="rounded-xl border border-amber-200 bg-amber-50/60 px-4 py-3 text-[13px] text-amber-700 dark:border-amber-900/40 dark:bg-amber-950/20 dark:text-amber-400">
          {kbHint}
        </div>
      )}

      {/* Textbook tree + question list */}
      <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <div className="rounded-xl border border-[var(--border)] bg-[var(--card)] shadow-sm">
          <div className="flex items-center justify-between border-b border-[var(--border)]/70 px-4 py-3">
            <span className="flex items-center gap-2 text-[13px] font-medium text-[var(--foreground)]">
              <BookOpen size={14} className="text-[var(--muted-foreground)]" />
              教材章节
            </span>
            <span className="text-[11px] text-[var(--muted-foreground)]">
              勾选章节加载题目
            </span>
          </div>
          <div className="max-h-[420px] overflow-y-auto p-2">
            {loadingTree ? (
              <div className="flex min-h-[120px] items-center justify-center">
                <Loader2 className="h-4 w-4 animate-spin text-[var(--muted-foreground)]" />
              </div>
            ) : textbooks.length === 0 ? (
              <div className="flex min-h-[120px] flex-col items-center justify-center gap-2 px-4 text-center">
                <FolderOpen size={18} className="text-[var(--muted-foreground)]" />
                <p className="text-[12.5px] text-[var(--muted-foreground)]">
                  该知识库暂无教材结构（doc_tree），
                  <br />
                  请先处理带结构的教材文档。
                </p>
              </div>
            ) : (
              textbooks.map((book) => (
                <div key={book.doc_id} className="mb-1">
                  {book.tree?.title
                    ? renderTree(book.tree, "", 0)
                    : (
                        <div className="px-3 py-2 text-[12.5px] text-[var(--muted-foreground)]">
                          {book.file_name}（无章节树）
                        </div>
                      )}
                </div>
              ))
            )}
          </div>
        </div>

        <div className="flex min-h-[420px] flex-col rounded-xl border border-[var(--border)] bg-[var(--card)] shadow-sm">
          <div className="flex items-center justify-between gap-2 border-b border-[var(--border)]/70 px-4 py-3">
            <span className="flex items-center gap-2 text-[13px] font-medium text-[var(--foreground)]">
              <FileText size={14} className="text-[var(--muted-foreground)]" />
              已选题目
              <span className="rounded-full bg-[var(--muted)] px-1.5 py-0.5 text-[10px] tabular-nums text-[var(--muted-foreground)]">
                {selectedCount}/{totalCount}
              </span>
            </span>
            <button
              type="button"
              onClick={() => toggleAll(totalCount > 0 && selectedCount !== totalCount)}
              disabled={totalCount === 0}
              className="rounded-md px-2 py-1 text-[12px] text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-40"
            >
              {selectedCount === totalCount && totalCount > 0 ? "取消全选" : "全选"}
            </button>
          </div>
          <div className="max-h-[420px] flex-1 overflow-y-auto">
            {questions.length === 0 ? (
              <div className="flex min-h-[320px] flex-col items-center justify-center gap-2 px-6 text-center">
                <FileText size={20} className="text-[var(--muted-foreground)]" />
                <p className="text-[13px] text-[var(--muted-foreground)]">
                  在左侧勾选章节后，此处会列出该章节的 doc_intel 题目。
                </p>
              </div>
            ) : (
              <ul className="flex flex-col gap-2 p-3">
                {questions.map((question) => {
                  const selected = selectedNodeIds.has(question.node_id);
                  return (
                    <li
                      key={question.node_id}
                      className={`rounded-lg border px-3 py-2.5 transition-colors ${
                        selected
                          ? "border-[var(--primary)]/50 bg-[var(--muted)]/40"
                          : "border-[var(--border)]/70 hover:border-[var(--border)]"
                      }`}
                    >
                      <label className="flex cursor-pointer items-start gap-2.5">
                        <input
                          type="checkbox"
                          checked={selected}
                          onChange={() => toggleQuestion(question.node_id)}
                          className="mt-0.5 h-4 w-4 shrink-0 accent-[var(--primary)]"
                        />
                        <span className="min-w-0 flex-1">
                          <span className="mb-1 flex flex-wrap items-center gap-1.5">
                            {question.question_type && (
                              <span className="rounded-md bg-[var(--muted)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--muted-foreground)]">
                                {question.question_type}
                              </span>
                            )}
                            {question.difficulty && (
                              <span className="rounded-md bg-[var(--muted)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--muted-foreground)]">
                                {question.difficulty}
                              </span>
                            )}
                            <span
                              className={`rounded-md px-1.5 py-0.5 text-[10px] font-medium ${
                                question.has_answer
                                  ? "bg-green-100 text-green-700 dark:bg-green-950/30 dark:text-green-400"
                                  : "bg-[var(--muted)] text-[var(--muted-foreground)]"
                              }`}
                            >
                              {question.has_answer ? "有答案" : "无答案"}
                            </span>
                            <span className="text-[10px] text-[var(--muted-foreground)]">
                              {question.q_id}
                            </span>
                          </span>
                          <span className="line-clamp-2 block text-[13px] leading-relaxed text-[var(--foreground)]">
                            {question.text}
                          </span>
                          <span className="mt-1 block truncate text-[10.5px] text-[var(--muted-foreground)]">
                            {question.struct_path}
                          </span>
                        </span>
                      </label>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>
      </div>

      {/* Export bar */}
      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-[var(--border)] bg-[var(--card)] px-4 py-3 shadow-sm">
        <input
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="试卷标题（默认：试卷）"
          className="min-w-0 flex-1 rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[13px] text-[var(--foreground)] outline-none placeholder:text-[var(--muted-foreground)] focus:border-[var(--primary)]"
        />
        <label className="flex shrink-0 cursor-pointer items-center gap-1.5 text-[13px] text-[var(--foreground)]">
          <input
            type="checkbox"
            checked={includeAnswers}
            onChange={(event) => setIncludeAnswers(event.target.checked)}
            className="h-4 w-4 accent-[var(--primary)]"
          />
          含参考答案
        </label>
        <button
          type="button"
          onClick={() => void handleExport()}
          disabled={exporting || selectedCount === 0}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-[var(--primary)] px-4 py-2 text-[13px] font-medium text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {exporting ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <Download size={14} />
          )}
          组卷导出
        </button>
      </div>
    </div>
  );
}
