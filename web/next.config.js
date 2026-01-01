/** @type {import('next').NextConfig} */

const nextConfig = {
  // Move dev indicator to bottom-right corner
  devIndicators: {
    position: "bottom-right",
  },

  // Transpile mermaid and related packages for proper ESM handling
  transpilePackages: ["mermaid"],

  // Turbopack configuration (Next.js 16+ uses Turbopack by default)
  turbopack: {
    resolveAlias: {
      // Fix for mermaid's cytoscape dependency - use CJS version
      // Use package-relative path for Turbopack
      cytoscape: "cytoscape/dist/cytoscape.cjs.js",
    },
  },

  // Webpack fallback for compatibility (used when --webpack flag is passed)
  webpack: (config, { isServer }) => {
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
