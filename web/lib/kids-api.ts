import { apiFetch } from "@/lib/api";

const ADMIN_BASE = "/api/v1/kids-admin";
const KIDS_BASE = "/api/v1/kids";

// ── Types ──────────────────────────────────────────────────────────────────

export interface KidsProfile {
  id: string;
  name: string;
  avatar: string;
  birth_date: string;
  age: number;
  age_band: "3-5" | "6-8" | "9-12";
  help_language: "en" | "zh";
  narration_rate: number;
  daily_limit_minutes: number;
  has_pin?: boolean;
  created_at?: number;
  device_url?: string;
  updated_at?: number;
}

export interface KidsBookAssignment {
  id: string;
  profile_id: string;
  document_id: string;
  document_title: string;
  status: "active" | "hidden";
  available_through_section_id: string;
  available_through_section_index: number;
  sort_order: number;
  is_next_read: boolean;
}

export interface KidsLearningProgress {
  profile_id: string;
  document_id: string;
  current_section_id: string;
  current_section_index: number;
  scroll_percent: number;
  epub_cfi: string;
  section_href: string;
  completed_section_ids: string[];
  total_stars: number;
  quiz_attempts: number;
  quiz_best_score: number;
  time_spent_seconds: number;
  last_read_at: number;
}

export interface KidsLibraryItem {
  assignment: KidsBookAssignment;
  document: Record<string, unknown>;
  progress: KidsLearningProgress;
}

export interface KidsSafeQuestion {
  id: string;
  kind: "comprehension" | "sight_word" | "sequence";
  question: string;
  choices: string[];
}

export interface KidsQuizGrade {
  score: number;
  total: number;
  stars: number;
  per_question: { id: string; correct: boolean; explanation: string }[];
  encouragements: string[];
}

// ── Admin (parent) API ─────────────────────────────────────────────────────

async function adminRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await apiFetch(`${ADMIN_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) throw new Error(`Admin API error: ${res.status}`);
  return res.json();
}

export const kidsAdminApi = {
  listProfiles: () => adminRequest<{ profiles: KidsProfile[] }>("/profiles"),

  createProfile: (data: {
    name: string;
    avatar?: string;
    birth_date?: string;
    help_language?: string;
    narration_rate?: number;
    daily_limit_minutes?: number;
    parent_pin?: string;
  }) => adminRequest<{ profile: KidsProfile }>("/profiles", {
    method: "POST",
    body: JSON.stringify(data),
  }),

  updateProfile: (id: string, data: Record<string, unknown>) =>
    adminRequest<{ profile: KidsProfile }>(`/profiles/${id}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),

  deleteProfile: (id: string) =>
    adminRequest<{ deleted: boolean }>(`/profiles/${id}`, { method: "DELETE" }),

  verifyPin: (profileId: string, pin: string) =>
    adminRequest<{ verified: boolean }>(`/profiles/${profileId}/verify-pin`, {
      method: "POST",
      body: JSON.stringify({ pin }),
    }),

  listAssignedBooks: (profileId: string) =>
    adminRequest<{ library: KidsLibraryItem[] }>(`/profiles/${profileId}/books`),

  assignBook: (
    profileId: string,
    data: { document_id: string; available_through_section_id?: string; available_through_section_index?: number },
  ) =>
    adminRequest<{ assignment: KidsBookAssignment }>(`/profiles/${profileId}/books`, {
      method: "POST",
      body: JSON.stringify(data),
    }),

  updateAssignment: (profileId: string, documentId: string, data: Record<string, unknown>) =>
    adminRequest<{ assignment: KidsBookAssignment }>(
      `/profiles/${profileId}/books/${documentId}`,
      { method: "PUT", body: JSON.stringify(data) },
    ),

  unassignBook: (profileId: string, documentId: string) =>
    adminRequest<{ deleted: boolean }>(
      `/profiles/${profileId}/books/${documentId}`,
      { method: "DELETE" },
    ),

  adultLibrary: () => adminRequest<{ documents: Record<string, unknown>[] }>("/library"),

  learningReport: (profileId: string) =>
    adminRequest<Record<string, unknown>>(`/profiles/${profileId}/report`),
};

// ── Child API ──────────────────────────────────────────────────────────────

async function kidsRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const token = typeof window !== "undefined" ? localStorage.getItem("dt_kids_token") : null;
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await apiFetch(`${KIDS_BASE}${path}`, {
    headers,
    ...init,
  });
  if (!res.ok) throw new Error(`Kids API error: ${res.status}`);
  return res.json();
}

export const kidsApi = {
  bootstrap: () => kidsRequest<{ profiles: KidsProfile[] }>("/bootstrap"),

  selectProfile: (profileId: string) =>
    kidsRequest<{ token: string; profile: KidsProfile }>("/select-profile", {
      method: "POST",
      body: JSON.stringify({ profile_id: profileId }),
    }),

  parentUnlock: (profileId: string, pin: string) =>
    kidsRequest<{ token: string; profile: KidsProfile }>("/parent-unlock", {
      method: "POST",
      body: JSON.stringify({ profile_id: profileId, pin }),
    }),

  library: (profileId: string) =>
    kidsRequest<{ library: KidsLibraryItem[] }>("/library", {
      headers: { "X-Profile-Id": profileId },
    }),

  getBook: (documentId: string) =>
    kidsRequest<{ document: Record<string, unknown>; progress: KidsLearningProgress }>(
      `/books/${documentId}`,
    ),

  getSection: (documentId: string, sectionId: string) =>
    kidsRequest<Record<string, unknown>>(`/books/${documentId}/sections/${sectionId}`),

  getCoverUrl: (documentId: string) => `${KIDS_BASE}/books/${documentId}/cover`,

  updateProgress: (
    documentId: string,
    data: {
      section_id: string;
      section_index: number;
      scroll_percent: number;
      epub_cfi?: string;
      section_href?: string;
      time_delta?: number;
      completed?: boolean;
    },
  ) =>
    kidsRequest<{ progress: KidsLearningProgress }>(`/books/${documentId}/progress`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),

  getQuiz: (documentId: string, sectionId: string, forceRefresh = false) =>
    kidsRequest<{ questions: KidsSafeQuestion[]; section_id: string }>(
      `/books/${documentId}/quiz`,
      { method: "POST", body: JSON.stringify({ section_id: sectionId, force_refresh: forceRefresh }) },
    ),

  submitQuiz: (documentId: string, sectionId: string, answers: number[]) =>
    kidsRequest<KidsQuizGrade>(`/books/${documentId}/quiz/submit`, {
      method: "POST",
      body: JSON.stringify({ section_id: sectionId, answers }),
    }),

  translate: (text: string, targetLanguage = "Chinese") =>
    kidsRequest<{ translation: string }>("/translate", {
      method: "POST",
      body: JSON.stringify({ text, target_language: targetLanguage }),
    }),

  exitVerify: (profileId: string, pin: string) =>
    kidsRequest<{ ok: boolean }>("/exit-verify", {
      method: "POST",
      body: JSON.stringify({ profile_id: profileId, pin }),
    }),
};
