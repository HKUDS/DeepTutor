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

export interface KidsBootstrapResponse {
  authenticated: boolean;
  profile?: KidsProfile;
  pairing_required?: boolean;
  profiles?: KidsBootstrapProfile[];
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

export interface KidsFamilyLibraryItem {
  document: {
    id: string;
    title: string;
    author?: string;
    source_filename: string;
    source_format: string;
    total_chars: number;
    total_words: number;
    reading_mode: "chapters" | "chunks";
    sections: Array<{ id: string; title: string; index: number; checkpoint_kind?: string }>;
    cover_url?: string;
    created_at?: number;
    updated_at?: number;
  };
  entry: {
    document_id: string;
    scopes: ("personal" | "kids_family")[];
    kids_review_status: "pending" | "approved" | "archived";
    approved_age_bands: ("3-5" | "6-8" | "9-12")[];
    reviewed_at: number;
    reviewer_note: string;
    source_scope: "personal" | "kids_upload";
    created_at: number;
    updated_at: number;
  };
  assigned_profiles: Array<{ id: string; name: string }>;
  assigned_count: number;
}

export interface KidsDeviceSessionItem {
  id: string;
  profile_id: string;
  profile_name: string;
  avatar: string;
  device_name: string;
  created_at: number;
  last_seen_at: number;
  expires_at: number;
}

export interface KidsPairingCodeResponse {
  code: string;
  profile_id: string;
  profile_name: string;
  expires_at: number;
  ttl_seconds: number;
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
  if (!res.ok) {
    let detail = "";
    try {
      const data = await res.json();
      if (typeof data?.detail === "string") {
        detail = data.detail;
      } else if (Array.isArray(data?.detail)) {
        detail = data.detail.map((d: any) => d.msg || JSON.stringify(d)).join("; ");
      } else if (data?.detail) {
        detail = JSON.stringify(data.detail);
      }
    } catch {}
    throw new Error(detail || `Admin API error: ${res.status}`);
  }
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

  // Family Kids Library management
  getFamilyLibrary: () =>
    adminRequest<{ items: KidsFamilyLibraryItem[]; documents: Record<string, unknown>[] }>("/library"),

  importKidsBook: async (
    file: File,
    options?: { auto_approve?: boolean; age_bands?: string },
  ): Promise<{ document: Record<string, unknown> }> => {
    const formData = new FormData();
    formData.append("file", file);
    if (options?.auto_approve) formData.append("auto_approve", "true");
    if (options?.age_bands) formData.append("age_bands", options.age_bands);
    const res = await apiFetch(`${ADMIN_BASE}/library/import`, {
      method: "POST",
      body: formData,
    });
    if (!res.ok) {
      let detail = "";
      try {
        const data = await res.json();
        detail = typeof data?.detail === "string" ? data.detail : JSON.stringify(data?.detail);
      } catch {}
      throw new Error(detail || `Import failed: ${res.status}`);
    }
    return res.json();
  },

  reviewBook: (
    documentId: string,
    data: {
      status: "pending" | "approved" | "archived";
      approved_age_bands?: ("3-5" | "6-8" | "9-12")[];
      reviewer_note?: string;
    },
  ) =>
    adminRequest<{ entry: Record<string, unknown> }>(`/library/${documentId}/review`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),

  assignToProfiles: (
    documentId: string,
    data: {
      profile_ids: string[];
      available_through_section_index?: number;
      content_confirmed?: boolean;
    },
  ) =>
    adminRequest<{ assignments: KidsBookAssignment[]; assigned_profile_ids: string[] }>(
      `/library/${documentId}/assign`,
      { method: "POST", body: JSON.stringify(data) },
    ),

  shareFromPersonal: (
    documentId: string,
    data?: { auto_approve?: boolean; approved_age_bands?: string[]; reviewer_note?: string },
  ) =>
    adminRequest<{ entry: Record<string, unknown> }>(`/library/from-personal/${documentId}`, {
      method: "POST",
      body: JSON.stringify(data || {}),
    }),

  shareToPersonal: (documentId: string) =>
    adminRequest<{ entry: Record<string, unknown> }>(`/library/${documentId}/add-to-personal`, {
      method: "POST",
    }),

  archiveBook: (documentId: string) =>
    adminRequest<{ entry: Record<string, unknown> }>(`/library/${documentId}/archive`, {
      method: "POST",
    }),

  unarchiveBook: (documentId: string) =>
    adminRequest<{ entry: Record<string, unknown> }>(`/library/${documentId}/unarchive`, {
      method: "POST",
    }),

  purgeBook: (documentId: string, confirmTitle?: string) =>
    adminRequest<{ purged: boolean; kept_in_personal: boolean }>(`/library/${documentId}/purge`, {
      method: "POST",
      body: JSON.stringify({ confirm_title: confirmTitle || "" }),
    }),

  listPersonalCandidates: () =>
    adminRequest<{ candidates: Record<string, unknown>[] }>("/library/personal-candidates"),

  // Device pairing & session management
  createDevicePairing: (profileId: string, ttlSeconds = 600) =>
    adminRequest<{ pairing: KidsPairingCodeResponse }>("/devices/pair", {
      method: "POST",
      body: JSON.stringify({ profile_id: profileId, ttl_seconds: ttlSeconds }),
    }),

  listDeviceSessions: () =>
    adminRequest<{ devices: KidsDeviceSessionItem[] }>("/devices"),

  revokeDeviceSession: (sessionId: string) =>
    adminRequest<{ revoked: boolean }>(`/devices/${sessionId}`, {
      method: "DELETE",
    }),

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
  bootstrap: () => kidsRequest<KidsBootstrapResponse>("/bootstrap"),

  pairDevice: (code: string, deviceName?: string) =>
    kidsRequest<{ token: string; expires_at: number; profile: KidsProfile }>("/pair", {
      method: "POST",
      body: JSON.stringify({ code, device_name: deviceName || "Kids Device" }),
    }),

  getProfilePublicInfo: (profileId: string) =>
    kidsRequest<{ profile: KidsBootstrapProfile }>(`/profile/${profileId}`),

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
