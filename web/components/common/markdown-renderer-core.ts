import React from "react";

export function extractMarkdownText(children: React.ReactNode): string {
  return React.Children.toArray(children)
    .map((child) => {
      if (typeof child === "string" || typeof child === "number") {
        return String(child);
      }
      if (React.isValidElement<{ children?: React.ReactNode }>(child)) {
        return extractMarkdownText(child.props.children);
      }
      return "";
    })
    .join("");
}

export function markdownHeadingId(
  children: React.ReactNode,
): string | undefined {
  const text = extractMarkdownText(children)
    .toLowerCase()
    .replace(/[^\w\s-]/g, "")
    .replace(/\s+/g, "-");
  return text || undefined;
}

export function hasRenderableMarkdownChildren(
  children: React.ReactNode,
): boolean {
  return (
    extractMarkdownText(children).replace(/[\s\u200B-\u200D\uFEFF]/g, "")
      .length > 0
  );
}

export function hasRenderableDetailsBody(
  children: React.ReactNode,
): boolean {
  return React.Children.toArray(children).some((child) => {
    if (typeof child === "string" || typeof child === "number") {
      return String(child).replace(/[\s\u200B-\u200D\uFEFF]/g, "").length > 0;
    }
    if (!React.isValidElement(child)) return false;
    return !(
      typeof child.type === "string" &&
      child.type.toLowerCase() === "summary"
    );
  });
}

export function stripLeadingMarkdownHashes(
  children: React.ReactNode,
): React.ReactNode {
  const values = React.Children.toArray(children);
  if (values.length > 0 && typeof values[0] === "string") {
    const cleaned = values[0].replace(/^#{1,6}\s+/, "");
    if (cleaned !== values[0]) return [cleaned, ...values.slice(1)];
  }
  return children;
}
