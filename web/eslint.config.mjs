import nextConfig from "eslint-config-next";
import i18nPlugin from "./eslint/i18n-plugin.mjs";

const config = [
  ...nextConfig,
  {
    files: ["app/**/*.{ts,tsx}", "components/**/*.{ts,tsx}", "features/**/*.{ts,tsx}"],
    plugins: {
      i18n: i18nPlugin,
    },
    rules: {
      // During migration keep as warning; change to "error" once phase2/3 complete.
      "i18n/no-literal-ui-text": "warn",
      "no-restricted-imports": [
        "error",
        {
          paths: [
            {
              name: "@/components/common/Tooltip",
              message: "Import the canonical @/shared/ui/Tooltip primitive.",
            },
            {
              name: "@/components/ui/Tooltip",
              message: "Import the canonical @/shared/ui/Tooltip primitive.",
            },
            {
              // The app tree renders inside a strict `LazyMotion`, which throws
              // on a full `motion` component rather than degrading — one such
              // import crashed the whole learning dashboard (#1549). Stating it
              // here is what stops the next file from finding out at runtime.
              name: "framer-motion",
              importNames: ["motion"],
              message:
                "Import `m as motion`: a full `motion` component throws inside the strict LazyMotion provider.",
            },
          ],
        },
      ],
      "no-restricted-syntax": [
        "warn",
        {
          selector: "JSXAttribute[name.name='role'][value.value='tooltip']",
          message: "Use @/shared/ui/Tooltip instead of a local tooltip implementation.",
        },
        {
          selector: "FunctionDeclaration[id.name=/Icon(Button|Btn)$/] JSXOpeningElement[name.type='JSXIdentifier'][name.name=/^[a-z]/] > JSXAttribute[name.name='title']",
          message: "Icon button hints must use @/shared/ui/Tooltip so they work on keyboard and touch.",
        },
      ],
    },
  },
  {
    // Vendored upstream source — see `web/vendor/thinking-orbs/index.ts` for
    // provenance and the list of local changes.
    //
    // Both hooks it ships seed their state from `matchMedia` with a
    // synchronous `setState` in the effect body, which the React Compiler rule
    // rejects. Rewriting them would deepen every future re-sync in exchange
    // for one render at mount, so the rule is off here rather than the file
    // being skipped: everything else still gets linted.
    files: ["vendor/**/*.{ts,tsx}"],
    rules: {
      "react-hooks/set-state-in-effect": "off",
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
      "public/pdfjs/**",
    ],
  },
];

export default config;
