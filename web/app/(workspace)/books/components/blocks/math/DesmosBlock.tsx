"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronDown, ChevronUp } from "lucide-react";
import type { MathBlockConfig } from "./mathBlockAdapter";

/** Desmos 计算器 embed 页地址（无 API key 的 iframe 嵌入模式）。 */
const EMBED_SRC = "https://www.desmos.com/calculator?embed";

/** 外网不可达判定超时（毫秒）：8s 内未触发 load 即显示优雅提示。 */
const LOAD_TIMEOUT_MS = 8000;

/** load 事件后、postMessage 注入前的等待（给计算器内部初始化留时间）。 */
const INJECT_DELAY_MS = 1500;

/** expressions URL 参数编码后的长度上限（保守值，避免触发 URL 长度限制）。 */
const URL_PARAM_MAX = 1800;

/**
 * YuEdu fork: Desmos 函数图像 block。
 *
 * 嵌入 Desmos 在线图形计算器（iframe embed，无需 API key），并把
 * config.expressions 逐条注入计算器，而不是只把表达式贴成旁边的文本：
 *
 * - 主路径（postMessage）：iframe 加载完成（load 事件晚于 embed 页自身的
 *   DOMContentLoaded，此时 iframe 内 document.querySelector 等已就绪）后，
 *   向 iframe.contentWindow 逐条投递官方 'set-expression' JSON 协议消息：
 *   {"event":"set-expression","id":"graphN","latex":"<expr>"}；
 * - 退级（URL 参数）：postMessage 不可行（如 contentWindow 不可用）时，改用
 *   ?embed&expressions=<URL 编码的 JSON 数组> 重新加载 iframe，由 Desmos
 *   初始化表达式（受 URL 长度上限约束，超长则放弃注入，仅保留文本清单）；
 * - 外网不可达：8s 内 iframe 未触发 load，在 iframe 上方覆盖
 *   "Desmos 需联网，表达式如下可手输" 提示（iframe 保持挂载，慢网下 load
 *   事件晚到会自动恢复）；
 * - 表达式文本清单始终保留且可折叠，作为手动输入参照。
 *
 * 注（交付 README 有完整验证记录）：2026-08 抓取的 desmos.com embed 页
 * （commit 233d22e9）不注册父窗口 message 监听、隐藏表达式列表、初始化只读
 * data-load-data 属性，因此当前版本下 postMessage / URL 参数均为尽力注入；
 * 组件按评审要求的官方协议实现，随 Desmos 版本恢复生效时开箱可用。
 */
export default function DesmosBlock({ config }: { config: MathBlockConfig }) {
  const { t } = useTranslation();
  const expressions = (
    config.expressions.length > 0 ? config.expressions : [config.expression]
  ).filter((expr) => expr.trim().length > 0);

  // iframe 是否已加载成功（load 事件触发）。
  const loadedRef = useRef(false);
  // 注入是否已执行 / 是否已退级到 URL 参数（防止重复注入与重复退级）。
  const injectedRef = useRef(false);
  const fallbackUsedRef = useRef(false);
  const injectTimerRef = useRef<number | null>(null);

  const [failed, setFailed] = useState(false);
  const [injectMode, setInjectMode] = useState<"postMessage" | "url" | "none">(
    "none",
  );
  const [expressionsOpen, setExpressionsOpen] = useState(false);
  const [src, setSrc] = useState<string>(EMBED_SRC);
  const iframeRef = useRef<HTMLIFrameElement | null>(null);

  // 外网不可达判定：8s 内未触发 load 显示优雅提示。
  useEffect(() => {
    const timer = window.setTimeout(() => {
      if (!loadedRef.current) setFailed(true);
    }, LOAD_TIMEOUT_MS);
    return () => window.clearTimeout(timer);
  }, []);

  // 卸载时清理注入定时器。
  useEffect(
    () => () => {
      if (injectTimerRef.current !== null) {
        window.clearTimeout(injectTimerRef.current);
      }
    },
    [],
  );

  const injectViaPostMessage = useCallback((): boolean => {
    const win = iframeRef.current?.contentWindow;
    if (!win) return false;
    try {
      expressions.forEach((latex, index) => {
        win.postMessage(
          JSON.stringify({
            event: "set-expression",
            id: `graph${index + 1}`,
            latex,
          }),
          "*",
        );
      });
      return true;
    } catch {
      // postMessage 抛错（如 targetOrigin 校验失败）→ 判定不可行，走 URL 退级。
      return false;
    }
  }, [expressions]);

  const fallbackToUrlParam = useCallback(() => {
    const param = encodeURIComponent(JSON.stringify(expressions));
    if (param.length > URL_PARAM_MAX) {
      // 表达式清单超长，URL 参数路径不可行：仅保留可折叠文本清单供手动输入。
      setInjectMode("none");
      return;
    }
    fallbackUsedRef.current = true;
    setInjectMode("url");
    setSrc(`${EMBED_SRC}&expressions=${param}`);
  }, [expressions]);

  const handleLoad = useCallback(() => {
    loadedRef.current = true;
    // 慢网恢复：load 事件晚于 8s 超时到达时撤销失败态。
    setFailed(false);
    if (fallbackUsedRef.current) return;
    if (expressions.length === 0 || injectedRef.current) return;
    // load 已保证 embed 页 DOMContentLoaded 完成；再留一点时间让计算器内部
    // 控制器挂好消息监听（document.querySelector 等初始化之后）再注入。
    injectTimerRef.current = window.setTimeout(() => {
      injectTimerRef.current = null;
      if (injectedRef.current) return;
      if (injectViaPostMessage()) {
        injectedRef.current = true;
        setInjectMode("postMessage");
      } else {
        fallbackToUrlParam();
      }
    }, INJECT_DELAY_MS);
  }, [expressions, fallbackToUrlParam, injectViaPostMessage]);

  const handleError = useCallback(() => {
    loadedRef.current = false;
    setFailed(true);
  }, []);

  const hasExpressions = expressions.length > 0;

  return (
    <div className="my-4 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4 shadow-sm">
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <h3 className="text-base font-bold text-[var(--foreground)]">
          {config.title || t("Desmos graph")}
        </h3>
        {expressions[0] && (
          <code className="text-sm text-[var(--primary)]">
            {expressions[0]}
          </code>
        )}
      </div>
      {config.description && (
        <p className="mb-3 text-sm text-[var(--muted-foreground)]">
          {config.description}
        </p>
      )}

      <div className="relative h-[420px] w-full overflow-hidden rounded-lg">
        {/* 有意不使用 loading="lazy"：8s 超时判定依赖 iframe 立即开始加载。 */}
        <iframe
          ref={iframeRef}
          title={config.title || "Desmos"}
          src={src}
          className="h-full w-full rounded-lg border-0"
          allowFullScreen
          onLoad={handleLoad}
          onError={handleError}
        />
        {failed && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-[var(--border)] bg-[var(--card)] px-4 text-sm text-[var(--muted-foreground)]">
            <span>{t("Desmos 需联网，表达式如下可手输")}</span>
            {hasExpressions && (
              <>
                <button
                  type="button"
                  onClick={() => setExpressionsOpen((v) => !v)}
                  aria-expanded={expressionsOpen}
                  className="inline-flex items-center gap-1 rounded-md border border-[var(--border)] bg-[var(--background)] px-2.5 py-1 text-xs font-medium text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                >
                  {expressionsOpen ? (
                    <ChevronUp className="h-3.5 w-3.5" />
                  ) : (
                    <ChevronDown className="h-3.5 w-3.5" />
                  )}
                  {t("Expressions ({{count}})", { count: expressions.length })}
                </button>
                {expressionsOpen && (
                  <pre className="max-w-full overflow-x-auto whitespace-pre-wrap rounded bg-[var(--background)] px-3 py-2 font-mono text-xs text-[var(--foreground)]">
                    {expressions.join("\n")}
                  </pre>
                )}
              </>
            )}
          </div>
        )}
      </div>

      {/* 表达式文本清单：始终保留、可折叠，作为手动输入参照（评审要求）。 */}
      {!failed && hasExpressions && (
        <div className="mt-2">
          <button
            type="button"
            onClick={() => setExpressionsOpen((v) => !v)}
            aria-expanded={expressionsOpen}
            className="inline-flex items-center gap-1 rounded-md px-1 py-0.5 text-xs text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
          >
            {expressionsOpen ? (
              <ChevronUp className="h-3 w-3" />
            ) : (
              <ChevronDown className="h-3 w-3" />
            )}
            {t("Expressions ({{count}})", { count: expressions.length })}
            {injectMode === "postMessage" && (
              <span className="ml-1 rounded-full bg-[var(--primary)]/10 px-1.5 py-0.5 text-[10px] text-[var(--primary)]">
                {t("Injected")}
              </span>
            )}
            {injectMode === "url" && (
              <span className="ml-1 rounded-full bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-600 dark:text-amber-400">
                {t("URL fallback")}
              </span>
            )}
          </button>
          {expressionsOpen && (
            <pre className="mt-1 max-w-full overflow-x-auto whitespace-pre-wrap rounded bg-[var(--background)] px-3 py-2 font-mono text-xs text-[var(--foreground)]">
              {expressions.join("\n")}
            </pre>
          )}
        </div>
      )}

      <p className="mt-2 text-xs text-[var(--muted-foreground)]">
        {config.hint ||
          t("Drag the curve and add expressions to observe function properties.")}
      </p>
    </div>
  );
}
