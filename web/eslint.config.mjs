import nextConfig from "eslint-config-next";
import i18nPlugin from "./eslint/i18n-plugin.mjs";

const config = [
  ...nextConfig,
  {
    files: ["app/**/*.{ts,tsx}", "components/**/*.{ts,tsx}"],
    plugins: {
      i18n: i18nPlugin,
    },
    rules: {
      // During migration keep as warning; change to "error" once phase2/3 complete.
      "i18n/no-literal-ui-text": "warn",
    },
  },
  {
    // ``.next-*`` covers every build output, including the throwaway dist dirs
    // a second dev server needs (DEEPTUTOR_NEXT_DIST_DIR, see next.config.js):
    // without it, running one turns `npx eslint .` — a CI gate — red with
    // hundreds of errors from generated code.
    ignores: [
      "node_modules/**",
      ".next/**",
      ".next-*/**",
      "dist/**",
      "out/**",
      "tmp/**",
      "coverage/**",
      "playwright-report/**",
      "test-results/**",
      "contracts/generated/.tmp/**",
    ],
  },
];

export default config;
