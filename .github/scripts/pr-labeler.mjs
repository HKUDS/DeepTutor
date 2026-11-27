#!/usr/bin/env node
/**
 * Restrained, anti-spam PR Auto-Labeler for HKUDS/DeepTutor.
 *
 * Rules:
 * - Maps changed files into 6 coarse module buckets:
 *     desktop, mobile, web, backend, documentation, ci
 * - Ignores lockfiles and snapshot noise when weighing line changes.
 * - Applies AT MOST the top 1-2 module labels (the 2nd bucket is included ONLY
 *   if it accounts for >= 25% of total weighted changes).
 * - On `synchronize`, skips adding module labels if the PR already carries any
 *   module label, preserving manual Maintainer edits.
 * - Optionally infers at most 1 type label (`bug` or `enhancement`) from a
 *   conventional commit title (`fix:` / `feat:`) if no type label is present.
 */

import assert from "node:assert/strict";

const MODULE_LABELS = new Set([
  "desktop",
  "mobile",
  "web",
  "backend",
  "documentation",
  "ci",
]);

const TYPE_LABELS = new Set(["bug", "enhancement", "documentation", "question"]);

// v1.7.0 release timestamp (2026-10-28T14:13:12Z):
// - PRs created BEFORE v1.7.0 are owned by @pancacake.
// - PRs created ON/AFTER v1.7.0 are handled by Maintainers and must NOT keep
//   @pancacake in requested_reviewers unless escalated via `needs-pancake`.
const V170_CUTOFF_ISO = "2026-10-28T14:13:12Z";
const PANCAKE_LOGIN = "pancacake";

const NOISE_FILE_RE =
  /(?:^|\/)(?:package-lock\.json|pnpm-lock\.yaml|yarn\.lock|poetry\.lock|uv\.lock|Cargo\.lock)|(?:\.snap|\.png|\.jpg|\.jpeg|\.gif|\.webp|\.ico|\.woff2?|\.ttf)$/i;

export function classifyFileBucket(filename) {
  const f = (filename || "").replace(/\\/g, "/");
  if (f.startsWith("apps/desktop/")) return "desktop";
  if (f.startsWith("apps/mobile/")) return "mobile";
  if (f.startsWith("web/")) return "web";
  if (
    f.startsWith("docs/") ||
    f.startsWith("docs-for-dev/") ||
    f.startsWith("site/") ||
    f.startsWith("assets/README/") ||
    /^README(?:[._-].*)?\.md$/i.test(f) ||
    /^(?:CHANGELOG|CONTRIBUTING|SECURITY)\.md$/i.test(f)
  ) {
    return "documentation";
  }
  if (
    f.startsWith(".github/") ||
    f.startsWith("scripts/") ||
    /^Dockerfile/i.test(f) ||
    /^docker-compose/i.test(f)
  ) {
    return "ci";
  }
  if (
    f.startsWith("deeptutor/") ||
    f.startsWith("deeptutor_cli/") ||
    f.startsWith("tests/") ||
    f.startsWith("requirements/") ||
    f === "pyproject.toml" ||
    f === "setup.py"
  ) {
    return "backend";
  }
  return null;
}

export function inferTypeLabel(title) {
  const t = (title || "").trim();
  if (/^fix(?:\([^)]+\))?!?\s*:/i.test(t)) return "bug";
  if (/^feat(?:\([^)]+\))?!?\s*:/i.test(t)) return "enhancement";
  if (/^docs(?:\([^)]+\))?!?\s*:/i.test(t)) return "documentation";
  return null;
}

export function computePrLabels({ files, title, existingLabels = [], action = "opened" }) {
  const existing = new Set(existingLabels);
  const toAdd = new Set();

  const hasExistingModule = [...existing].some((l) => MODULE_LABELS.has(l));
  if (action === "opened" || action === "reopened" || !hasExistingModule) {
    const weights = new Map();
    const fallbackCounts = new Map();

    for (const file of files || []) {
      const bucket = classifyFileBucket(file.filename);
      if (!bucket) continue;
      fallbackCounts.set(bucket, (fallbackCounts.get(bucket) || 0) + 1);
      if (NOISE_FILE_RE.test(file.filename)) continue;
      const lines = Math.max(1, Number(file.additions || 0) + Number(file.deletions || 0));
      weights.set(bucket, (weights.get(bucket) || 0) + lines);
    }

    const activeMap = weights.size > 0 ? weights : fallbackCounts;
    const ranked = [...activeMap.entries()].sort((a, b) => b[1] - a[1]);
    const total = ranked.reduce((acc, [, w]) => acc + w, 0);

    if (ranked.length > 0 && total > 0) {
      toAdd.add(ranked[0][0]);
      if (ranked.length > 1 && ranked[1][1] / total >= 0.25) {
        toAdd.add(ranked[1][0]);
      }
    }
  }

  const hasExistingType = [...existing].some((l) => TYPE_LABELS.has(l));
  if (!hasExistingType) {
    const inferred = inferTypeLabel(title);
    if (inferred) toAdd.add(inferred);
  }

  return [...toAdd].filter((l) => !existing.has(l));
}

async function ghRequest(token, repoFull, method, urlPath, body = undefined, allowStatus = []) {
  const res = await fetch(`https://api.github.com/repos/${repoFull}${urlPath}`, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok && !allowStatus.includes(res.status)) {
    const txt = await res.text();
    throw new Error(`GitHub API ${method} ${urlPath} -> ${res.status}: ${txt}`);
  }
  if (res.status === 204 || !res.ok) return null;
  return res.json();
}

export function decidePancakeRouting({ createdAt, existingLabels = [], requestedReviewers = [], assignees = [] }) {
  const isPre170 = Boolean(createdAt && createdAt < V170_CUTOFF_ISO);
  const labels = new Set(existingLabels);
  const reviewersLower = requestedReviewers.map((u) => u.toLowerCase());
  const assigneesLower = assignees.map((u) => u.toLowerCase());

  if (isPre170) {
    return {
      assignPancake: !assigneesLower.includes(PANCAKE_LOGIN),
      stripPancakeReviewer: false,
    };
  }
  return {
    assignPancake: false,
    stripPancakeReviewer:
      reviewersLower.includes(PANCAKE_LOGIN) && !labels.has("needs-pancake"),
  };
}

function runSelfTest() {
  // 1. Large web PR touching 2 lines of README -> ONLY `web` + `enhancement` (no `documentation` spam)
  const labels1 = computePrLabels({
    title: "feat(settings): render preferences as floating card",
    files: [
      { filename: "web/components/settings/SettingsMain.tsx", additions: 280, deletions: 80 },
      { filename: "web/package-lock.json", additions: 4000, deletions: 2000 },
      { filename: "README.md", additions: 2, deletions: 2 },
    ],
    existingLabels: [],
    action: "opened",
  });
  assert.deepEqual(labels1, ["web", "enhancement"]);

  // 2. Balanced full-stack PR (backend 60%, web 40%) -> `backend`, `web`, `bug` (capped at 2 modules)
  const labels2 = computePrLabels({
    title: "fix(rag): surface indexing errors in UI",
    files: [
      { filename: "deeptutor/services/rag/indexer.py", additions: 60, deletions: 0 },
      { filename: "web/features/kb/KbStatus.tsx", additions: 40, deletions: 0 },
      { filename: "docs/kb.md", additions: 5, deletions: 0 },
    ],
    existingLabels: [],
    action: "opened",
  });
  assert.deepEqual(labels2, ["backend", "web", "bug"]);

  // 3. On synchronize, respects existing module label without re-adding removed ones
  const labels3 = computePrLabels({
    title: "fix(rag): surface indexing errors in UI",
    files: [
      { filename: "deeptutor/services/rag/indexer.py", additions: 60, deletions: 0 },
      { filename: "web/features/kb/KbStatus.tsx", additions: 40, deletions: 0 },
    ],
    existingLabels: ["backend", "bug"],
    action: "synchronize",
  });
  assert.deepEqual(labels3, []);

  assert.deepEqual(
    decidePancakeRouting({
      createdAt: "2026-10-20T00:00:00Z",
      existingLabels: [],
      requestedReviewers: [],
      assignees: [],
    }),
    { assignPancake: true, stripPancakeReviewer: false },
  );
  assert.deepEqual(
    decidePancakeRouting({
      createdAt: "2026-11-26T00:00:00Z",
      existingLabels: ["web"],
      requestedReviewers: ["pancacake"],
      assignees: [],
    }),
    { assignPancake: false, stripPancakeReviewer: true },
  );
  assert.deepEqual(
    decidePancakeRouting({
      createdAt: "2026-11-26T00:00:00Z",
      existingLabels: ["web", "needs-pancake"],
      requestedReviewers: ["pancacake"],
      assignees: [],
    }),
    { assignPancake: false, stripPancakeReviewer: false },
  );

  console.log("pr-labeler self-test passed.");
}

async function main() {
  if (process.argv.includes("--self-test")) {
    runSelfTest();
    return;
  }

  const token = process.env.GH_TOKEN || "";
  const repoFull = process.env.GITHUB_REPOSITORY || "";
  const prNumber = Number(process.env.PR_NUMBER || "0");
  const prTitle = process.env.PR_TITLE || "";
  const envCreatedAt = process.env.PR_CREATED_AT || "";
  const action = process.env.EVENT_ACTION || "opened";

  if (!token || !repoFull || !prNumber) {
    throw new Error("Missing GH_TOKEN, GITHUB_REPOSITORY, or PR_NUMBER.");
  }

  const pr = await ghRequest(token, repoFull, "GET", `/pulls/${prNumber}`);
  const existingLabels = (pr.labels || []).map((l) => l.name);
  const requestedReviewers = (pr.requested_reviewers || []).map((u) => u.login);
  const assignees = (pr.assignees || []).map((u) => u.login);
  const createdAt = pr.created_at || envCreatedAt;

  // Enforce v1.7.0 @pancacake routing rule
  const routing = decidePancakeRouting({
    createdAt,
    existingLabels,
    requestedReviewers,
    assignees,
  });
  if (routing.assignPancake) {
    await ghRequest(
      token,
      repoFull,
      "POST",
      `/issues/${prNumber}/assignees`,
      { assignees: [PANCAKE_LOGIN] },
      [422],
    );
    console.log(`PR #${prNumber}: pre-v1.7.0 PR assigned to @${PANCAKE_LOGIN}.`);
  }
  if (routing.stripPancakeReviewer) {
    await ghRequest(
      token,
      repoFull,
      "DELETE",
      `/pulls/${prNumber}/requested_reviewers`,
      { reviewers: [PANCAKE_LOGIN] },
      [422],
    );
    console.log(`PR #${prNumber}: removed @${PANCAKE_LOGIN} from requested_reviewers (post-v1.7.0 rule).`);
  }

  if (action === "review_requested") {
    return;
  }

  const files = [];
  for (let page = 1; page <= 3; page += 1) {
    const batch = await ghRequest(
      token,
      repoFull,
      "GET",
      `/pulls/${prNumber}/files?per_page=100&page=${page}`,
    );
    if (!Array.isArray(batch) || batch.length === 0) break;
    files.push(...batch);
    if (batch.length < 100) break;
  }

  const toAdd = computePrLabels({ files, title: prTitle, existingLabels, action });
  if (toAdd.length === 0) {
    console.log(`PR #${prNumber}: no new labels needed (existing: ${existingLabels.join(", ") || "none"}).`);
    return;
  }

  await ghRequest(token, repoFull, "POST", `/issues/${prNumber}/labels`, { labels: toAdd });
  console.log(`PR #${prNumber}: applied [${toAdd.join(", ")}].`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
