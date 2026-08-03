"use client";

import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";

import {
  getCodeBlockTheme,
  getCodeBlockThemeBackground,
} from "./code-block-themes";
import { useAppShell } from "../../context/AppShellContext";

const MONOSPACE =
  'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace';

const PLAIN_LANGS = new Set(["", "text", "txt", "plain", "plaintext", "none"]);
const DEFAULT_CODE_BLOCK_BACKGROUND = "#1f2937";
const DEFAULT_CODE_BLOCK_FOREGROUND = "#e5e7eb";

function getCodeBlockThemeForeground(
  style: Record<string, React.CSSProperties>,
): string | undefined {
  const codeStyle = style['code[class*="language-"]'];
  if (codeStyle && typeof codeStyle.color === "string") {
    return codeStyle.color;
  }

  const preStyle = style['pre[class*="language-"]'];
  if (preStyle && typeof preStyle.color === "string") {
    return preStyle.color;
  }

  return undefined;
}

export default function RichCodeBlock({
  raw,
  lang,
  className,
}: {
  raw: string;
  lang: string;
  className?: string;
}) {
  const { codeBlockTheme, codeBlockShowLineNumbers, codeBlockWrapLongLines } =
    useAppShell();
  const normalizedLang = (lang || "").toLowerCase();
  const isPlain = PLAIN_LANGS.has(normalizedLang);
  const syntaxTheme = getCodeBlockTheme(codeBlockTheme);
  const backgroundColor =
    getCodeBlockThemeBackground(syntaxTheme) ?? DEFAULT_CODE_BLOCK_BACKGROUND;
  const textColor =
    getCodeBlockThemeForeground(syntaxTheme) ?? DEFAULT_CODE_BLOCK_FOREGROUND;
  const syntaxLanguage = isPlain ? "text" : normalizedLang;

  return (
    <div
      className={`md-code-block overflow-hidden rounded-xl border border-[var(--border)] ${
        className || ""
      }`}
      style={{ backgroundColor, color: textColor }}
    >
      {!isPlain ? (
        <div
          className="border-b border-[var(--border)] px-3 py-2 text-[11px] font-medium uppercase tracking-wider"
          style={{ color: textColor, opacity: 0.8 }}
        >
          {normalizedLang}
        </div>
      ) : null}
      <SyntaxHighlighter
        language={syntaxLanguage}
        style={syntaxTheme}
        PreTag="pre"
        customStyle={{
          margin: 0,
          borderRadius: 0,
          background: backgroundColor,
          color: textColor,
          padding: "1rem",
          fontSize: "0.875rem",
          lineHeight: "1.7",
          overflowX: codeBlockWrapLongLines ? "hidden" : "auto",
          whiteSpace: codeBlockWrapLongLines ? "pre-wrap" : "pre",
          wordWrap: codeBlockWrapLongLines ? "break-word" : "normal",
        }}
        codeTagProps={{
          className: "md-code-block__code",
          style: {
            fontFamily: MONOSPACE,
            ...(codeBlockWrapLongLines ? { wordWrap: "break-word" } : {}),
          },
        }}
        showLineNumbers={codeBlockShowLineNumbers}
        wrapLongLines={codeBlockWrapLongLines}
        // react-syntax-highlighter's highlight.js forces `display:flex` onto
        // each per-line span when BOTH wrapLongLines and showLineNumbers are
        // on (so the line-number gutter can align in a column). That flex
        // layout makes each token span a flex item with the default
        // `min-width:auto`, which cannot shrink below content size — so a
        // long unbreakable token overflows the line wrapper and defeats
        // `overflow-wrap:break-word` set on <pre>/<code>. Overriding the
        // per-line wrapper back to `display:block` lets the tokens flow as
        // normal inline content, where `overflow-wrap:break-word` can
        // actually break long tokens.
        lineProps={
          codeBlockWrapLongLines && codeBlockShowLineNumbers
            ? { style: { display: "block" } }
            : undefined
        }
      >
        {raw}
      </SyntaxHighlighter>
    </div>
  );
}
