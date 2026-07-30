/**
 * Catalog entry id → [Simple Icons](https://simpleicons.org) slug.
 *
 * The hand-curated half of the brand-icon pipeline. `brand-icons.generated.ts`
 * is produced from this file plus the `simple-icons` package by
 * `scripts/build-brand-icons.mts`, which **fails** on a slug that does not
 * exist — so a typo here is a build error, not a silently missing icon.
 *
 * Why bundled rather than fetched: an icon per installed service, fetched at
 * render time, tells that vendor (or a favicon proxy) who is looking and what
 * else they have installed. Simple Icons is CC0, so the paths ship with the app
 * and the browser makes no request at all. The upstream CLI-Anything hub and
 * nanobot both hot-link a favicon chain; this is the same icons without the
 * callout.
 *
 * Coverage is deliberately partial. The newer MCP brands (Exa, Tavily,
 * Firecrawl, Apify, Jina, Context7, Linkup, Browserbase, Hyperbrowser, FastMCP,
 * DeepWiki) are not in Simple Icons at all, and a wrong-but-present logo is
 * worse than an initials monogram. Anything absent here falls back to the
 * monogram, which is a fine second-class citizen.
 *
 * ADDING ONE: find the slug at simpleicons.org, add a line, re-run
 * `npm run build:brand-icons`. Trademarks belong to their owners; these marks
 * identify a product and imply no endorsement (see the notice in the stores).
 */

/** MCP catalog ids (`deeptutor/services/mcp/catalog/vendor/curated.json`). */
export const MCP_BRAND_SLUGS: Readonly<Record<string, string>> = {
  airtable: "airtable",
  "baidu-maps": "baidu",
  "brave-search": "brave",
  "chakra-ui": "chakraui",
  clerk: "clerk",
  "cloudflare-docs": "cloudflare",
  convex: "convex",
  github: "github",
  // The server is a thin wrapper over git hosting; the git mark is the honest one.
  gitmcp: "git",
  "google-maps": "googlemaps",
  huggingface: "huggingface",
  neon: "neon",
  postman: "postman",
  pubmed: "pubmed",
  stripe: "stripe",
  supabase: "supabase",
  svelte: "svelte",
  wolfram: "wolfram",
  zapier: "zapier",
};

/** CLI app ids (`deeptutor/services/cli_apps/vendor/catalog.json`). */
export const CLI_BRAND_SLUGS: Readonly<Record<string, string>> = {
  "1password-cli": "1password",
  adguardhome: "adguard",
  "android-cli": "android",
  "arcgis-pro": "arcgis",
  audacity: "audacity",
  blender: "blender",
  // Both browser harnesses drive Chrome over the DevTools protocol.
  browser: "googlechrome",
  "browser-cdp": "googlechrome",
  // A Rust CLI with no brand of its own.
  clibrowser: "rust",
  contentful: "contentful",
  "dify-workflow": "dify",
  drawio: "diagramsdotnet",
  elevenlabs: "elevenlabs",
  "eth2-quickstart": "ethereum",
  firefly: "fireflyiii",
  "firefly-iii": "fireflyiii",
  freecad: "freecad",
  "generate-veo-video": "googlegemini",
  gimp: "gimp",
  godot: "godotengine",
  "hacker-feeds-cli": "ycombinator",
  inkscape: "inkscape",
  iterm2: "iterm2",
  jimeng: "bytedance",
  joplin: "joplin",
  kdenlive: "kdenlive",
  krita: "krita",
  libreoffice: "libreoffice",
  // The debugger ships with LLVM and has no mark of its own.
  lldb: "llvm",
  mailchimp: "mailchimp",
  mermaid: "mermaid",
  minimax: "minimax",
  "minimax-cli": "minimax",
  n8n: "n8n",
  notebooklm: "googlegemini",
  "nsight-graphics": "nvidia",
  "obs-studio": "obsstudio",
  obsidian: "obsidian",
  "obsidian-agent-cli": "obsidian",
  "obsidian-cli": "obsidian",
  ollama: "ollama",
  pm2: "pm2",
  // An R package for clinical reporting.
  py4csr: "r",
  qgis: "qgis",
  safari: "safari",
  sanity: "sanity",
  sentry: "sentry",
  shopify: "shopify",
  siyuan: "siyuan",
  sketch: "sketch",
  slay_the_spire_ii: "steam",
  suno: "suno",
  ueatelier: "unrealengine",
  unrealinsights: "unrealengine",
  // WeCom is WeChat Work; Simple Icons carries only the WeChat mark.
  wecom: "wechat",
  zoom: "zoom",
  zotero: "zotero",
};

/** Every slug the generated file has to contain, deduplicated. */
export function referencedSlugs(): string[] {
  return [
    ...new Set([...Object.values(MCP_BRAND_SLUGS), ...Object.values(CLI_BRAND_SLUGS)]),
  ].sort();
}
