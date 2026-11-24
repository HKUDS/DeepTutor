// DeepTutor guide screenshots — drives a running DeepTutor web UI and writes
// 1470x836@2x light-theme shots into site/docs/public/screenshots/guide/<dir>/.
//
// The guide shots (the ones embedded in /explore/* pages) used to be taken by
// hand, which is why they drifted ~25 releases behind the product. This script
// makes a refresh reproducible: pick the jobs you need, re-run, review the diff.
//
// Requires the `playwright` npm package + chromium. It is not a dependency of
// the docs site, so resolve it from wherever it is installed:
//   PW_FROM=../../web/package.json node scripts/capture-guide.mjs <job ...>
// Run with no arguments to list the jobs.
//
// The DeepTutor instance must be running with the interface language set to
// English (the docs are English-source and both locales share the images).
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
import { dirname } from "node:path";

const require = createRequire(
  new URL(process.env.PW_FROM ?? "../../../web/package.json", import.meta.url),
);
const { chromium } = require("playwright");

const BASE = process.env.BASE ?? "http://localhost:3784";
const API_BASE = process.env.API_BASE ?? "http://localhost:8001";
const EXPECT_VERSION = process.env.EXPECT_VERSION ?? "v1.6.1";
const OUT =
  process.env.OUT ?? new URL("../public/screenshots/guide", import.meta.url).pathname;
const ROOT_OUT = dirname(OUT);

// The bundled chromium is older than the pdf.js build the reader ships, and
// fails to render a PDF at all (`getOrInsertComputed is not a function`).
// Installed Chrome is current, and playwright still gives it a throwaway
// profile — so the reading shots need `channel: "chrome"` and everything else
// is happy with it too.
const browser = await chromium.launch({ channel: process.env.PW_CHANNEL ?? "chrome" });
const ctx = await browser.newContext({
  viewport: { width: 1470, height: 836 },
  deviceScaleFactor: 2,
  colorScheme: "light",
});
// Collapse the Recents list: it is the one part of the chrome that renders the
// operator's own session titles into a published image.
await ctx.addInitScript(() => {
  try {
    localStorage.setItem("deeptutor.sidebar.recentsCollapsed", "1");
  } catch {}
});
const page = await ctx.newPage();

// Settings should demonstrate the memory card without publishing the capture
// machine's RAM size or current process footprint. The values are synthetic,
// stable, and scoped to this disposable browser context.
await page.route("**/api/v1/system/memory", async (route) => {
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      available: true,
      total_rss_bytes: 100663296,
      limit_bytes: 2147483648,
      available_bytes: 1610612736,
      limit_source: "cgroup-v2",
      usage_ratio: 0.046875,
      partial: false,
      processes: [{ label: "backend", count: 1, rss_bytes: 100663296 }],
    }),
  });
});

async function go(path, delay = 1800) {
  const response = await page.goto(BASE + path, {
    waitUntil: "networkidle",
    timeout: 45000,
  });
  const landedOnRequestedDocument = page.url().startsWith(BASE + path);
  if ((!response && !landedOnRequestedDocument) || (response && response.status() >= 400)) {
    throw new Error(`navigation failed for ${path}: ${response?.status() ?? "no response"}`);
  }
  await page.waitForTimeout(delay);
  const hash = path.includes("#") ? path.split("#", 2)[1] : "";
  if (hash) {
    const target = page.locator(`#${hash}`);
    await target.scrollIntoViewIfNeeded().catch(() => {});
    await page.waitForTimeout(400);
  }
  await dismissDevOverlay();
}

async function dismissDevOverlay() {
  await assertNoDevError();
  await page.evaluate(() => {
    document.querySelectorAll("nextjs-portal").forEach((node) => node.remove());
    if (!document.querySelector("style[data-docs-capture-clean]")) {
      const style = document.createElement("style");
      style.dataset.docsCaptureClean = "true";
      style.textContent = "nextjs-portal{display:none!important;pointer-events:none!important}";
      document.head.appendChild(style);
    }
  });
}

async function assertNoDevError() {
  const text = await page.evaluate(() =>
    Array.from(document.querySelectorAll("nextjs-portal"))
      .map((node) => node.shadowRoot?.textContent ?? node.textContent ?? "")
      .join("\n"),
  );
  if (/\b\d+\s+Issues?\b|Unhandled Runtime Error|Build Error/i.test(text)) {
    throw new Error(`Next.js reported a capture-blocking issue: ${text.slice(0, 500)}`);
  }
}

async function assertRelease() {
  await go("/home", 500);
  const badge = page.locator(`a[title="${EXPECT_VERSION}"]`).first();
  if (!(await badge.isVisible().catch(() => false))) {
    const body = (await page.locator("body").innerText()).slice(0, 500);
    throw new Error(
      `expected ${EXPECT_VERSION} release badge before capture; page starts: ${body}`,
    );
  }
}

async function shot(name, opts = {}) {
  const path = `${OUT}/${name}.png`;
  await shotTo(path, opts);
  console.log("shot", name);
}

async function shotRoot(name, opts = {}) {
  const path = `${ROOT_OUT}/${name}.png`;
  await shotTo(path, opts);
  console.log("shot", name);
}

async function shotTo(path, opts = {}) {
  await mkdir(dirname(path), { recursive: true });
  // Never publish a screenshot from a page that Next itself considers broken.
  // The portal is removed only after this assertion so a real warning cannot
  // be silently hidden by the capture harness.
  await assertNoDevError();
  await dismissDevOverlay();
  await page.waitForTimeout(100);
  await page.screenshot({ path, ...opts });
}

/** Screenshot one element plus a margin, for menus and popovers. */
async function shotRegion(name, selector, pad = 16) {
  const target = page.locator(selector).first();
  await target.waitFor({ state: "visible", timeout: 3000 }).catch(() => {});
  const box = await target.boundingBox().catch(() => null);
  if (!box) {
    // The popup shell changed across releases. A full-page shot still records
    // the visible semantic state and is safer than publishing an old image.
    await shot(name);
    return;
  }
  const clip = {
    x: Math.max(0, box.x - pad),
    y: Math.max(0, box.y - pad),
    width: Math.min(1470 - Math.max(0, box.x - pad), box.width + pad * 2),
    height: Math.min(836 - Math.max(0, box.y - pad), box.height + pad * 2),
  };
  await shot(name, { clip });
}

// ---------------------------------------------------------------------------
// Jobs
// ---------------------------------------------------------------------------

/** Plain "navigate and shoot" pages: job -> [route, output name]. */
const PAGE_JOBS = {
  overview: ["/home", "OVERVIEW"],
  "home-overview": ["/home", "home/00-overview"],
  knowledge: ["/knowledge", "knowledge/00-overview"],
  "rag-integrations": ["/knowledge?section=engines", "ecosystem/rag/00-integrations"],
  "learning-space": ["/space", "learning-space/00-overview"],
  "chat-history": ["/space/chat-history", "learning-space/01-chat-history"],
  notebook: ["/notebook", "notebook/00-console"],
  questions: ["/space/questions", "learning-space/03-question-bank"],
  "ecosystem-overview": ["/space", "ecosystem/OVERVIEW"],
  skills: ["/space/skills", "ecosystem/skills/00-overview"],
  personas: ["/space/personas", "learning-space/05-personas"],
  "mcp-installed": ["/space/mcp", "ecosystem/mcp/00-installed"],
  "cli-apps-installed": ["/space/cli-apps", "ecosystem/cli-apps/00-installed"],
  mastery: ["/mastery", "mastery-path/00-overview"],
  settings: ["/settings", "settings/00-setting-overview"],
  "settings-video": ["/settings#video-learning", "settings/04-video-learning"],
  "settings-agents": ["/settings#agents", "settings/05-partners-agents"],
  "settings-about": ["/settings#about", "settings/06-about-update"],
  "settings-appearance": ["/settings/appearance", "settings/01-appearance-settings"],
  "settings-chat": ["/settings/chat", "home/11-configure-and-explore-tools"],
  "settings-models": ["/settings/models", "home/10-configure-models"],
  "settings-starters": ["/settings/starters", "settings/03-starting-points"],
  "settings-memory": ["/settings/memory", "memory/02-config-memory-params-in-settings"],
  "settings-parsing": [
    "/settings/document-parsing",
    "knowledge/03-config-document-parsing-engine-in-settings",
  ],
  memory: ["/memory", "memory/00-overview"],
  "memory-graph": ["/memory/graph", "memory/01-3-layer-memory-graph"],
  book: ["/book", "book/00-book-overview"],
  "co-writer": ["/co-writer", "co-writer/00-overview"],
  agents: ["/agents", "myagents/00-overview"],
  partners: ["/partners", "partners/00-partners-overview"],
};

/** The composer's capability button — its accessible name is the active mode. */
const capButton = (label = "Chat") => page.getByRole("button", { name: label, exact: true });

/** Open the reader on the most recently read material. */
async function openReader() {
  await go("/reading");
  const collection = page.getByRole("link", { name: /Signal Processing Reading List/ });
  const href = await collection.getAttribute("href");
  if (!href) throw new Error("demo reading collection has no workspace URL");
  await go(href, 3500);
}

/** Interactive jobs that have to click something first. */
const FLOW_JOBS = {
  // The capability picker, open. Clipped to the popup so the menu is legible.
  async capabilities() {
    await go("/home");
    await capButton().click();
    await page.waitForTimeout(700);
    await shotRegion("home/01-capabilities", ".dt-popup-up", 24);
  },

  // The `+` context menu, open.
  async "add-contexts"() {
    await go("/home");
    await page.locator('button[aria-label="Add files & context"]').first().click();
    await page.waitForTimeout(700);
    await shotRegion("home/02-add-contexts", ".absolute.bottom-full.left-0.z-50 > div", 24);
  },

  // Sticky-context popovers on the right of the composer toolbar.
  async knowledge_picker() {
    await go("/home");
    await page.locator('button[aria-label="Select knowledge bases"]').click();
    await page.waitForTimeout(700);
    await shotRegion("home/04-attatch-knowledge-base", ".dt-popup-up", 24);
  },
  async persona_picker() {
    await go("/home");
    await page.locator('button[aria-label="Select persona"]').click();
    await page.waitForTimeout(700);
    await shotRegion("home/05-customize-persona", ".dt-popup-up", 24);
  },
  async model_picker() {
    await go("/home");
    await page.locator('button[aria-label="Select model"]').click();
    await page.waitForTimeout(700);
    await shotRegion("home/06-switch-model", ".dt-popup-up", 24);
  },

  async activity_panel() {
    await go("/home");
    await page.getByRole("button", { name: "Activity", exact: true }).click();
    await page.waitForTimeout(700);
    await shot("home/07-side-bar-for-various-activities");
  },

  async connected_agent_picker() {
    await go("/home");
    await page
      .getByRole("button", { name: "Select a connected agent", exact: true })
      .click();
    await page.waitForTimeout(500);
    await shotRegion("home/03-use-subagent", ".dt-popup-up", 24);
  },

  async agent_mention() {
    await go("/home");
    const input = page.getByRole("textbox", {
      name: "How can I help you today?",
      exact: true,
    });
    await input.fill("@");
    await page.getByRole("listbox", { name: "Talk to an agent" }).waitFor();
    await shotRegion("home/03-another-use-subagent", '[role="listbox"]', 24);
  },

  async immersive_watching() {
    await go("/home");
    await capButton().click();
    await page.locator(".dt-popup-up").getByRole("button", { name: /^Immersive Watching/ }).click();
    await page.getByPlaceholder("https://youtu.be/…", { exact: true }).waitFor();
    await shot("home/12-immersive-watching");
  },

  async visualizer_types() {
    await go("/home");
    await capButton().click();
    await page.locator(".dt-popup-up").getByRole("button", { name: /^Visualize/ }).click();
    await page.getByText("Visualizer Types", { exact: true }).waitFor();
    await shot("home/13-visualizer-types");
  },

  async myagents_add() {
    await go("/agents");
    await page.getByRole("button", { name: "Add agent", exact: true }).click();
    await page.getByRole("dialog").waitFor();
    await shot("myagents/01-sync-selective-chat-history-from-claude-code-or-codex");
  },

  async partner_chat() {
    await go("/partners/sage");
    await shot("partners/01-chat-with-partners");
  },

  async partner_channels() {
    await go("/partners/sage");
    await page.getByRole("button", { name: "Channels", exact: true }).click();
    await page.waitForTimeout(700);
    await shot("partners/02-im-config-for-each-partner");
  },

  async partner_channel_status() {
    await go("/partners/sage");
    await page.getByRole("button", { name: "Channels", exact: true }).click();
    await page.getByRole("button", { name: /^Telegram/ }).click();
    await page.getByText("Status: Configuration required", { exact: true }).waitFor();
    await shot("partners/03-channel-status");
  },

  async channel_forms() {
    const channels = [
      ["WeChat", "weixin"],
      ["WeCom", "wecom"],
      ["QQ", "qq"],
      ["QQ (NapCat)", "napcat"],
      ["Telegram", "telegram"],
      ["Discord", "discord"],
      ["Slack", "slack"],
      ["Feishu", "feishu"],
      ["DingTalk", "dingtalk"],
      ["Zulip", "zulip"],
      ["Mattermost", "mattermost"],
      ["WhatsApp", "whatsapp"],
      ["Email", "email"],
      ["Mochat", "mochat"],
      ["Microsoft Teams", "msteams"],
    ];
    await go("/partners/sage");
    await page.getByRole("button", { name: "Channels", exact: true }).click();
    for (const [label, slug] of channels) {
      const prefix = label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      await page
        .getByRole("button", { name: new RegExp(`^${prefix}(?:\\s+Enabled)?$`) })
        .click();
      await page.waitForTimeout(300);
      await shotRoot(`partners-channel-${slug}`);
    }
  },

  async multi_user() {
    await go("/admin/users");
    await shotRoot("multi-user");
  },

  async knowledge_create() {
    await go("/knowledge");
    await page.getByRole("button", { name: "New knowledge base", exact: true }).click();
    await page.getByRole("dialog").waitFor();
    await shot("knowledge/01-create-knowledge-base");
  },

  async knowledge_panel() {
    await go("/knowledge");
    const kb = page.getByText("Signal Processing Notes", { exact: true });
    await kb.scrollIntoViewIfNeeded();
    await kb.click();
    await page.waitForTimeout(900);
    await shot("knowledge/02-panel-for-each-knowledge-base");
  },

  async mastery_study() {
    const response = await fetch(`${API_BASE}/api/v1/learning/topics`);
    if (!response.ok) throw new Error(`mastery topic lookup failed: ${response.status}`);
    const payload = await response.json();
    const topics = Array.isArray(payload) ? payload : payload.topics ?? payload.data ?? [];
    const topic = topics.find((item) => item.name === "Fourier Transform Foundations");
    const pathId = topic?.path_id ?? topic?.book_id ?? topic?.id;
    if (!pathId) throw new Error("demo mastery topic was not found");
    await go(`/mastery/${encodeURIComponent(pathId)}/study`, 2500);
    const activity = page.getByRole("button", { name: "Activity", exact: true });
    await activity.waitFor();
    await activity.click();
    await page.getByText("Session activity", { exact: true }).waitFor();
    await shot("mastery-path/01-study-workspace");
  },

  async cowriter_editor() {
    await go("/co-writer");
    await page.getByText("Fourier Transform Study Notes", { exact: true }).click();
    await page.waitForTimeout(1000);
    await shot("co-writer/01-edit-panel");
  },

  async book_quiz() {
    await go("/book?book=docs_fourier&page=pg_foundations", 2500);
    await page.locator('[data-block-id="blk_quiz"]').scrollIntoViewIfNeeded();
    await shot("book/01-book-demo-quiz-card");
  },

  async book_animation() {
    await go("/book?book=docs_fourier&page=pg_visual", 2500);
    await page.locator('[data-block-id="blk_animation"]').scrollIntoViewIfNeeded();
    await shot("book/02-book-demo-manim-video");
  },

  async book_interactive() {
    await go("/book?book=docs_fourier&page=pg_interactive", 2500);
    await page.locator('[data-block-id="blk_interactive"]').scrollIntoViewIfNeeded();
    await shot("book/03-book-demo-interactive-module");
  },

  async book_mermaid_chat() {
    await go("/book?book=docs_fourier&page=pg_visual", 2500);
    await page.locator('[data-block-id="blk_mermaid"]').scrollIntoViewIfNeeded();
    await dismissDevOverlay();
    await page.getByRole("button", { name: "Chat", exact: true }).click({ force: true });
    await page.getByText("Page Chat", { exact: true }).waitFor();
    await shot("book/04-book-demo-side-chat-mermaid");
  },

  async book_insert_menu() {
    await go("/book?book=docs_fourier&page=pg_foundations", 2500);
    const button = page.getByRole("button", { name: "Insert block", exact: true });
    await button.scrollIntoViewIfNeeded();
    await button.click();
    await page.waitForTimeout(300);
    await shot("book/05-book-add-customize-block-for-chapter");
  },

  async book_change_type() {
    await go("/book?book=docs_fourier&page=pg_foundations", 2500);
    const block = page.locator('[data-block-id="blk_intro"]');
    await block.scrollIntoViewIfNeeded();
    await block.hover();
    await page.getByTitle("Change type").first().click();
    await page.waitForTimeout(300);
    await shot("book/06-book-switch-the-block-type");
  },

  // The MCP + CLI stores land on their "Installed" tab; the catalog is behind
  // the Store tab, and that is the half worth showing.
  async "mcp-store-catalog"() {
    await go("/space/mcp");
    await page.getByRole("button", { name: /^Store/ }).click();
    await page.waitForTimeout(1500);
    await shot("ecosystem/mcp/00-store");
  },
  async "cli-apps-catalog"() {
    await go("/space/cli-apps");
    await page.getByRole("button", { name: /^Store/ }).click();
    await page.waitForTimeout(1500);
    await shot("ecosystem/cli-apps/00-store");
  },

  async "eduhub-catalog"() {
    await go("/space/skills");
    await page.getByRole("button", { name: "Import from EduHub", exact: true }).click();
    const dialog = page.getByRole("dialog");
    await dialog.waitFor({ state: "visible", timeout: 10000 });
    await dialog.locator("ul li").first().waitFor({ state: "visible", timeout: 30000 });
    await shot("ecosystem/eduhub/00-skill-catalog");
  },

  // Immersive Reading: the empty state (what you see on entering the mode),
  // then the reader with a document open beside the thread.
  async "reading-picker"() {
    await go("/reading");
    await shot("reading/01-open-a-document");
  },
  async "reading-open"() {
    await openReader();
    await shot("reading/00-overview");
  },

  // A real grounded turn: ask the open document a question and let the answer
  // arrive with its page citations. Costs one LLM call against whatever model
  // the instance is configured with.
  async "reading-answer"() {
    await openReader();
    await page.getByRole("textbox").last().fill(
      "What problem does this paper say existing RAG tutoring systems fail at? Cite the page.",
    );
    await page.locator('button[aria-label="Send"]').click();
    // Let the turn run to completion (locate pre-pass + model + reader jump).
    await page.waitForTimeout(60000);
    await shot("reading/02-cited-answer");
  },
};

const args = process.argv.slice(2);
const all = [...Object.keys(PAGE_JOBS), ...Object.keys(FLOW_JOBS)];
if (args.length === 0) {
  console.log("jobs:\n  " + all.join("\n  "));
} else {
  await assertRelease();
  const wanted = args[0] === "all" ? all : args;
  let failed = 0;
  for (const job of wanted) {
    try {
      if (PAGE_JOBS[job]) {
        const [route, name] = PAGE_JOBS[job];
        await go(route);
        await shot(name);
      } else if (FLOW_JOBS[job]) {
        await FLOW_JOBS[job]();
      } else {
        console.error("unknown job", job);
      }
    } catch (err) {
      failed += 1;
      console.error("FAILED", job, "-", err.message);
    }
  }
  if (failed) process.exitCode = 1;
}
await browser.close();
