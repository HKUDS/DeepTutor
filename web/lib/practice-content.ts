/** Canonical blank IDs belong to answer mapping, not learner-facing text. */
export function displayQuestionBlanks(content: string): string {
  return content.replace(/\{\{blank:[A-Za-z0-9_-]{1,80}\}\}/g, "___");
}

/** Escape underscores so a standalone blank is not a Markdown horizontal rule. */
export function practiceQuestionMarkdown(content: string): string {
  return practiceMarkdown(content.replace(/\{\{blank:[A-Za-z0-9_-]{1,80}\}\}/g, "\\_\\_\\_"));
}

/** Older generated stems sometimes put a fenced block directly after prose. */
export function practiceMarkdown(content: string): string {
  return content.replace(/([^\n])(```[\w+-]*[ \t]*\r?\n)/g, "$1\n\n$2");
}
