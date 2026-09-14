import { apiFetch, apiUrl } from "@/lib/api";
import type {
  ExamPaperAssemblePayload,
  StructQuestion,
  StructQuestionsResponse,
  TextbookSummary,
} from "@/app/(utility)/space/questions/types";

/** Response envelope of GET /api/{kb_name}/textbook-tree. */
export interface TextbookTreeResponse {
  kb_name: string;
  textbooks: TextbookSummary[];
}

/**
 * Fetch the textbook structure trees of a knowledge base (aggregated per
 * source document from the doc_intel ``doc_tree`` metadata).
 */
export async function getTextbookTree(kbName: string): Promise<TextbookTreeResponse> {
  const response = await apiFetch(
    apiUrl(`/api/${encodeURIComponent(kbName)}/textbook-tree`),
    { cache: "no-store" },
  );
  if (!response.ok) {
    throw new Error(`加载教材树失败 (${response.status})`);
  }
  return (await response.json()) as TextbookTreeResponse;
}

/**
 * Fetch doc_intel question nodes under a struct path. The path uses the same
 * "/"-joined segment format as the textbook tree (e.g. ``必修一/第1章 集合``).
 */
export async function getQuestionsByStruct(
  kbName: string,
  structPath: string,
): Promise<StructQuestionsResponse> {
  const query = new URLSearchParams({ struct_path: structPath });
  const response = await apiFetch(
    apiUrl(
      `/api/${encodeURIComponent(kbName)}/questions/by-struct?${query.toString()}`,
    ),
    { cache: "no-store" },
  );
  if (!response.ok) {
    throw new Error(`加载题目失败 (${response.status})`);
  }
  return (await response.json()) as StructQuestionsResponse;
}

/**
 * Assemble a paper from the given question node ids and return the raw
 * response so the caller can download the docx blob.
 */
export async function assembleExamPaper(
  payload: ExamPaperAssemblePayload,
): Promise<Response> {
  return apiFetch(apiUrl("/api/exam-paper/assemble"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

/** Merge question lists from multiple chapters, de-duplicated by node_id. */
export function mergeQuestions(
  lists: Array<{ structPath: string; questions: StructQuestion[] }>,
): StructQuestion[] {
  const byNodeId = new Map<string, StructQuestion>();
  for (const { questions } of lists) {
    for (const question of questions) {
      if (!byNodeId.has(question.node_id)) byNodeId.set(question.node_id, question);
    }
  }
  return Array.from(byNodeId.values());
}
