"use client";

import { useTranslation } from "react-i18next";
import type { MathBlockConfig } from "./mathBlockAdapter";

/**
 * YuEdu fork: GeoGebra 交互几何 block。
 *
 * 两种模式（均走 iframe，无需 npm 包）：
 * 1. config.materialId -> 加载指定 GeoGebra 素材
 * 2. 无 materialId -> 打开 GeoGebra 在线计算器
 * config.commands 作为初始命令展示在折叠面板里。iframe 失败时浏览器显示空白帧，
 * 故无 materialId 时额外给出网络降级提示（不白屏）。
 */
export default function GeoGebraBlock({ config }: { config: MathBlockConfig }) {
  const { t } = useTranslation();
  const src = config.materialId
    ? `https://www.geogebra.org/material/iframe/id/${config.materialId}`
    : "https://www.geogebra.org/calculator";

  return (
    <div className="my-4 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4 shadow-sm">
      {config.title && (
        <h3 className="mb-2 text-base font-bold text-[var(--foreground)]">
          {config.title}
        </h3>
      )}
      {config.description && (
        <p className="mb-3 text-sm text-[var(--muted-foreground)]">
          {config.description}
        </p>
      )}
      <iframe
        title={config.title || "GeoGebra"}
        src={src}
        className="h-96 w-full rounded-lg border-0"
        loading="lazy"
        allow="fullscreen"
      />
      {!config.materialId && (
        <p className="mt-2 text-xs text-[var(--muted-foreground)]">
          {t("If GeoGebra does not load, check the network or provide a material id.")}
        </p>
      )}
      {config.commands.length > 0 && (
        <details className="mt-2 rounded border border-[var(--border)] bg-[var(--background)] p-2 text-xs text-[var(--muted-foreground)]">
          <summary className="cursor-pointer font-medium">
            {t("Initial commands")}
          </summary>
          <pre className="mt-1 whitespace-pre-wrap font-mono text-[11px]">
            {config.commands.join("\n")}
          </pre>
        </details>
      )}
    </div>
  );
}
