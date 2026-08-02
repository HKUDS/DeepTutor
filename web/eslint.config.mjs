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
    ignores: ["node_modules/**", ".next/**", ".next-deeptutor/**", "dist/**", "out/**"],
  },
];

export default config;
