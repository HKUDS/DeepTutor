"use client";

import { useTranslation } from "react-i18next";
import katex from "katex";
import "katex/dist/katex.min.css";
import type { MathBlockConfig, FormulaItem } from "./mathBlockAdapter";

const DEFAULT_FORMULAS: FormulaItem[] = [
  { tex: "f(x) = ax^2 + bx + c", caption: "二次函数一般式。" },
  { tex: "x = \\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a}", caption: "求根公式。" },
];

function renderTex(tex: string): string {
  try {
    return katex.renderToString(tex, {
      displayMode: true,
      throwOnError: false,
    });
  } catch {
    return tex;
  }
}

/**
 * YuEdu fork: KaTeX 公式渲染 block。
 * 用 config.formulas（{tex, caption}）以 KaTeX 渲染；为空时用默认公式样例。
 */
export default function KatexFormulaBlock({
  config,
}: {
  config: MathBlockConfig;
}) {
  const { t } = useTranslation();
  const formulas =
    config.formulas.length > 0 ? config.formulas : DEFAULT_FORMULAS;

  return (
    <div className="my-4 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4 shadow-sm">
      <h3 className="mb-3 text-base font-bold text-[var(--foreground)]">
        {config.title || t("Formula (KaTeX)")}
      </h3>
      {config.description && (
        <p className="mb-3 text-sm text-[var(--muted-foreground)]">
          {config.description}
        </p>
      )}
      <div className="space-y-3">
        {formulas.map((f, i) => (
          <div
            key={i}
            className="rounded-lg border border-[var(--border)] bg-[var(--background)] p-3"
          >
            <div
              className="overflow-x-auto text-lg text-[var(--foreground)] [&::-webkit-scrollbar]:hidden"
              // KaTeX 输出是本地受信任渲染产物
              dangerouslySetInnerHTML={{ __html: renderTex(f.tex) }}
            />
            {f.caption && (
              <p className="mt-2 text-sm text-[var(--muted-foreground)]">
                {f.caption}
              </p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
