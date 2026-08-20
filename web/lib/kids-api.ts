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

export interface KidsBootstrapProfile {
  id: string;
  name: string;
  avatar: string;
  age_band: KidsProfile["age_band"];
  has_pin?: boolean;
  device_url?: string;
}

export interface KidsBookAssignment {
  id: string;
  profile_id: string;
  document_id: string;
  document_title: string;
  status: "active" | "hidden";
  available_through_section_id: string;
  available_through_section_index: number;
  content_confirmed: boolean;
  content_confirmed_at?: number;
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
  quiz_best_stars?: number;
  quiz_section_attempts?: Record<string, number>;
  quiz_section_best_scores?: Record<string, number>;
  quiz_section_best_stars?: Record<string, number>;
  quiz_exempt_section_ids?: string[];
  time_spent_seconds: number;
  last_read_at: number;
}

export interface KidsLibraryItem {
  assignment: KidsBookAssignment;
  document: Record<string, unknown>;
  progress: KidsLearningProgress;
}

export interface KidsUsage {
  date?: string;
  used_seconds: number;
  limit_seconds: number;
  bonus_seconds: number;
  remaining_seconds: number;
  limit_reached: boolean;
}

export interface KidsSafeQuestion {
  id: string;
  kind:
    | "recall"
    | "sequence"
    | "inference"
    | "vocabulary"
    | "comprehension"
    | "sight_word";
  question: string;
  choices: string[];
}

export interface KidsQuizGrade {
  score: number;
  total: number;
  section_id?: string;
  stars: number;
  earned_stars?: number;
  is_complete?: boolean;
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
    data: {
      document_id: string;
      available_through_section_id?: string;
      available_through_section_index?: number;
      content_confirmed: boolean;
    },
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

  resetUsage: (profileId: string) =>
    adminRequest<{ usage: KidsUsage }>(`/profiles/${profileId}/usage/reset`, {
      method: "POST",
    }),

  extendUsage: (profileId: string, minutes: number) =>
    adminRequest<{ usage: KidsUsage }>(`/profiles/${profileId}/usage/extend`, {
      method: "POST",
      body: JSON.stringify({ minutes }),
    }),
};

export class KidsApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public detail: unknown,
  ) {
    super(message);
    this.name = "KidsApiError";
  }
}

// ── Child API ──────────────────────────────────────────────────────────────

async function kidsRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const res = await apiFetch(`${KIDS_BASE}${path}`, {
    headers,
    ...init,
    skipAuthRedirect: true,
  });
  if (!res.ok) {
    let detail: unknown = null;
    try {
      detail = (await res.json())?.detail ?? null;
    } catch {}
    throw new KidsApiError(`Kids API error: ${res.status}`, res.status, detail);
  }
  return res.json();
}

export const kidsApi = {
  bootstrap: () => kidsRequest<{ profiles: KidsBootstrapProfile[] }>("/bootstrap"),

  selectProfile: (profileId: string) =>
    kidsRequest<{ profile: KidsProfile }>("/select-profile", {
      method: "POST",
      body: JSON.stringify({ profile_id: profileId }),
    }),

  parentUnlock: (profileId: string, pin: string) =>
    kidsRequest<{ profile: KidsProfile }>("/parent-unlock", {
      method: "POST",
      body: JSON.stringify({ profile_id: profileId, pin }),
    }),

  library: () =>
    kidsRequest<{ library: KidsLibraryItem[]; usage: KidsUsage; profile: KidsProfile }>(
      "/library",
    ),

  getBook: (documentId: string) =>
    kidsRequest<{
      document: Record<string, unknown>;
      progress: KidsLearningProgress;
      usage: KidsUsage;
      profile: KidsProfile;
    }>(
      `/books/${documentId}`,
    ),

  getSection: (documentId: string, sectionId: string) =>
    kidsRequest<Record<string, unknown>>(`/books/${documentId}/sections/${sectionId}`),

  getCoverUrl: (documentId: string) => `${KIDS_BASE}/books/${documentId}/cover`,

  getEpubUrl: (documentId: string) => `${KIDS_BASE}/books/${documentId}/epub`,

  updateProgress: (
    documentId: string,
    data: {
      section_id: string;
      section_index: number;
      scroll_percent: number;
      epub_cfi?: string;
      section_href?: string;
      completed?: boolean;
    },
  ) =>
    kidsRequest<{ progress: KidsLearningProgress }>(`/books/${documentId}/progress`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),

  getQuiz: (documentId: string, sectionId: string, forceRefresh = false) =>
    kidsRequest<{
      questions: KidsSafeQuestion[];
      section_id: string;
      status: "ready" | "exempt";
      message?: string;
    }>(
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

  heartbeat: (documentId: string) =>
    kidsRequest<KidsUsage>("/session/heartbeat", {
      method: "POST",
      body: JSON.stringify({ active: true, document_id: documentId }),
    }),

  logout: () => kidsRequest<{ ok: boolean }>("/session/logout", { method: "POST" }),

  exitVerify: (profileId: string, pin: string) =>
    kidsRequest<{ ok: boolean }>("/exit-verify", {
      method: "POST",
      body: JSON.stringify({ profile_id: profileId, pin }),
    }),
};
