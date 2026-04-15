"use client";

import React, { useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { normalizeMarkdownForDisplay } from "@/lib/markdown-display";
import type { MarkdownRendererProps } from "./MarkdownRenderer";

function extractText(children: React.ReactNode): string {
  return React.Children.toArray(children)
    .map((child) => {
      if (typeof child === "string" || typeof child === "number") {
        return String(child);
      }

      if (React.isValidElement<{ children?: React.ReactNode }>(child)) {
        return extractText(child.props.children);
      }

      return "";
    })
    .join("");
}

function headingId(children: React.ReactNode): string | undefined {
  const text = extractText(children)
    .toLowerCase()
    .replace(/[^\w\s-]/g, "")
    .replace(/\s+/g, "-");
  return text || undefined;
}

function hasRenderableChildren(children: React.ReactNode): boolean {
  return extractText(children).replace(/[\s\u200B-\u200D\uFEFF]/g, "").length > 0;
}

function hasRenderableDetailsBody(children: React.ReactNode): boolean {
  return React.Children.toArray(children).some((child) => {
    if (typeof child === "string" || typeof child === "number") {
      return String(child).replace(/[\s\u200B-\u200D\uFEFF]/g, "").length > 0;
    }

    if (!React.isValidElement(child)) return false;
    if (typeof child.type === "string" && child.type.toLowerCase() === "summary") {
      return false;
    }

    return true;
  });
}

function stripLeadingHashes(children: React.ReactNode): React.ReactNode {
  const arr = React.Children.toArray(children);
  if (arr.length > 0 && typeof arr[0] === "string") {
    const cleaned = arr[0].replace(/^#{1,6}\s+/, "");
    if (cleaned !== arr[0]) return [cleaned, ...arr.slice(1)];
  }
  return children;
}

export default function SimpleMarkdownRenderer({
  content,
  className = "",
  variant = "default",
}: MarkdownRendererProps) {
  const normalizedContent = useMemo(() => normalizeMarkdownForDisplay(content), [content]);
  const isTrace = variant === "trace";
  const gap = isTrace ? "my-1" : variant === "compact" ? "my-2" : "my-4";
  const cellPad =
    isTrace ? "px-1.5 py-1" : variant === "compact" ? "px-2 py-1.5" : "px-3 py-2";
  const headingSpacing = variant === "compact" ? "mt-4 mb-2" : "mt-6 mb-3";
  const textColor = "text-[var(--foreground)]";

  const traceComponents: Record<string, React.ComponentType<any>> = {
    p: ({ node, ...props }: any) => <p className="mb-1.5 last:mb-0" {...props} />,
    h1: ({ node, children }: any) => <p className="mb-1.5 font-semibold">{children}</p>,
    h2: ({ node, children }: any) => <p className="mb-1.5 font-semibold">{children}</p>,
    h3: ({ node, children }: any) => <p className="mb-1.5 font-semibold">{children}</p>,
    h4: ({ node, children }: any) => <p className="mb-1.5 font-semibold">{children}</p>,
    h5: ({ node, children }: any) => <p className="mb-1.5 font-semibold">{children}</p>,
    h6: ({ node, children }: any) => <p className="mb-1.5 font-semibold">{children}</p>,
    strong: ({ node, children }: any) => (
      <strong className="font-semibold text-[var(--foreground)]">{children}</strong>
    ),
    em: ({ node, children }: any) => <em className="italic">{children}</em>,
    a: ({ node, children }: any) => (
      <span className="underline underline-offset-2">{children}</span>
    ),
    blockquote: ({ node, children }: any) => (
      <div className="border-l border-current/20 pl-3 opacity-80">{children}</div>
    ),
    pre: ({ children }: any) => <>{children}</>,
    code: ({ node, children }: any) => (
      <code className="rounded bg-[var(--muted)] px-1 py-0.5 font-mono text-[0.95em] text-[var(--foreground)]">
        {String(children).replace(/\n$/, "")}
      </code>
    ),
    img: () => null,
    hr: () => <div className="my-1 h-px bg-current opacity-10" />,
    ul: ({ node, ...props }: any) => <ul className="my-1 ml-4 list-disc" {...props} />,
    ol: ({ node, ...props }: any) => <ol className="my-1 ml-4 list-decimal" {...props} />,
    li: ({ node, ...props }: any) => <li className="my-0.5 pl-0" {...props} />,
    table: ({ node, children, ...props }: any) =>
      hasRenderableChildren(children) ? (
        <div className="my-1 overflow-x-auto rounded border border-[var(--border)]/50">
          <table className="min-w-full text-[inherit]" {...props}>
            {children}
          </table>
        </div>
      ) : null,
    thead: ({ node, ...props }: any) => <thead className="bg-[var(--muted)]/50" {...props} />,
    th: ({ node, ...props }: any) => (
      <th
        className="border-b border-[var(--border)]/50 px-1.5 py-0.5 text-left font-medium"
        {...props}
      />
    ),
    tbody: ({ node, ...props }: any) => <tbody {...props} />,
    td: ({ node, ...props }: any) => (
      <td className="border-b border-[var(--border)]/30 px-1.5 py-0.5" {...props} />
    ),
    tr: ({ node, ...props }: any) => <tr {...props} />,
    input: ({ node, type, ...props }: any) =>
      type === "checkbox" ? (
        <input type="checkbox" readOnly className="mr-1 align-middle" {...props} />
      ) : null,
    progress: () => null,
    meter: () => null,
    button: () => null,
    select: () => null,
    option: () => null,
    textarea: () => null,
    details: ({ node, children }: any) =>
      hasRenderableDetailsBody(children) ? <div>{children}</div> : null,
    summary: ({ node, children }: any) =>
      hasRenderableChildren(children) ? <span>{children}</span> : null,
  };

  const headingComponents = {
    h1: ({ node, children, className: headingClassName, ...props }: any) => {
      const clean = stripLeadingHashes(children);
      return (
        <h1
          id={headingId(clean)}
          className={`scroll-mt-20 font-sans text-2xl font-bold tracking-tight ${textColor} ${
            variant === "compact" ? "mt-5 mb-2" : "mt-8 mb-4"
          } ${headingClassName || ""}`}
          {...props}
        >
          {clean}
        </h1>
      );
    },
    h2: ({ node, children, className: headingClassName, ...props }: any) => {
      const clean = stripLeadingHashes(children);
      return (
        <h2
          id={headingId(clean)}
          className={`scroll-mt-20 font-sans text-xl font-semibold tracking-tight ${textColor} ${
            variant === "compact" ? "mt-4 mb-2" : "mt-7 mb-3"
          } ${headingClassName || ""}`}
          {...props}
        >
          {clean}
        </h2>
      );
    },
    h3: ({ node, children, className: headingClassName, ...props }: any) => {
      const clean = stripLeadingHashes(children);
      return (
        <h3
          id={headingId(clean)}
          className={`scroll-mt-20 font-sans text-lg font-semibold tracking-tight ${textColor} ${
            variant === "compact" ? "mt-4 mb-1.5" : "mt-6 mb-2.5"
          } ${headingClassName || ""}`}
          {...props}
        >
          {clean}
        </h3>
      );
    },
    h4: ({ node, children, className: headingClassName, ...props }: any) => {
      const clean = stripLeadingHashes(children);
      return (
        <h4
          id={headingId(clean)}
          className={`scroll-mt-20 font-sans text-base font-semibold ${textColor} ${
            variant === "compact" ? "mt-3 mb-1.5" : "mt-5 mb-2"
          } ${headingClassName || ""}`}
          {...props}
        >
          {clean}
        </h4>
      );
    },
    h5: ({ node, children, className: headingClassName, ...props }: any) => {
      const clean = stripLeadingHashes(children);
      return (
        <h5
          id={headingId(clean)}
          className={`scroll-mt-20 font-sans text-sm font-semibold ${textColor} ${
            variant === "compact" ? "mt-3 mb-1.5" : "mt-4 mb-2"
          } ${headingClassName || ""}`}
          {...props}
        >
          {clean}
        </h5>
      );
    },
    h6: ({ node, children, className: headingClassName, ...props }: any) => {
      const clean = stripLeadingHashes(children);
      return (
        <h6
          id={headingId(clean)}
          className={`scroll-mt-20 font-sans text-sm font-semibold uppercase tracking-wide text-[var(--muted-foreground)] ${
            variant === "compact" ? "mt-3 mb-1.5" : "mt-4 mb-2"
          } ${headingClassName || ""}`}
          {...props}
        >
          {clean}
        </h6>
      );
    },
  };

  const normalComponents: Record<string, React.ComponentType<any>> = {
    ...headingComponents,
    table: ({ node, children, ...props }: any) =>
      hasRenderableChildren(children) ? (
        <div className={`overflow-x-auto rounded-lg border border-[var(--border)] shadow-sm ${gap}`}>
          <table className="min-w-full divide-y divide-[var(--border)] text-sm" {...props}>
            {children}
          </table>
        </div>
      ) : null,
    thead: ({ node, ...props }: any) => <thead className="bg-[var(--muted)]" {...props} />,
    th: ({ node, ...props }: any) => (
      <th
        className={`border-b border-[var(--border)] text-left font-semibold text-[var(--foreground)] ${cellPad}`}
        {...props}
      />
    ),
    tbody: ({ node, ...props }: any) => (
      <tbody className="divide-y divide-[var(--border)] bg-[var(--card)]" {...props} />
    ),
    td: ({ node, ...props }: any) => (
      <td
        className={`border-b border-[var(--border)] text-[var(--muted-foreground)] ${cellPad}`}
        {...props}
      />
    ),
    tr: ({ node, ...props }: any) => (
      <tr className="transition-colors hover:bg-[var(--muted)]/60" {...props} />
    ),
    pre: ({ children }: any) => <>{children}</>,
    code: ({ node, children, ...props }: any) => {
      const raw = String(children).replace(/\n$/, "");

      if (raw.includes("\n")) {
        return (
          <div
            className={`md-code-block ${gap} overflow-hidden rounded-xl border border-[var(--border)] bg-[#292524]`}
          >
            <pre className="overflow-x-auto p-4 text-sm leading-relaxed text-[#D6D3D1]">
              <code {...props}>{raw}</code>
            </pre>
          </div>
        );
      }

      return (
        <code
          className="md-inline-code rounded bg-[var(--muted)] px-1.5 py-0.5 font-mono text-[0.875em] text-[var(--foreground)]"
          {...props}
        >
          {children}
        </code>
      );
    },
    a: ({ node, href, children, title, ...props }: any) => {
      const isCitation = title === "citation";
      const isHashLink = href?.startsWith("#");
      const external = href?.startsWith("http://") || href?.startsWith("https://");

      if (isCitation) {
        const label = extractText(children);
        const ids = label.split(/\s*,\s*/);
        const scrollToRef = (event: React.MouseEvent) => {
          event.preventDefault();
          const target = document.getElementById("references");
          target?.scrollIntoView({ block: "start", behavior: "smooth" });
        };
        return (
          <span className="citation-group mx-0.5 text-[0.78em] leading-snug text-[var(--muted-foreground)]" {...props}>
            [
            {ids.map((id, idx) => {
              const prefixMatch = id.match(/^(web|rag|code|src)-/);
              const prefix = prefixMatch?.[1] ?? "";
              const num = prefix && prefixMatch ? id.slice(prefixMatch[0].length) : id;
              return (
                <React.Fragment key={id}>
                  {idx > 0 && ", "}
                  <a
                    href={href}
                    onClick={scrollToRef}
                    className="cursor-pointer text-[var(--primary)] no-underline transition-colors hover:text-[var(--primary)]/70 hover:underline"
                  >
                    {prefix ? <><span className="text-[0.85em] font-semibold uppercase tracking-wide">{prefix}</span>{num}</> : num}
                  </a>
                </React.Fragment>
              );
            })}
            ]
          </span>
        );
      }

      return (
        <a
          href={href}
          {...(external ? { target: "_blank", rel: "noopener noreferrer" } : {})}
          onClick={(event) => {
            if (!isHashLink || !href) return;

            event.preventDefault();
            const targetId = decodeURIComponent(href.slice(1));
            const target = document.getElementById(targetId);
            target?.scrollIntoView({ block: "start", behavior: "smooth" });
          }}
          className="text-[var(--primary)] underline decoration-[var(--primary)]/40 underline-offset-2 transition-colors hover:decoration-[var(--primary)]"
          {...props}
        >
          {children}
        </a>
      );
    },
    img: ({ node, src, alt, ...props }: any) => (
      <img
        src={src}
        alt={alt || ""}
        loading="lazy"
        className={`${gap} inline-block max-w-full rounded-lg border border-[var(--border)]`}
        {...props}
      />
    ),
    blockquote: ({ node, ...props }: any) => (
      <blockquote
        className={`${gap} border-l-[3px] border-[var(--muted-foreground)] pl-4 italic text-[var(--muted-foreground)] [&>p]:mb-1`}
        {...props}
      />
    ),
    hr: ({ node, ...props }: any) => (
      <hr className={`${gap} h-px border-none bg-[var(--border)]`} {...props} />
    ),
    input: ({ node, type, checked, ...props }: any) =>
      type === "checkbox" ? (
        <input
          type="checkbox"
          checked={checked}
          readOnly
          className="mr-2 h-4 w-4 rounded border-[var(--border)] align-middle accent-[var(--primary)]"
          {...props}
        />
      ) : null,
    progress: () => null,
    meter: () => null,
    button: () => null,
    select: () => null,
    option: () => null,
    textarea: () => null,
    details: ({ node, children, ...props }: any) =>
      hasRenderableDetailsBody(children) ? (
        <details
          className={`${gap} rounded-lg border border-[var(--border)] bg-[var(--card)] px-4 py-2`}
          {...props}
        >
          {children}
        </details>
      ) : null,
    summary: ({ node, children, ...props }: any) =>
      hasRenderableChildren(children) ? (
        <summary
          className="cursor-pointer select-none font-medium text-[var(--foreground)]"
          {...props}
        >
          {children}
        </summary>
      ) : null,
  };

  const components = useMemo(
    () => (isTrace ? traceComponents : normalComponents),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- components only change with variant
    [isTrace, variant],
  );

  const remarkPlugins = useMemo(() => [remarkGfm], []);

  const rootClasses = isTrace
    ? "md-renderer max-w-none font-sans text-[11px] leading-[1.55] text-[var(--muted-foreground)]"
    : variant === "prose"
      ? "md-renderer prose max-w-none font-serif"
      : "md-renderer prose prose-sm max-w-none font-serif";

  return (
    <div className={`${rootClasses} ${className}`}>
      <ReactMarkdown remarkPlugins={remarkPlugins} components={components}>
        {normalizedContent}
      </ReactMarkdown>
    </div>
  );
}
