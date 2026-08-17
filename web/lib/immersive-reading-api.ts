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

export interface DictionaryDefinition {
  part_of_speech: string;
  definition: string;
  chinese: string;
  example: string;
  synonyms: string[];
  context_match: boolean;
}

export interface DictionaryResult {
  word: string;
  phonetic: string;
  definitions: DictionaryDefinition[];
  chinese?: string;
  context_note: string;
}

export interface DictionaryStatus {
  installed: boolean;
  frequency_fields?: boolean;
  path: string;
  entries: number | null;
  size_bytes: number;
  version: string | null;
  checksum: string | null;
  license: string | null;
  import_progress: number | null;
  error: string;
}

export interface ImmersiveTranslationJob {
  job_id: string;
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  created_at: number;
  updated_at: number;
  result: string | null;
  error: string;
  cache_key: string;
  target_language: string;
}

export interface ImmersiveTranslationJobEvent {
  type: "snapshot" | "started" | "delta" | "completed" | "failed" | "cancelled";
  job_id: string;
  status: ImmersiveTranslationJob["status"];
  delta?: string;
  translation?: string | null;
  error?: string;
  sequence?: number;
}

export interface VocabEntry {
  id: string;
  word: string;
  phonetic: string;
  definitions: DictionaryDefinition[];
  chinese: string;
  context_note: string;
  document_id: string;
  document_title: string;
  section_title: string;
  pairing_id?: string;
  chapter_id?: string;
  chapter_index?: number;
  group_index?: number;
  context_en: string;
  context_zh: string;
  cards: VocabularyCard[];
  review: VocabularyReviewState;
  created_at: number;
  updated_at?: number;
  occurrence_count?: number;
  mn4_exported: boolean;
}

export interface VocabularyCard {
  id: string;
  card_type: "cloze" | "choice";
  front: string;
  back: string;
  context_en: string;
  context_zh: string;
  choices: string[];
  answer: string;
  created_at: number;
  updated_at: number;
}

export interface VocabularyReviewState {
  due_at: number;
  interval_index: number;
  consecutive_correct: number;
  review_count: number;
  correct_count: number;
  wrong_count: number;
  last_result: "unset" | "correct" | "wrong";
  last_reviewed_at: number;
}

export type VocabularyBand = "core" | "common" | "advanced" | "low" | "unknown";

export interface VocabularyDifficultyWord {
  word: string;
  lemma: string;
  count: number;
  frequency_rank: number | null;
  oxford: boolean;
  band: VocabularyBand;
  phonetic: string;
  definition: string;
  chinese: string;
}

export interface VocabularyDifficultyPreview {
  available: boolean;
  reason: string;
  words: VocabularyDifficultyWord[];
  distribution: Record<VocabularyBand, number | undefined>;
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
    throw new ApiRequestError(String(detail), response.status);
  }
  return (await response.json()) as T;
}

async function readTranslationJobEvents(
  body: ReadableStream<Uint8Array>,
  onEvent: (event: ImmersiveTranslationJobEvent) => void,
) {
  const decoder = new TextDecoder();
  const reader = body.getReader();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    if (!value) continue;
    buffer += decoder.decode(value, { stream: true });
    let index = buffer.indexOf("\n");
    while (index >= 0) {
      const raw = buffer.slice(0, index).trim();
      buffer = buffer.slice(index + 1);
      if (raw) {
        try {
          onEvent(JSON.parse(raw));
        } catch {
          // Ignore parse errors from partial frames.
        }
      }
      index = buffer.indexOf("\n");
    }
  }
  const tail = buffer.trim();
  if (tail) {
    try {
      onEvent(JSON.parse(tail));
    } catch {
      // Ignore parse errors from malformed tail frames.
    }
  }
}

export class ApiRequestError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
  }
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
  epubProgress: (
    documentId: string,
    data: { epub_cfi?: string; section_href?: string; scroll_percent?: number },
  ) =>
    request<{ progress: ReadingProgress }>(
      `/documents/${encodeURIComponent(documentId)}/epub-progress`,
      {
        method: "PUT",
        body: JSON.stringify(data),
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
  translate: (text: string, targetLanguage: string, documentId?: string, sourceObjectId?: string, signal?: AbortSignal) =>
    request<{ translation: string }>("/translate", {
      method: "POST",
      body: JSON.stringify({ text, target_language: targetLanguage, document_id: documentId || "", source_object_id: sourceObjectId || "" }),
      signal,
    }),
  translateJob: (
    text: string,
    targetLanguage: string,
    glossary: Array<Record<string, unknown>> = [],
    documentId?: string,
    sourceObjectId?: string,
    signal?: AbortSignal,
  ) =>
    request<ImmersiveTranslationJob>("/translate/job", {
      method: "POST",
      body: JSON.stringify({ text, target_language: targetLanguage, glossary, document_id: documentId || "", source_object_id: sourceObjectId || "" }),
      signal,
    }),
  translateJobStatus: (jobId: string) =>
    request<ImmersiveTranslationJob>(`/translate/${encodeURIComponent(jobId)}/status`),
  translateJobCancel: (jobId: string) =>
    request<{ job_id: string; status: string; cancelled: boolean }>(
      `/translate/${encodeURIComponent(jobId)}/cancel`,
      { method: "POST" },
    ),
  translateJobStream: async (
    jobId: string,
    onEvent: (event: ImmersiveTranslationJobEvent) => void,
    signal?: AbortSignal,
  ) => {
    const response = await apiFetch(
      apiUrl(`${BASE}/translate/${encodeURIComponent(jobId)}/stream`),
      { headers: new Headers(), signal },
    );
    if (!response.ok) {
      let detail = response.statusText;
      try {
        const body = await response.json();
        detail = body?.detail || body?.message || detail;
      } catch {
        // Keep HTTP status text.
      }
      throw new ApiRequestError(String(detail), response.status);
    }
    if (!response.body) return;
    await readTranslationJobEvents(response.body, onEvent);
  },
  dictionary: (word: string, context = "", signal?: AbortSignal) =>
    request<DictionaryResult>("/dictionary", {
      method: "POST",
      body: JSON.stringify({ word, context }),
      signal,
    }),
  dictionaryStatus: () => request<DictionaryStatus>("/dictionary/status"),
  importDictionaryCsv: (file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<{ imported: boolean; entries: number }>(
      "/dictionary/ecdict/import",
      { method: "POST", body },
    );
  },
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
  query: (text: string, question: string, language: "zh" | "en") =>
    request<{ answer: string; citations: Array<Record<string, unknown>>; search_provider: string }>(
      "/query",
      { method: "POST", body: JSON.stringify({ text, question, language }) },
    ),
  vocabulary: (documentId?: string, pairingId?: string) => {
    const query = new URLSearchParams(
      Object.entries({ document_id: documentId, pairing_id: pairingId }).filter(
        ([, value]) => Boolean(value),
      ) as Array<[string, string]>,
    ).toString();
    return request<{ entries: VocabEntry[] }>(
      `/vocabulary${query ? `?${query}` : ""}`,
    );
  },
  addWord: (
    word: string,
    context: string,
    documentId: string,
    documentTitle: string,
    sectionTitle: string,
    source?: {
      pairing_id?: string;
      chapter_id?: string;
      chapter_index?: number;
      group_index?: number;
    },
  ) =>
   request<{ entry: VocabEntry; lookup_warning?: string }>("/vocabulary", {
     method: "POST",
     body: JSON.stringify({
       word,
       context,
       document_id: documentId,
       document_title: documentTitle,
       section_title: sectionTitle,
       ...source,
      }),
    }),
  deleteWord: (entryId: string) =>
    request<{ deleted: boolean }>(`/vocabulary/${encodeURIComponent(entryId)}`, {
      method: "DELETE",
    }),
  reviewVocabulary: (limit = 10) =>
    request<{ entries: VocabEntry[] }>(
      `/vocabulary/review?limit=${encodeURIComponent(String(limit))}`,
    ),
  gradeVocabularyReview: (entryId: string, correct: boolean) =>
    request<{ entry: VocabEntry }>("/vocabulary/review/grade", {
      method: "POST",
      body: JSON.stringify({ entry_id: entryId, correct }),
    }),
  vocabularyExportUrl: (format: "csv" | "apkg") =>
    `${apiUrl(BASE)}/vocabulary/export/${format}`,
  sectionVocabularyDifficulty: (documentId: string, sectionId: string) =>
    request<VocabularyDifficultyPreview>(
      `/documents/${encodeURIComponent(documentId)}/sections/${encodeURIComponent(sectionId)}/vocabulary-difficulty`,
    ),
  bilingualVocabularyDifficulty: (pairingId: string, chapterId: string) =>
    request<VocabularyDifficultyPreview>(
      `/bilingual/${encodeURIComponent(pairingId)}/section/${encodeURIComponent(chapterId)}/vocabulary-difficulty`,
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
  last_read_at?: number;
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

export type BilingualExportStyle = "folded" | "alternating" | "two_column";

export interface BilingualExportOptions {
  style?: BilingualExportStyle;
  font_family?: string;
  custom_css?: string;
  font_asset_id?: string;
}

export interface BilingualReadingPosition {
  pairing_id: string;
  chapter_id: string;
  chapter_index: number;
  group_index: number;
  epub_cfi: string;
  section_href: string;
  scroll_percent: number;
  text_fingerprint: string;
  updated_at: number;
}

export interface BilingualBookmark extends BilingualReadingPosition {
  id: string;
  title: string;
  chapter_title: string;
  preview: string;
  created_at: number;
}

export interface BilingualNavigation {
  current: BilingualReadingPosition | null;
  back_stack: BilingualReadingPosition[];
  forward_stack: BilingualReadingPosition[];
  can_back: boolean;
  can_forward: boolean;
}

export type BilingualPositionInput = Omit<BilingualReadingPosition, "pairing_id" | "chapter_id" | "updated_at">;

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
  readingPosition: (pairingId: string) =>
    request<{ position: BilingualReadingPosition | null }>(
      `/bilingual/${encodeURIComponent(pairingId)}/reading-position`,
    ),
  updateReadingPosition: (pairingId: string, position: BilingualPositionInput) =>
    request<{ position: BilingualReadingPosition }>(
      `/bilingual/${encodeURIComponent(pairingId)}/reading-position`,
      { method: "PUT", body: JSON.stringify(position) },
    ),
  bookmarks: (pairingId: string) =>
    request<{ bookmarks: BilingualBookmark[] }>(
      `/bilingual/${encodeURIComponent(pairingId)}/bookmarks`,
    ),
  addBookmark: (
    pairingId: string,
    position: BilingualPositionInput,
    title = "",
    preview = "",
  ) =>
    request<BilingualBookmark>(`/bilingual/${encodeURIComponent(pairingId)}/bookmarks`, {
      method: "POST",
      body: JSON.stringify({ position, title, preview }),
    }),
  renameBookmark: (pairingId: string, bookmarkId: string, title: string) =>
    request<BilingualBookmark>(
      `/bilingual/${encodeURIComponent(pairingId)}/bookmarks/${encodeURIComponent(bookmarkId)}`,
      { method: "PUT", body: JSON.stringify({ title }) },
    ),
  deleteBookmark: (pairingId: string, bookmarkId: string) =>
    request<{ status: string }>(
      `/bilingual/${encodeURIComponent(pairingId)}/bookmarks/${encodeURIComponent(bookmarkId)}`,
      { method: "DELETE" },
    ),
  navigation: (pairingId: string) =>
    request<{ navigation: BilingualNavigation }>(
      `/bilingual/${encodeURIComponent(pairingId)}/navigation`,
    ),
  recordNavigation: (pairingId: string, position: BilingualPositionInput) =>
    request<{ navigation: BilingualNavigation }>(
      `/bilingual/${encodeURIComponent(pairingId)}/navigation`,
      { method: "POST", body: JSON.stringify(position) },
    ),
  navigateBack: (pairingId: string) =>
    request<{ position: BilingualReadingPosition; navigation: BilingualNavigation }>(
      `/bilingual/${encodeURIComponent(pairingId)}/navigation/back`,
      { method: "POST" },
    ),
  navigateForward: (pairingId: string) =>
    request<{ position: BilingualReadingPosition; navigation: BilingualNavigation }>(
      `/bilingual/${encodeURIComponent(pairingId)}/navigation/forward`,
      { method: "POST" },
    ),
  exportUrl: (pairingId: string) =>
    apiUrl(`${BASE}/bilingual/${encodeURIComponent(pairingId)}/export`),
  uploadFont: (pairingId: string, file: File, family?: string) => {
    const form = new FormData();
    form.append("file", file);
    if (family) form.append("family", family);
    return request<{ font_asset_id: string; family: string }>(
      `${BASE}/bilingual/${encodeURIComponent(pairingId)}/fonts`,
      { method: "POST", body: form },
    );
  },
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
};

export interface TranslationMemoryEntry {
  cache_key: string;
  source_hash: string;
  normalized_source: string;
  target_language: string;
  provider_name: string;
  model_name: string;
  prompt_version: string;
  glossary_version: string;
  translation: string;
  created_at: number;
  updated_at: number;
  hit_count: number;
}

export interface OfflineBookPackage {
  document_id: string;
  title: string;
  author: string;
  size_bytes: number;
  version: string;
  generated_at: number;
}

export interface QueuedLearningOperation {
  id: string;
  operation_type: "add_word" | "translate" | "focus_check";
  idempotency_key: string;
  payload: Record<string, unknown>;
  status: "queued" | "processing" | "completed" | "failed";
  error: string;
  created_at: number;
  updated_at: number;
}

export interface MN4WriteReceipt {
  remote_object_id: string;
  content_hash: string;
  written_at: number;
}

export interface MN4WritebackItem {
  id: string;
  source_type: "word" | "translation";
  source_object_id: string;
  content_hash: string;
  idempotency_key: string;
  model: string;
  status: "pending_confirmation" | "approved" | "applying" | "applied" | "failed" | "conflicted" | "rejected";
  receipt: MN4WriteReceipt | null;
  created_at: number;
  updated_at: number;
}

// ── MN4 Writeback and Offline Packages ─────────────────────────────────

export const offlinePackagesApi = {

  export: (documentId: string) =>
    request<{ exported: boolean; package_path: string; document_id: string }>(`/offline-packages/${encodeURIComponent(documentId)}/export`, {
      method: "POST"
    }),
  list: () => request<{ packages: OfflineBookPackage[] }>("/offline-packages"),
  sync: (operations: QueuedLearningOperation[]) => 
    request<{ synced_count: number }>("/offline-packages/sync", {
      method: "POST",
      body: JSON.stringify({ operations }),
    }),
};

export const mn4WritebackApi = {
  pairDevice: () => request<{ pairing_code: string, expires_at: number }>("/mn4/device/pair", { method: "POST" }),
  syncData: (payload: Record<string, unknown>) => request<{ sync_status: string }>("/mn4/sync", {
    method: "POST",
    body: JSON.stringify(payload),
  }),
  list: () => request<{ writebacks: MN4WritebackItem[] }>("/mn4/writebacks"),
  preview: (writebackIds: string[]) => request<{ previews: Record<string, unknown> }>("/mn4/writebacks/preview", {
    method: "POST",
    body: JSON.stringify({ writeback_ids: writebackIds }),
  }),
  approve: (writebackIds: string[]) => request<{ approved_count: number }>("/mn4/writebacks/approve", {
    method: "POST",
    body: JSON.stringify({ writeback_ids: writebackIds }),
  }),
  pull: () => request<{ pending_items: MN4WritebackItem[] }>("/mn4/writebacks/pull", { method: "POST" }),
  submitReceipt: (receipts: MN4WriteReceipt[]) => request<{ processed_count: number }>("/mn4/writebacks/receipt", {
    method: "POST",
    body: JSON.stringify({ receipts }),
  }),
};
