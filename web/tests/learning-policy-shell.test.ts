import assert from "node:assert/strict";
import test from "node:test";

import { authStatusStateFromStatus } from "../hooks/useAuthStatus";
import { loadSidebarSummaries } from "../lib/sidebar-summaries";
import type { SessionSummary } from "../lib/session-api";
import { settingsAccessFromAuthStatus } from "../features/settings/navigation/settings-access";
import {
  isSettingsCategoryVisible,
  SETTINGS_CATEGORIES,
} from "../features/settings/navigation/settings-nav";
import {
  isNavEntryAllowedForLearningPolicy,
  NAV_BY_HREF,
} from "../components/sidebar/nav-entries";

const policy = {
  age_band: "13-15",
  locked_persona: "teacher",
  allowed_capabilities: ["chat", "immersive_reading"],
  default_capability: "immersive_reading",
  allowed_surfaces: ["chat", "reading"],
};

test("auth state preserves the server learning policy", () => {
  const state = authStatusStateFromStatus({
    enabled: true,
    authenticated: true,
    user_id: "learner-1",
    role: "user",
    preset: "standard",
    learning_policy: policy,
  });

  assert.deepEqual(state.learningPolicy, policy);
  assert.deepEqual(authStatusStateFromStatus(null), {
    enabled: false,
    authenticated: false,
    isAdmin: false,
    userId: null,
    learningPolicy: null,
    statusAvailable: false,
    loading: false,
  });
});

test("learning policy drives the sidebar and redacted settings document", () => {
  for (const href of ["/chat", "/reading", "/settings"]) {
    assert.equal(
      isNavEntryAllowedForLearningPolicy(NAV_BY_HREF.get(href)!, policy),
      true,
      href,
    );
  }
  for (const href of [
    "/partners",
    "/agents",
    "/co-writer",
    "/books",
    "/mastery",
    "/space",
    "/memory",
    "/knowledge-bases",
  ]) {
    assert.equal(
      isNavEntryAllowedForLearningPolicy(NAV_BY_HREF.get(href)!, policy),
      false,
      href,
    );
  }
  assert.equal(
    isNavEntryAllowedForLearningPolicy(NAV_BY_HREF.get("/chat")!, {
      allowed_surfaces: [],
    }),
    false,
  );
  assert.equal(
    isNavEntryAllowedForLearningPolicy(NAV_BY_HREF.get("/reading")!, {
      allowed_surfaces: ["reading"],
    }),
    true,
  );

  const access = settingsAccessFromAuthStatus({
    enabled: true,
    authenticated: true,
    is_admin: false,
    preset: "standard",
    learning_policy: policy,
  });
  assert.equal(access.showGuardianOnly, false);
  const visibleKeys = SETTINGS_CATEGORIES.filter((category) =>
    isSettingsCategoryVisible(category, access),
  ).map((category) => category.key);
  assert.deepEqual(visibleKeys, [
    "appearance",
    "learner-profile",
    "about",
  ]);
});

test("optional sidebar label failures keep the session list", async () => {
  const session = {
    id: "allowed-session",
    session_id: "allowed-session",
    title: "Allowed chat history",
    created_at: 1,
    updated_at: 2,
    message_count: 0,
    last_message: "",
    status: "idle",
    preferences: { capability: "chat" },
    active_turns: [],
  } as SessionSummary;

  const summaries = await loadSidebarSummaries({
    listSessions: async () => [session],
    listCourses: async () => {
      throw new Error("HTTP 403");
    },
    fetchMasteryTopicIndex: async () => {
      throw new Error("HTTP 403");
    },
    fetchReadingCollectionIndex: async () => {
      throw new Error("HTTP 403");
    },
  });

  assert.deepEqual(summaries.sessions, [session]);
  assert.deepEqual(summaries.courses, []);
  assert.deepEqual(summaries.masteryTopics, []);
  assert.deepEqual(summaries.readingCollections, []);
});
