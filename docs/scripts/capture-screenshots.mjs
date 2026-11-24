// DeepTutor docs screenshot capture — drives a running DeepTutor web UI and
// writes 1470x836@2x light-theme shots into site/public/screenshots/.
// Needs the `playwright` npm package + chromium (npx playwright install chromium).
// Usage: node capture-screenshots.mjs [job ...]   (no args = list jobs)
//        PARTNER=<id> node capture-screenshots.mjs channels   # per-channel cards
import { chromium } from "playwright";

const BASE = process.env.BASE ?? "http://localhost:3784";
const OUT = process.env.OUT ?? new URL("../public/screenshots", import.meta.url).pathname;
const CHANNELS = [
  "weixin", "wecom", "qq", "napcat", "telegram", "discord", "slack",
  "feishu", "dingtalk", "matrix", "zulip", "whatsapp", "email", "mochat", "msteams",
];
const DISPLAY = {
  weixin: "WeChat", wecom: "WeCom", qq: "QQ", napcat: "QQ (NapCat)",
  telegram: "Telegram", discord: "Discord", slack: "Slack", feishu: "Feishu",
  dingtalk: "DingTalk", matrix: "Matrix", zulip: "Zulip", whatsapp: "WhatsApp",
  email: "Email", mochat: "Mochat", msteams: "Microsoft Teams",
};

const browser = await chromium.launch();
const ctx = await browser.newContext({
  viewport: { width: 1470, height: 836 },
  deviceScaleFactor: 2,
  colorScheme: "light",
});
// Hide personal session titles in the sidebar on every page.
await ctx.addInitScript(() => {
  try { localStorage.setItem("deeptutor.sidebar.recentsCollapsed", "1"); } catch {}
});
const page = await ctx.newPage();

async function go(path, delay = 1500) {
  await page.goto(BASE + path, { waitUntil: "networkidle", timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(delay);
}
async function shot(name) {
  await page.screenshot({ path: `${OUT}/${name}.png` });
  console.log("shot", name);
}

const jobs = {
  // simple page shots: job name -> [path, file]
  partners: ["/partners", "partners"],
  "partners-new": ["/partners/new", "partners-new"],
  chat: ["/chat", "chat"],
  knowledge: ["/knowledge", "knowledge"],
  book: ["/book", "book"],
  "co-writer": ["/co-writer", "co-writer"],
  learning: ["/learning", "learning"],
  space: ["/space", "space"],
  memory: ["/memory", "memory"],
  "memory-graph": ["/memory/graph", "memory-graph"],
  "settings-appearance": ["/settings/appearance", "settings-appearance"],
  "settings-llm": ["/settings/llm", "settings-llm"],
  "settings-embedding": ["/settings/embedding", "settings-embedding"],
  "settings-search": ["/settings/search", "settings-search"],
  "settings-mineru": ["/settings/mineru", "settings-mineru"],
  "settings-capabilities": ["/settings/capabilities", "settings-capabilities"],
  "settings-memory": ["/settings/memory", "settings-memory"],
  "settings-mcp": ["/settings/mcp", "settings-mcp"],
  "settings-tools": ["/settings/tools", "settings-tools"],
  "settings-network": ["/settings/network", "settings-network"],
  "settings-status": ["/settings/status", "settings-status"],
};

async function openPartnerTab(partnerId, tabText) {
  await go(`/partners/${partnerId}`);
  await page.click(`button:has-text("${tabText}")`);
  await page.waitForTimeout(1200);
}

async function channelShots(partnerId) {
  await openPartnerTab(partnerId, "Channels");
  for (const ch of CHANNELS) {
    const label = DISPLAY[ch];
    const btn = page.locator("aside button", { hasText: label }).first();
    await btn.click();
    await page.waitForTimeout(900);
    await shot(`partners-channel-${ch}`);
  }
}

const args = process.argv.slice(2);
if (args.length === 0) {
  console.log("jobs:", [...Object.keys(jobs), "channels", "partner-detail"].join(" "));
} else {
  for (const a of args) {
    if (a === "channels") {
      await channelShots(process.env.PARTNER ?? "frank");
    } else if (a === "partner-detail") {
      const pid = process.env.PARTNER ?? "frank";
      await openPartnerTab(pid, "Configure");
      await shot("partners-configure");
      await openPartnerTab(pid, "Channels");
      await shot("partners-channels");
    } else if (jobs[a]) {
      const [path, file] = jobs[a];
      await go(path);
      await shot(file);
    } else {
      console.error("unknown job", a);
    }
  }
}
await browser.close();
