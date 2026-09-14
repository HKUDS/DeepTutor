import { apiFetch, apiUrl } from "@/lib/api";

/**
 * 素材处理管线契约（``/api/ingest-pipeline``）— 教师自助上传全自动化。
 *
 * 后端把 解析→建结构→生成题库→挂载 串成一条异步管线，四段状态机诚实：
 * queued / running / done / failed / skipped；单段失败让后续段 skipped，
 * 支持单段重试。前端只渲染状态徽标 + 每段重试按钮。
 */

export type IngestStageStatus =
  | "queued"
  | "running"
  | "done"
  | "failed"
  | "skipped";

export type IngestRunStatus = "queued" | "running" | "done" | "failed" | "partial";

export interface IngestStage {
  status: IngestStageStatus;
  note: string;
  /** structured：结构树节点数。 */
  node_count?: number;
  /** qb_generated：题目总数 / LLM token 用量。 */
  count?: number;
  tokens?: number;
  /** kp_mapped：已映射 / 未映射章节数。 */
  mapped?: number;
  unmapped?: number;
  /** qb_mounted：成功挂载的 KP 数。 */
  mounted?: number;
}

export interface IngestRun {
  run_id: string;
  kb_name: string;
  book_id: string;
  status: IngestRunStatus;
  stages: Record<string, IngestStage>;
  error?: string;
  created_at: string;
  updated_at: string;
}

export const INGEST_STAGE_ORDER = [
  "structured",
  "qb_generated",
  "kp_mapped",
  "qb_mounted",
] as const;

export type IngestStageName = (typeof INGEST_STAGE_ORDER)[number];

async function parseError(res: Response, fallback: string): Promise<never> {
  const data = await res.json().catch(() => ({}));
  throw new Error(
    typeof data.detail === "string" ? data.detail : `${fallback}: ${res.status}`,
  );
}

/** 创建管线 run（后台执行四段）。 */
export async function startIngestPipeline(
  kbName: string,
  bookId: string,
): Promise<{ run: IngestRun }> {
  const res = await apiFetch(apiUrl("/api/ingest-pipeline"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kb_name: kbName, book_id: bookId }),
  });
  if (!res.ok) return parseError(res, "Failed to start pipeline");
  return res.json();
}

/** 取最近一次 run；无记录返回 null（后端 404）。 */
export async function fetchIngestPipeline(
  kbName: string,
  bookId: string,
): Promise<IngestRun | null> {
  const qs = `?kb_name=${encodeURIComponent(kbName)}&book_id=${encodeURIComponent(bookId)}`;
  const res = await apiFetch(apiUrl(`/api/ingest-pipeline${qs}`));
  if (res.status === 404) return null;
  if (!res.ok) return parseError(res, "Failed to load pipeline status");
  const data = (await res.json()) as { run: IngestRun };
  return data.run;
}

/** 重试指定段。 */
export async function retryIngestStage(
  runId: string,
  stage: IngestStageName,
): Promise<{ run: IngestRun }> {
  const res = await apiFetch(
    apiUrl(`/api/ingest-pipeline/${encodeURIComponent(runId)}/retry`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stage }),
    },
  );
  if (!res.ok) return parseError(res, "Failed to retry stage");
  return res.json();
}
