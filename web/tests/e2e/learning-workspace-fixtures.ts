import type { Page } from "@playwright/test";

/**
 * Deterministic LRN-03 / MOD-03 fixtures for the Feynman workspace audit.
 * Representative Chinese content and long identifiers exercise wrap/overflow
 * behaviour at 1440px and 390px.
 */

export const LONG_KP = "贝叶斯更新在医疗诊断与产品 A/B 实验中的证据解释力应用";
export const LONG_SRC_ID = "snapshot-user-material-贝叶斯笔记-2026-08-04-版本三";
export const LONG_MODEL = "openai/gpt-5.6-20260804-prod-edge-custom-推理推理推理推理";

export const EVALUATOR_SNAPSHOT = {
  profile_id: "evaluator-profile-openai-responses-001",
  profile_name: "评估模型（固定）",
  profile_revision: "rev-7",
  requested_provider: "openai",
  requested_api_protocol: "auto",
  requested_model: LONG_MODEL,
  resolved_provider: "openai",
  resolved_api_protocol: "openai_responses",
  resolved_model: LONG_MODEL,
  auto_resolution_reason: "explicit profile protocol",
  base_url_fingerprint: "fp-demo-bayes-notes-001",
  strict_protocol: true,
  prompt_version: "feynman-rubric-v3",
  rubric_version: "3",
  created_at: 1780000000,
};

export const MAP = {
  book_id: "path-001",
  next: {
    action: "assess",
    module_id: "m1",
    module_name: "概率与贝叶斯推断",
    knowledge_point_id: "kp-bayes",
    knowledge_point_name: LONG_KP,
    knowledge_point_type: "concept",
    status: "learning",
    gate: "qualitative",
    mastery: 0,
    threshold: 2,
    reason: "用自己的话解释贝叶斯更新",
    pending_prompt: "",
  },
  projections: {
    "kp-bayes": {
      knowledge_point_id: "kp-bayes",
      mastery_state: "in_progress",
      review_state: "unscheduled",
      active_attempt_id: "att-000000000000001",
      latest_assessment_id: "",
      provisional_since: null,
      stable_since: null,
      next_review_at: null,
      updated_at: 1780000100,
    },
    "kp-prior": {
      knowledge_point_id: "kp-prior",
      mastery_state: "provisional_mastery",
      review_state: "scheduled",
      active_attempt_id: "",
      latest_assessment_id: "as-2",
      provisional_since: 1780000000,
      stable_since: null,
      next_review_at: 1780864000,
      updated_at: 1780000100,
    },
    "kp-likelihood": {
      knowledge_point_id: "kp-likelihood",
      mastery_state: "needs_revision",
      review_state: "due",
      active_attempt_id: "",
      latest_assessment_id: "as-1",
      provisional_since: null,
      stable_since: null,
      next_review_at: 1779900000,
      updated_at: 1780000100,
    },
  },
  active_attempts: {
    "kp-bayes": {
      attempt_id: "att-000000000000001",
      status: "collecting",
      cycle_type: "initial",
      chain_id: "chain-bayes-001",
      map_version_id: "map-v2",
    },
  },
  evidence_summary: {
    "kp-bayes": { count: 2, kinds: ["explanation", "probe_question"] },
  },
  map_version: 2,
  map_version_id: "map-v2",
  source_snapshots: [
    {
      id: LONG_SRC_ID,
      source_type: "user_material",
      material_id: "mat-1",
      locator: "笔记/贝叶斯笔记.md",
      title: "个人笔记：贝叶斯更新",
      content_hash: "sha256-aaaa",
      citation_anchors: ["§2", "§3.1"],
      captured_at: 1780000000,
    },
    {
      id: "snapshot-web-阳性预测值-定义-00000000000000002",
      source_type: "web",
      material_id: "web-1",
      locator: "https://example.invalid/ppv",
      title: "外部补充：阳性预测值定义",
      content_hash: "sha256-bbbb",
      citation_anchors: ["p.18"],
      captured_at: 1780000000,
    },
  ],
  map_versions: [
    {
      id: "map-v2",
      path_id: "path-001",
      version: 2,
      nodes: ["kp-bayes", "kp-prior", "kp-likelihood"],
      edges: [
        { from: "kp-prior", to: "kp-bayes", relation: "prerequisite" },
        { from: "kp-bayes", to: "kp-likelihood", relation: "related" },
      ],
      priorities: { "kp-bayes": 1, "kp-prior": 2, "kp-likelihood": 1 },
      source_snapshot_ids: [LONG_SRC_ID, "snapshot-web-阳性预测值-定义-00000000000000002"],
      confirmed_at: 1780000000,
    },
  ],
  conflicts: [
    {
      id: "conflict-bayes-001",
      path_id: "path-001",
      knowledge_point_ids: ["kp-bayes"],
      claim: "先验概率的定义在两份资料中不一致",
      source_snapshot_ids: [LONG_SRC_ID, "snapshot-web-阳性预测值-定义-00000000000000002"],
      citation_anchors: ["§2", "p.18"],
      version: 1,
      status: "open",
      accepted_snapshot_id: "",
      resolution_note: "",
      resolved_at: null,
      resolved_by: "",
    },
  ],
  updated_at: 1780000100,
  map: {
    counts: { mastered: 0, learning: 2, new: 1, total: 3 },
    due_reviews: 1,
    complete: false,
    modules: [
      {
        id: "m1",
        name: "概率与贝叶斯推断",
        order: 0,
        mastered: 0,
        total: 3,
        knowledge_points: [
          { id: "kp-prior", name: "先验与后验", type: "concept", status: "learning", mastery: 1 },
          { id: "kp-bayes", name: LONG_KP, type: "concept", status: "learning", mastery: 0.5 },
          { id: "kp-likelihood", name: "似然比与阳性预测值", type: "concept", status: "learning", mastery: 0 },
        ],
      },
    ],
  },
};

export const REVIEWS = {
  reviews: [
    {
      id: "rev-1",
      knowledge_point_id: "kp-prior",
      knowledge_type: "concept",
      due_at: 1780864000,
      priority: 3,
      state: { interval_index: 0, consecutive_correct: 1, consecutive_wrong: 0, next_review_at: 1780864000 },
    },
    {
      id: "rev-2",
      knowledge_point_id: "kp-likelihood",
      knowledge_type: "concept",
      due_at: 1779900000,
      priority: 1,
      state: { interval_index: 0, consecutive_correct: 0, consecutive_wrong: 1, next_review_at: 1779900000 },
    },
  ],
  due_reviews: [
    {
      id: "rev-2",
      knowledge_point_id: "kp-likelihood",
      knowledge_type: "concept",
      due_at: 1779900000,
      priority: 1,
      state: { interval_index: 0, consecutive_correct: 0, consecutive_wrong: 1, next_review_at: 1779900000 },
    },
  ],
  due_count: 1,
  needs_revision: ["kp-likelihood"],
  updated_at: 1780000100,
};

export const ATTEMPT = {
  attempt: {
    id: "att-000000000000001",
    knowledge_point_id: "kp-bayes",
    cycle_type: "initial",
    status: "collecting",
    invalidated_reason: "",
    knowledge_point_version: 1,
    map_version_id: "map-v2",
    source_snapshot_ids: [LONG_SRC_ID],
    supersedes_attempt_id: "",
    session_id: "path-001",
    started_turn_id: "turn-7",
    active_chain_id: "chain-bayes-001",
    max_help_level: "hint",
    evaluator_snapshot: EVALUATOR_SNAPSHOT,
    created_at: 1780000000,
    updated_at: 1780000100,
    closed_at: null,
  },
  evidence: [
    {
      id: "evidence-000000000000001",
      attempt_id: "att-000000000000001",
      chain_id: "chain-bayes-001",
      kind: "explanation",
      session_id: "path-001",
      turn_id: "turn-7",
      message_id: "msg-1",
      event_seq: 1,
      input_mode: "text",
      transcript_confirmed: true,
      content_snapshot: "贝叶斯更新不是推翻旧判断，而是把原来的相信程度与新证据的解释力结合。",
      content_hash: "h-1",
      question_evidence_id: "",
      source_citations: [{ source_snapshot_id: LONG_SRC_ID, anchor: "§2" }],
      help_level: null,
      created_at: 1780000010,
    },
    {
      id: "evidence-000000000000002",
      attempt_id: "att-000000000000001",
      chain_id: "chain-bayes-001",
      kind: "probe_question",
      session_id: "path-001",
      turn_id: "turn-7",
      message_id: "msg-2",
      event_seq: 2,
      input_mode: "text",
      transcript_confirmed: true,
      content_snapshot: "如果检测结果是阳性，为什么不能直接说患病概率很高？请不用公式解释。",
      content_hash: "h-2",
      question_evidence_id: "",
      source_citations: [],
      help_level: null,
      created_at: 1780000020,
    },
  ],
  assessments: [],
  gaps: [
    {
      id: "gap-0001",
      knowledge_point_id: "kp-bayes",
      label: "灵敏度与阳性预测值的条件方向仍含糊",
      description: "需要区分给定疾病下的阳性率与给定阳性下的患病率。",
      evidence_ids: ["evidence-000000000000002"],
      source_citations: [{ source_snapshot_id: LONG_SRC_ID, anchor: "§3.1" }],
      status: "active",
      priority: 1,
      first_seen_at: 1780000030,
      last_seen_at: 1780000030,
      resolved_at: null,
    },
  ],
  challenges: [],
  audit: [{ seq: 1, event_type: "attempt_start", summary: "attempt started", at: 1780000000 }],
  projection: {
    knowledge_point_id: "kp-bayes",
    mastery_state: "in_progress",
    review_state: "unscheduled",
    active_attempt_id: "att-000000000000001",
    latest_assessment_id: "",
    provisional_since: null,
    stable_since: null,
    next_review_at: null,
    updated_at: 1780000100,
  },
};

export const LLM_OPTIONS = {
  active: { profile_id: "teaching-profile-001", model_id: LONG_MODEL },
  options: [
    {
      profile_id: "teaching-profile-001",
      profile_name: "教学模型",
      model_id: LONG_MODEL,
      model_name: LONG_MODEL,
      model: LONG_MODEL,
      provider: "openai",
      provider_label: "OpenAI",
      context_window: 128000,
      is_active_default: true,
      api_protocol: "openai_responses",
      strict_protocol: true,
    },
  ],
};

export const AUTH_STATUS = { enabled: false, authenticated: false };
export const EMPTY_SESSIONS = { sessions: [] };
export const EMPTY_KNOWLEDGE_BASES = { knowledge_bases: [] };
export const EMPTY_TOOLS = { enabled_optional_tools: [] };
export const SUBAGENT_SETTINGS = { consult_budget: 2 };
export const ATTACHMENT_LIMITS = {
  effective: { max_file_bytes: 10 * 1024 * 1024, max_total_bytes: 30 * 1024 * 1024 },
};

/** Session detail for /home/path-001 — the chat page the workspace hands off to. */
export const SESSION_DETAIL = {
  id: "path-001",
  session_id: "path-001",
  title: "贝叶斯更新学习",
  created_at: 1780000000,
  updated_at: 1780000100,
  status: "idle",
  preferences: {
    capability: "mastery_path",
    tools: [],
    knowledge_bases: [],
    language: "en",
    persona: "",
  },
  messages: [],
  active_turns: [],
};

/**
 * Deterministic stubs for the global app-shell requests (auth status, session
 * list, capability probe, LLM options, tools, KB list, subagent settings,
 * chat-attachment limits) that every page fires through its layout/sidebar.
 *
 * The audit is fail-closed: there is no permissive `/api/** -> 200 {}`
 * catch-all. Every request the learning and chat handoff flows exercise is
 * modeled explicitly below, and any *unrecognized* `/api/*` request aborts,
 * which the browser surfaces as a `Failed to load resource` console error and
 * fails the audit's console/page-error assertion. This keeps a new production
 * request from passing the audit merely because it received a successful empty
 * body (the class of integration error that previously produced the Next dev
 * overlay).
 *
 * Playwright matches the last-registered route first, so the fail-closed
 * fallback is registered before every more-specific stub below it.
 */
export async function mockGlobalShellApis(page: Page) {
  // Fail-closed fallback for any `/api/*` request not explicitly modeled. An
  // abort is a network failure, not a 2xx, so the audit fails loudly instead of
  // hiding the missing model behind an empty body.
  await page.route("**/api/**", (route) => route.abort("failed"));
  // Every explicit stub below returns 2xx: a 4xx/5xx from the mocked layer
  // would itself log a browser console error ("Failed to load resource") and
  // fail the audit's console assertion, even though the app handles it
  // gracefully.
  await page.route("**/api/v1/settings/chat-attachments", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(ATTACHMENT_LIMITS) }),
  );
  await page.route("**/api/v1/settings", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
  );
  await page.route("**/api/v1/settings/llm-options", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(LLM_OPTIONS) }),
  );
  await page.route("**/api/v1/auth/status", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(AUTH_STATUS) }),
  );
  await page.route("**/api/v1/tools", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(EMPTY_TOOLS) }),
  );
  await page.route("**/api/v1/subagents/settings", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(SUBAGENT_SETTINGS) }),
  );
  await page.route("**/api/v1/knowledge/list", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(EMPTY_KNOWLEDGE_BASES) }),
  );
  // `*` globs do not cross `/`, so the list/detail session endpoints need a
  // regex matcher: `/api/v1/sessions`, `/api/v1/sessions?limit=…` and
  // `/api/v1/sessions/path-001` all resolve here.
  await page.route(/\/api\/v1\/sessions(?:\/|\?|$)/, (route) => {
    const url = route.request().url();
    const detail = /\/api\/v1\/sessions\/[^/]+$/.test(url);
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(detail ? SESSION_DETAIL : EMPTY_SESSIONS),
    });
  });
}

export async function mockLearningApis(page: Page) {
  await mockGlobalShellApis(page);
  await page.route("**/api/v1/learning/progress/*/map", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(MAP) }),
  );
  await page.route("**/api/v1/learning/progress/*/reviews", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(REVIEWS) }),
  );
  await page.route("**/api/v1/learning/progress/*/attempts/*", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(ATTEMPT) }),
  );
  // UI-02 card collection + media fixtures so the base workspace audit renders
  // an empty (or card-free) knowledge-card surface without a fail-closed abort.
  await page.route("**/api/v1/learning/progress/*/knowledge-cards", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ cards: [], updated_at: 1780000100 }) });
    }
    return route.fulfill({ status: 405, contentType: "application/json", body: "{}" });
  });
  await page.route("**/api/v1/generated-artifacts", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        artifacts: [],
        quota: { used_bytes: 0, limit_bytes: 1000000, reclaimable_bytes: 0, file_count: 0, remaining_bytes: 1000000 },
      }),
    }),
  );
}

/* ────────────────────────────────────────────────────────────────────────
 * UI-02 knowledge-card fixtures.
 *
 * Deterministic owner-scoped card collection, writable + connected KB list,
 * generated-artifact payload, and stateful mutations so the desktop center
 * editor, mobile full-screen editor, publish/retry/reconcile/retract and
 * confirmation dialogs all render without a live provider or KB volume.
 * ──────────────────────────────────────────────────────────────────────── */

export const KNOWLEDGE_BASES = [
  { name: "我的学习知识库", is_default: true, status: "ready", metadata: { needs_reindex: false }, available: true, read_only: false, assigned: false },
  { name: "团队网络原理", status: "connected", metadata: { type: "linked" }, read_only: true, available: true, assigned: false },
  { name: "课程公共库", status: "error", metadata: { last_error: "index missing" }, read_only: false, available: true, assigned: false },
];

export const GENERATED_ARTIFACTS = {
  artifacts: [
    {
      id: "art-00000000000000000001",
      job_id: "job-00000000000000000001",
      session_id: "path-001",
      turn_id: "turn-7",
      provider: "openai",
      profile: "media-profile",
      protocol: "openai_responses",
      model: "gpt-image-2",
      operation: "generate",
      original_prompt: "TCP 三次握手时序示意",
      revised_prompt: "",
      sha256: "a".repeat(64),
      mime_type: "image/png",
      width: 512,
      height: 512,
      size_bytes: 2048,
      created_at: 1780000250,
      gc_candidate_since: null,
      is_gc_candidate: false,
      reference_count: 1,
      references: [],
      preview_url: "/api/v1/generated-artifacts/art-00000000000000000001/file?disposition=inline",
      download_url: "/api/v1/generated-artifacts/art-00000000000000000001/file?disposition=attachment",
    },
  ],
  quota: { used_bytes: 2048, limit_bytes: 1000000, reclaimable_bytes: 0, file_count: 1, remaining_bytes: 997952 },
};

export function kcCard(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    card_id: "card-bayes-draft",
    knowledge_point_id: "kp-bayes",
    status: "draft",
    revision: 1,
    version: 0,
    generation_locked_by_user_edit: false,
    draft_generation_status: "ready",
    title: "为什么 TCP 需要三次握手",
    body: "三次握手让双方确认双向可达，并同步连接双方的初始序列号。两次握手无法让服务端确认自己的响应已被客户端接收。",
    content_hash: "sha256-card-body",
    source_snapshot_ids: [LONG_SRC_ID, "snapshot-web-阳性预测值-定义-00000000000000002"],
    evidence_ids: ["evidence-000000000000001"],
    artifact_ids: ["art-00000000000000000001"],
    source_count: 2,
    evidence_count: 1,
    artifact_count: 1,
    stable_assessment_id: "as-stable-1",
    stable_assessment_sequence: 3,
    target_kb_name: null,
    document_rel_path: null,
    document_sha256: null,
    publication_key: null,
    quarantine_rel_path: null,
    retraction_request_id: null,
    retraction_operation_id: null,
    cleanup_status: "",
    cleanup_error: null,
    confirmed_at: null,
    published_at: null,
    stale_at: null,
    retracted_at: null,
    error_code: null,
    sanitized_error: null,
    latest_generation_attempt: {
      id: "gen-attempt-1",
      status: "succeeded",
      generation_attempt_no: 1,
      retry_of_generation_attempt_id: null,
      input_card_revision: 1,
      model_invocation_id: "inv-00000000000000000001",
      output_hash: "sha256-output",
      error_code: null,
      sanitized_error: null,
      created_at: 1780000200,
      started_at: 1780000201,
      finished_at: 1780000205,
    },
    model_identity: {
      provider: "openai",
      profile: "evaluator-profile-openai-responses-001",
      model: LONG_MODEL,
      protocol: "openai_responses",
      base_url_fingerprint: "fp-demo-bayes-notes-001",
      strict_protocol: true,
      rubric_version: "3",
    },
    sources: [
      { id: LONG_SRC_ID, title: "个人笔记：贝叶斯更新", locator: "笔记/贝叶斯笔记.md", anchors: ["§2", "§3.1"] },
      { id: "snapshot-web-阳性预测值-定义-00000000000000002", title: "外部补充：阳性预测值定义", locator: "https://example.invalid/ppv", anchors: ["p.18"] },
    ],
    artifacts: [
      {
        id: "art-00000000000000000001",
        available: true,
        mime_type: "image/png",
        width: 512,
        height: 512,
        sha256: "a".repeat(64),
        preview_url: "/api/v1/generated-artifacts/art-00000000000000000001/file?disposition=inline",
        download_url: "/api/v1/generated-artifacts/art-00000000000000000001/file?disposition=attachment",
        references: [],
        provider: "openai",
        model: "gpt-image-2",
      },
    ],
    occupies_slot: true,
    ...overrides,
  };
}

/** The full owner-visible collection: one card per approved state. */
export const KNOWLEDGE_CARDS = [
  kcCard(),
  kcCard({
    card_id: "card-published",
    knowledge_point_id: "kp-prior",
    status: "published",
    title: "先验与后验",
    target_kb_name: "我的学习知识库",
    document_rel_path: "learning_cards/card-published-v1.md",
    document_sha256: "sha256-doc-pub",
    publication_key: "key-card-published-1",
    confirmed_at: 1780000300,
    published_at: 1780000300,
    revision: 1,
  }),
  kcCard({
    card_id: "card-publish-failed",
    knowledge_point_id: "kp-likelihood",
    status: "publish_failed",
    title: "似然比与阳性预测值",
    target_kb_name: "我的学习知识库",
    error_code: "kb_busy",
    sanitized_error: "Knowledge base lease is busy; retry later.",
    revision: 2,
  }),
  kcCard({
    card_id: "card-stale",
    knowledge_point_id: "kp-stale",
    status: "stale_evidence",
    title: "旧的掌握证据草稿",
    stale_at: 1780000400,
    revision: 1,
  }),
  kcCard({
    card_id: "card-reconcile",
    knowledge_point_id: "kp-reconcile",
    status: "reconcile_required",
    title: "发布结果待核对",
    target_kb_name: "我的学习知识库",
    revision: 1,
  }),
  kcCard({
    card_id: "card-retracting",
    knowledge_point_id: "kp-retracting",
    status: "retracting",
    title: "正在撤回的卡片",
    target_kb_name: "我的学习知识库",
    document_rel_path: "learning_cards/card-retracting-v1.md",
    revision: 1,
  }),
];

function mutationResult(card: Record<string, unknown>, status: string, revision: number) {
  return {
    card_id: card.card_id,
    status,
    replayed: false,
    revision,
    target_kb_name: card.target_kb_name ?? null,
    document_rel_path: card.document_rel_path ?? null,
    document_sha256: card.document_sha256 ?? null,
    publication_key: card.publication_key ?? null,
    quarantine_rel_path: card.quarantine_rel_path ?? null,
    retraction_request_id: card.retraction_request_id ?? null,
    retraction_operation_id: card.retraction_operation_id ?? null,
    confirmed_at: card.confirmed_at ?? null,
    published_at: card.published_at ?? null,
    retracted_at: card.retracted_at ?? null,
    cleanup_status: card.cleanup_status ?? "",
    cleanup_error: card.cleanup_error ?? null,
    error_code: card.error_code ?? null,
    sanitized_error: card.sanitized_error ?? null,
  };
}

/**
 * Stateful knowledge-card mock. Registered after ``mockLearningApis`` so the
 * knowledge/list, generated-artifacts and knowledge-card routes take
 * precedence over the shell stubs. Every mutation advances the shared in-test
 * collection so the post-mutation authoritative refresh returns the new state.
 */
// 1×1 transparent PNG (70 bytes) so the authenticated artifact file route
// renders a valid image without a live media volume.
const TINY_PNG = Buffer.from([
  0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0x00, 0x00, 0x0d,
  0x49, 0x48, 0x44, 0x52, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
  0x08, 0x04, 0x00, 0x00, 0x00, 0xb5, 0x1c, 0x0c, 0x02, 0x00, 0x00, 0x00,
  0x0b, 0x49, 0x44, 0x41, 0x54, 0x78, 0xda, 0x63, 0x64, 0xf8, 0xcf, 0x50,
  0x0f, 0x00, 0x03, 0x86, 0x01, 0x80, 0x5a, 0x34, 0x7d, 0x6b, 0x00, 0x00,
  0x00, 0x00, 0x49, 0x45, 0x4e, 0x44, 0xae, 0x42, 0x60, 0x82,
]);

export async function mockKnowledgeCardApis(page: Page) {
  await page.route("**/api/v1/knowledge/list", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(KNOWLEDGE_BASES) }),
  );
  await page.route("**/api/v1/generated-artifacts", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(GENERATED_ARTIFACTS) }),
  );
  // Authenticated same-user artifact bytes (MED-03 §12.3) so the editor's
  // image thumbnails load without a live media volume.
  await page.route("**/api/v1/generated-artifacts/*/file*", (route) =>
    route.fulfill({ status: 200, contentType: "image/png", body: TINY_PNG }),
  );

  const state: Array<Record<string, unknown>> = KNOWLEDGE_CARDS.map((c) => ({
    ...c,
    sources: [...c.sources],
    artifacts: [...c.artifacts],
  }));
  const cardById = (id: string) => state.find((c) => c.card_id === id);
  const fulfill = (route: { fulfill: (o: unknown) => unknown }, body: unknown, status = 200) =>
    route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

  await page.route("**/api/v1/learning/progress/*/knowledge-cards**", async (route: any) => {
    const url = new URL(route.request().url());
    const method = route.request().method();
    const base = "/api/v1/learning/progress/path-001/knowledge-cards";
    const rest = url.pathname.slice(base.length);
    if (!rest || rest === "/") {
      if (method === "GET") return fulfill(route, { cards: state, updated_at: 1780000100 });
      return route.fulfill({ status: 405, contentType: "application/json", body: "{}" });
    }
    const parts = rest.split("/").filter(Boolean);
    const card = cardById(parts[0]);
    if (!card) return route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "card not found" }) });
    const action = parts[1] ?? "";
    const body = method !== "GET" && route.request().postData() ? route.request().postDataJSON() : null;

    if (action === "" && method === "PATCH") {
      card.revision = Number(card.revision) + 1;
      card.generation_locked_by_user_edit = true;
      if (body && body.title !== undefined) card.title = body.title;
      if (body && body.body !== undefined) card.body = body.body;
      card.draft_generation_status = "ready";
      return fulfill(route, card);
    }
    if (action === "discard" && method === "POST") {
      card.status = "discarded";
      return fulfill(route, card);
    }
    if (action === "retry-generation" && method === "POST") {
      card.draft_generation_status = "queued";
      card.latest_generation_attempt = {
        id: `gen-attempt-${Number(card.revision) + 1}`,
        status: "queued",
        generation_attempt_no: Number((card.latest_generation_attempt as { generation_attempt_no: number })?.generation_attempt_no ?? 1) + 1,
        retry_of_generation_attempt_id: (card.latest_generation_attempt as { id: string })?.id ?? null,
        input_card_revision: card.revision,
        model_invocation_id: null,
        output_hash: null,
        error_code: null,
        sanitized_error: null,
        created_at: 1780000500,
        started_at: null,
        finished_at: null,
      };
      return fulfill(route, card);
    }
    if (action === "publish" && method === "POST") {
      card.status = "published";
      card.target_kb_name = body?.target_kb_name ?? card.target_kb_name ?? "我的学习知识库";
      card.document_rel_path = `learning_cards/${card.card_id}-v${card.revision}.md`;
      card.document_sha256 = "sha256-doc";
      card.publication_key = `key-${card.card_id}-${card.revision}`;
      card.confirmed_at = 1780000600;
      card.published_at = 1780000600;
      card.error_code = null;
      card.sanitized_error = null;
      return fulfill(route, mutationResult(card, "published", Number(card.revision)));
    }
    if (action === "retry-publish" && method === "POST") {
      card.status = "published";
      card.error_code = null;
      card.sanitized_error = null;
      card.published_at = 1780000700;
      return fulfill(route, mutationResult(card, "published", Number(card.revision)));
    }
    if (action === "reconcile-publication" && method === "POST") {
      card.status = "published";
      card.error_code = null;
      card.sanitized_error = null;
      return fulfill(route, mutationResult(card, "published", Number(card.revision)));
    }
    if (action === "retract" && method === "POST") {
      card.status = "retracted";
      card.retracted_at = 1780000800;
      card.retraction_request_id = "req-retract-1";
      card.retraction_operation_id = "op-retract-1";
      return fulfill(route, mutationResult(card, "retracted", Number(card.revision)));
    }
    if (action === "reconcile-retraction" && method === "POST") {
      card.status = "retracted";
      card.retracted_at = 1780000900;
      return fulfill(route, mutationResult(card, "retracted", Number(card.revision)));
    }
    return route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "unknown route" }) });
  });

  // Server-derived draft create/resume.
  await page.route("**/api/v1/learning/progress/*/knowledge-points/*/knowledge-card", (route: any) => {
    const card = kcCard({ card_id: "card-new-draft", title: "新建草稿", status: "draft", created: true });
    state.push(card);
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(card) });
  });
}
