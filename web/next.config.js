/** @type {import('next').NextConfig} */

const fs = require("fs");
const os = require("os");
const path = require("path");

function readJsonFile(filePath) {
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch {
    return {};
  }
}

function firstNonEmpty(...values) {
  for (const value of values) {
    if (value !== undefined && value !== null && String(value).trim() !== "") {
      return String(value).trim();
    }
  }
  return "";
}

function normalizeBoolean(value) {
  if (value === "__NEXT_PUBLIC_AUTH_ENABLED_PLACEHOLDER__") {
    return value;
  }
  return ["1", "true", "yes", "on"].includes(String(value).trim().toLowerCase())
    ? "true"
    : "false";
}

/** This machine's non-loopback IPv4 addresses — the hosts `next dev` prints
 *  as "Network:", i.e. the ones a phone on the same WiFi actually types. */
function localNetworkHosts() {
  const hosts = [];
  for (const addresses of Object.values(os.networkInterfaces())) {
    for (const address of addresses ?? []) {
      if (address.family === "IPv4" && !address.internal) {
        hosts.push(address.address);
      }
    }
  }
  return hosts;
}

const SETTINGS_DIR = path.resolve(__dirname, "..", "data", "user", "settings");
const SYSTEM_SETTINGS = readJsonFile(path.join(SETTINGS_DIR, "system.json"));
const AUTH_SETTINGS = readJsonFile(path.join(SETTINGS_DIR, "auth.json"));
const BACKEND_PORT = firstNonEmpty(
  process.env.BACKEND_PORT,
  SYSTEM_SETTINGS.backend_port,
  "8001",
);

// Use data/user/settings as the frontend source of truth. Environment values
// remain explicit deployment overrides for Docker/CI.
const NEXT_PUBLIC_API_BASE = firstNonEmpty(
  process.env.NEXT_PUBLIC_API_BASE_EXTERNAL,
  SYSTEM_SETTINGS.next_public_api_base_external,
  process.env.NEXT_PUBLIC_API_BASE,
  SYSTEM_SETTINGS.next_public_api_base,
  `http://localhost:${BACKEND_PORT}`,
);

const NEXT_PUBLIC_AUTH_ENABLED = normalizeBoolean(
  firstNonEmpty(
    process.env.NEXT_PUBLIC_AUTH_ENABLED,
    process.env.AUTH_ENABLED,
    AUTH_SETTINGS.enabled,
    "false",
  ),
);

process.env.NEXT_PUBLIC_API_BASE = NEXT_PUBLIC_API_BASE;
process.env.NEXT_PUBLIC_AUTH_ENABLED = NEXT_PUBLIC_AUTH_ENABLED;

// Resolve the build-time application version from the single source of
// truth at ``deeptutor/__version__.py``. The Python file is parsed with a
// small regex so the JS build does not need to execute Python.
const APP_VERSION = (() => {
  try {
    const text = fs.readFileSync(
      path.resolve(__dirname, "..", "deeptutor", "__version__.py"),
      "utf8",
    );
    const match = text.match(/__version__\s*=\s*["']([^"']+)["']/);
    if (match) return match[1];
  } catch {}
  return "";
})();

const nextConfig = {
  // Keep the production build used by `deeptutor start` separate from the
  // `.next` development cache used by the explicit `deeptutor start --dev`.
  // Without separate directories either command can invalidate the other
  // process while it is running.
  distDir: process.env.DEEPTUTOR_NEXT_DIST_DIR || ".next",

  // Build/typecheck wrappers can point Next at a process-local config so a
  // production build never rewrites the tsconfig watched by a live dev server.
  typescript: {
    tsconfigPath: process.env.DEEPTUTOR_NEXT_TSCONFIG || "tsconfig.json",
  },

  // Expose the build-time version to the browser so the sidebar badge
  // can compare it against GitHub's latest release.
  env: {
    NEXT_PUBLIC_APP_VERSION: APP_VERSION,
    NEXT_PUBLIC_API_BASE,
    NEXT_PUBLIC_AUTH_ENABLED,
  },

  // Standalone output: self-contained server.js + minimal node_modules
  // This eliminates the need to copy the full node_modules into Docker production images
  output: "standalone",

  // Keep the standalone bundle rooted at this frontend directory. Without an
  // explicit root, Next.js can mirror the absolute checkout path inside
  // `.next-deeptutor/standalone`, while the DeepTutor launcher expects
  // `.next-deeptutor/standalone/server.js` directly.
  outputFileTracingRoot: __dirname,

  // web/proxy.ts clones request bodies before rewriting them. Keep enough room
  // for individual large-body endpoints that still use Proxy. Knowledge-base
  // create/upload batches use dedicated streaming route handlers instead, so
  // their total size is not coupled to this in-memory clone limit.
  experimental: {
    proxyClientMaxBodySize: 210 * 1024 * 1024,
    // Agentic reads and full-draft edits routinely exceed Next's 30-second
    // rewrite default; the browser remains responsible for cancelling them.
    proxyTimeout: 30 * 60 * 1000,
  },

  // Move dev indicator to bottom-right corner
  devIndicators: {
    position: "bottom-right",
  },

  // Transpile mermaid and related packages for proper ESM handling
  transpilePackages: ["mermaid"],

  // v1.6.2 and earlier bookmarked Mastery Study at `/study`; tip teaches under
  // `/sessions`. Permanent redirects keep old URLs (and issue repro links)
  // landing on the live surface instead of a bare 404.
  async redirects() {
    return [
      {
        source: "/mastery/:pathId/study",
        destination: "/mastery/:pathId/sessions",
        permanent: true,
      },
      {
        source: "/mastery/:pathId/study/:sessionId",
        destination: "/mastery/:pathId/sessions/:sessionId",
        permanent: true,
      },
    ];
  },

  // Next.js 16 blocks cross-origin access to /_next/* dev resources (HMR
  // WebSocket, fonts, dev-only scripts) unless the request host is on this
  // allow-list. Without it, browsing http://127.0.0.1:<port>/ against a dev
  // server bound to localhost silently breaks client hydration — the SSR HTML
  // renders, but no React event handlers or effects ever attach.
  // The same applies to a phone or tablet on the LAN: `next dev` advertises a
  // "Network: http://<lan-ip>:<port>" address, and that host has to be on the
  // list too or the device gets the identical hydrated-nothing shell — a
  // top bar with an empty page under it. Detected rather than hard-coded so it
  // follows whatever network this machine is on. Dev-only: `allowedDevOrigins`
  // has no effect on `next build`/`next start`, and anyone who can reach the
  // dev server on these addresses is already inside the LAN.
  allowedDevOrigins: ["127.0.0.1", ...localNetworkHosts()],

  // Turbopack configuration (used when running `npm run dev:turbo`)
  turbopack: {
    resolveAlias: {
      // Fix for mermaid's cytoscape dependency - use CJS version
      cytoscape: "cytoscape/dist/cytoscape.cjs.js",
    },
  },

  // Webpack configuration (used for production builds - next build)
  webpack: (config) => {
    const path = require("path");
    config.resolve.alias = {
      ...config.resolve.alias,
      cytoscape: path.resolve(
        __dirname,
        "node_modules/cytoscape/dist/cytoscape.cjs.js",
      ),
    };
    return config;
  },
};

module.exports = nextConfig;
