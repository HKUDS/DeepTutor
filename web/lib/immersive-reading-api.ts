import { apiFetch, apiUrl } from "@/lib/api";

const BASE = "/api/v1/immersive-reading";

export interface ReadingSection {
  id: string;
  title: string;
  index: number;
  char_count: number;
  source_start: number;
  source_end: number;
  checkpoint_kind: "chapter" | "chunk" | "none";
  source_href?: string;
  parent_id?: string;
  level?: number;
}

export interface FocusAttempt {
  section_id: string;
  passed: boolean;
  score: number;
  feedback: string;
  attempt_count: number;
  updated_at: number;
}

export interface FocusAttemptRecord {
  id: string;
  section_id: string;
  attempt_number: number;
  immersive_run: number;
  summary: string;
  reflection: string;
  language: string;
  model: string;
  binding: string;
  prompt_version: string;
  pass_threshold: number;
  answer_recorded: boolean;
  status: "pending" | "graded" | "error";
  passed: boolean;
  score: number | null;
  feedback: string;
  strengths: string[];
  missing_points: string[];
  error: string;
  latency_seconds: number | null;
  created_at: number;
  updated_at: number;
}

export interface ReadingProgress {
  document_id: string;
  current_section_id: string;
  current_section_index: number;
  scroll_percent: number;
  passed_section_ids: string[];
  skipped_section_ids: string[];
  focus_attempts: Record<string, FocusAttempt>;
  focus_history: Record<string, FocusAttemptRecord[]>;
  epub_cfi?: string;
  section_href?: string;
  immersive_run: number;
  updated_at: number;
}

export interface FastSearchIndexStatus {
  status: "not_started" | "building" | "ready" | "partial" | "failed" | "stale";
  total_sections: number;
  completed_sections: number;
  failed_sections: number;
  model: string;
  binding: string;
  prompt_version: string;
  updated_at: number;
  needs_build: boolean;
  errors: Record<string, string>;
}

export interface ReadingDocument {
  id: string;
  title: string;
  author: string;
  source_filename: string;
  source_format: string;
  total_chars: number;
  total_words: number;
  reading_mode: "chapters" | "chunks";
  sections: ReadingSection[];
  has_cover: boolean;
  created_at: number;
  updated_at: number;
  progress: ReadingProgress;
  progress_percent: number;
  experience_mode: "standard" | "kids";
  cover_url: string;
  fast_search_index: FastSearchIndexStatus;
}

export interface ReadingCitation {
  id: string;
  document_id: string;
  document_title: string;
  section_id: string;
  section_title: string;
  quote: string;
  note: string;
  created_at: number;
}

export interface SearchHit {
  section_id: string;
  section_title: string;
  section_index: number;
  excerpt: string;
  score: number;
  reason: string;
  start_offset: number;
  end_offset: number;
}

export interface SearchResponse {
  hits: SearchHit[];
  resolved_mode: string;
  fallback_used: boolean;
  fallback_reason?: string;
  candidate_sections?: string[];
  warnings?: string[];
}

export interface DescriptionSearchJob {
  id: string;
  document_id: string;
  status: "queued" | "running" | "completed" | "failed";
  created_at: number;
  updated_at: number;
  result: SearchResponse | null;
  error: string;
}

export interface ReadingCapabilities {
  model: string;
  context_window: number;
  description_search_enabled: boolean;
  description_search_minimum: number;
}

export interface FocusCheckResult {
  passed: boolean;
  score: number;
  feedback: string;
  strengths: string[];
  missing_points: string[];
  prompts: string[];
  progress: ReadingProgress;
}

export interface CharacterNode {
  id: string;
  name: string;
  aliases: string[];
  description: string;
}

export interface CharacterEdge {
  source: string;
  target: string;
  relation: string;
  confidence: number;
}

export interface CharacterGraphResult {
  graph: {
    nodes: CharacterNode[];
    edges: CharacterEdge[];
  };
  mermaid: string;
  generated_at: number;
  scope: "current" | "through_current";
  section_id: string;
}

export interface KidsQuizChoice {
  id: string;
  kind: "comprehension" | "sight_word" | "sequence";
  question: string;
  choices: string[];
  answer_index: number;
  explanation: string;
}

export interface KidsQuizResult {
  document_id: string;
  section_id: string;
  questions: KidsQuizChoice[];
  content_hash: string;
  model: string;
  prompt_version: string;
  generated_at: number;
}


async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!(init?.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const response = await apiFetch(apiUrl(`${BASE}${path}`), { ...init, headers });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body?.detail || body?.message || detail;
    } catch {
      // Keep the HTTP status text.
    }
    throw new Error(String(detail));
  }
  return (await response.json()) as T;
}

export const immersiveReadingApi = {
  capabilities: () => request<ReadingCapabilities>("/capabilities"),
  list: () => request<{ documents: ReadingDocument[] }>("/documents"),
  get: (documentId: string) =>
    request<{ document: ReadingDocument }>(`/documents/${encodeURIComponent(documentId)}`),
  import: async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ document: ReadingDocument }>("/documents/import", {
      method: "POST",
      body: form,
    });
  },
  delete: (documentId: string) =>
    request<{ deleted: boolean }>(`/documents/${encodeURIComponent(documentId)}`, {
      method: "DELETE",
    }),
  section: (documentId: string, sectionId: string) =>
    request<{
      section: ReadingSection;
      content: string;
      passed: boolean;
      skipped: boolean;
      locked: boolean;
    }>(
      `/documents/${encodeURIComponent(documentId)}/sections/${encodeURIComponent(sectionId)}`,
    ),
  progress: (documentId: string, sectionId: string, scrollPercent: number) =>
    request<{ progress: ReadingProgress }>(
      `/documents/${encodeURIComponent(documentId)}/progress`,
      {
        method: "PUT",
        body: JSON.stringify({ section_id: sectionId, scroll_percent: scrollPercent }),
      },
    ),
  restart: (documentId: string, resetFocusChecks: boolean) =>
    request<{ progress: ReadingProgress }>(
      `/documents/${encodeURIComponent(documentId)}/restart`,
      {
        method: "POST",
        body: JSON.stringify({ reset_focus_checks: resetFocusChecks }),
      },
    ),
  skipSection: (documentId: string, sectionId: string) =>
    request<{ progress: ReadingProgress }>(
      `/documents/${encodeURIComponent(documentId)}/skip-section`,
      {
        method: "POST",
        body: JSON.stringify({ section_id: sectionId }),
      },
    ),
  search: (
    documentId: string,
    query: string,
    mode: "exact" | "fuzzy" | "description_fast" | "description_fine",
  ) =>
    request<SearchResponse>(`/documents/${encodeURIComponent(documentId)}/search`, {
      method: "POST",
      body: JSON.stringify({ query, mode }),
    }),
  startSearchJob: (
    documentId: string,
    query: string,
    mode: "description_fast" | "description_fine",
  ) =>
    request<{ job: DescriptionSearchJob }>(
      `/documents/${encodeURIComponent(documentId)}/search-jobs`,
      {
        method: "POST",
        body: JSON.stringify({ query, mode }),
      },
    ),
  searchJobStatus: (documentId: string, jobId: string) =>
    request<{ job: DescriptionSearchJob }>(
      `/documents/${encodeURIComponent(documentId)}/search-jobs/${encodeURIComponent(jobId)}`,
    ),
  fastIndexStatus: (documentId: string) =>
    request<{ index: FastSearchIndexStatus }>(
      `/documents/${encodeURIComponent(documentId)}/fast-search-index`,
    ),
  rebuildFastIndex: (documentId: string) =>
    request<{ index: FastSearchIndexStatus }>(
      `/documents/${encodeURIComponent(documentId)}/fast-search-index/rebuild`,
      { method: "POST", body: JSON.stringify({}) },
    ),
  focusCheck: (
    documentId: string,
    payload: { section_id: string; summary: string; reflection: string; language: "zh" | "en" },
  ) =>
    request<FocusCheckResult>(`/documents/${encodeURIComponent(documentId)}/focus-check`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  citations: (documentId?: string) =>
    request<{ citations: ReadingCitation[] }>(
      `/citations${documentId ? `?document_id=${encodeURIComponent(documentId)}` : ""}`,
    ),
  cite: (documentId: string, sectionId: string, quote: string, note = "") =>
    request<{ citation: ReadingCitation }>(
      `/documents/${encodeURIComponent(documentId)}/citations`,
      {
        method: "POST",
        body: JSON.stringify({ section_id: sectionId, quote, note }),
      },
    ),
  deleteCitation: (citationId: string) =>
    request<{ deleted: boolean }>(`/citations/${encodeURIComponent(citationId)}`, {
      method: "DELETE",
    }),
  translate: (text: string, targetLanguage: string) =>
    request<{ translation: string }>("/translate", {
      method: "POST",
      body: JSON.stringify({ text, target_language: targetLanguage }),
    }),
  query: (text: string, question: string, language: "zh" | "en") =>
    request<{ answer: string; citations: Array<Record<string, unknown>>; search_provider: string }>(
      "/query",
      { method: "POST", body: JSON.stringify({ text, question, language }) },
    ),
  characterGraph: (
    documentId: string,
    sectionId: string,
    scope: "current" | "through_current" = "current",
    forceRefresh = false,
  ) =>
    request<CharacterGraphResult>(
      `/documents/${encodeURIComponent(documentId)}/character-graph`,
      {
        method: "POST",
        body: JSON.stringify({
          section_id: sectionId,
          scope,
          force_refresh: forceRefresh,
        }),
      },
    ),
};

// ── Bilingual paired reading ────────────────────────────────────────────

export interface BilingualPairing {
  pairing_id: string;
  en_document_id: string;
  zh_document_id: string;
  en_title: string;
  zh_title: string;
  target_lang: string;
  translator: string;
  chapter_count: number;
  aligned: boolean;
  review_count: number;
  annotation_count?: number;
  created_at: number;
  updated_at: number;
  chapter_map?: ChapterMapEntry[];
}

export interface ChapterMapEntry {
  id: string;
  english: string;
  translation: string;
  en_title?: string;
  zh_title?: string;
}

export interface BilingualAlignGroup {
  en: string[];
  zh: string[];
  shape: string;
  cost: number;
  forced: boolean;
  low_confidence: boolean;
}

export interface BilingualSection {
  chapter: string;
  en_title: string;
  pairs: number;
  groups: BilingualAlignGroup[];
  review: Array<Record<string, unknown>>;
}

export const bilingualApi = {
  pair: (enDocumentId: string, zhDocumentId: string, targetLang?: string, translator = "") =>
    request<{ pairing_id: string } & Partial<BilingualPairing>>("/bilingual/pair", {
      method: "POST",
      body: JSON.stringify({
        en_document_id: enDocumentId,
        zh_document_id: zhDocumentId,
        target_lang: targetLang,
        translator,
      }),
    }),
  list: () => request<{ pairings: BilingualPairing[] }>("/bilingual"),
  get: (pairingId: string) =>
    request<BilingualPairing>(`/bilingual/${encodeURIComponent(pairingId)}`),
  updateChapterMap: (pairingId: string, chapterMap: ChapterMapEntry[]) =>
    request<BilingualPairing>(`/bilingual/${encodeURIComponent(pairingId)}/chapter-map`, {
      method: "PUT",
      body: JSON.stringify({ chapter_map: chapterMap }),
    }),
  align: (pairingId: string, force = false) =>
    request<BilingualPairing>(
      `/bilingual/${encodeURIComponent(pairingId)}/align${force ? "?force=true" : ""}`,
      { method: "POST" },
    ),
  section: (pairingId: string, chapterId: string) =>
    request<BilingualSection>(
      `/bilingual/${encodeURIComponent(pairingId)}/section/${encodeURIComponent(chapterId)}`,
    ),
  report: (pairingId: string) =>
    request<{ report: string }>(`/bilingual/${encodeURIComponent(pairingId)}/report`),
  exportUrl: (pairingId: string) =>
    apiUrl(`${BASE}/bilingual/${encodeURIComponent(pairingId)}/export`),
  delete: (pairingId: string) =>
    request<{ status: string }>(`/bilingual/${encodeURIComponent(pairingId)}`, {
      method: "DELETE",
    }),
};

// ── Annotation (review feedback loop) ───────────────────────────────────

export interface BilingualAnnotation {
  id: string;
  pairing_id: string;
  chapter_id: string;
  chapter_title: string;
  group_index: number;
  issue_type: string;
  note: string;
  en_text: string;
  zh_text: string;
  shape: string;
  cost: number;
  status: "open" | "resolved";
  created_at: number;
}

export const annotationApi = {
  list: (pairingId: string, status?: string) =>
    request<{ annotations: BilingualAnnotation[] }>(
      `/bilingual/${encodeURIComponent(pairingId)}/annotations${status ? `?status=${status}` : ""}`,
    ),
  add: (
    pairingId: string,
    payload: {
      chapter_id: string;
      group_index: number;
      issue_type: string;
      note?: string;
    },
  ) =>
    request<BilingualAnnotation>(
      `/bilingual/${encodeURIComponent(pairingId)}/annotations`,
      { method: "POST", body: JSON.stringify(payload) },
    ),
  resolve: (pairingId: string, annotationId: string, resolved = true) =>
    request<{ status: string }>(
      `/bilingual/${encodeURIComponent(pairingId)}/annotations/${encodeURIComponent(annotationId)}`,
      { method: "PUT", body: JSON.stringify({ resolved }) },
    ),
  delete: (pairingId: string, annotationId: string) =>
    request<{ status: string }>(
      `/bilingual/${encodeURIComponent(pairingId)}/annotations/${encodeURIComponent(annotationId)}`,
      { method: "DELETE" },
    ),
  reviewReport: (pairingId: string) =>
    request<{ report: string }>(
      `/bilingual/${encodeURIComponent(pairingId)}/review-report`,
    ),
  saveOverrides: (pairingId: string, overridesJson: string) =>
    request<{ status: string }>(
      `/bilingual/${encodeURIComponent(pairingId)}/alignment-overrides`,
      { method: "PUT", body: JSON.stringify({ overrides_json: overridesJson }) },
    ),
  setExperienceMode: (documentId: string, mode: "standard" | "kids") =>
    request<{ experience_mode: string; progress_percent: number }>(
      `/documents/${encodeURIComponent(documentId)}/experience-mode`,
      {
        method: "PUT",
        body: JSON.stringify({ mode }),
      },
    ),
  kidsQuiz: (
    documentId: string,
    sectionId: string,
    forceRefresh = false,
  ) =>
    request<KidsQuizResult>(
      `/documents/${encodeURIComponent(documentId)}/kids-quiz`,
      {
        method: "POST",
        body: JSON.stringify({ section_id: sectionId, force_refresh: forceRefresh }),
      },
    ),
  kidsProgress: (
    documentId: string,
    sectionId: string,
    data: { scroll_percent?: number; epub_cfi?: string; section_href?: string },
  ) =>
    request<{ progress: ReadingProgress }>(
      `/documents/${encodeURIComponent(documentId)}/kids-progress`,
      {
        method: "PUT",
        body: JSON.stringify({ section_id: sectionId, ...data }),
      },
    ),
};