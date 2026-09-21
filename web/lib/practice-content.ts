/** Older generated stems sometimes put a fenced block directly after prose. */
export function practiceMarkdown(content: string): string {
  return content.replace(/([^\n])(```[\w+-]*[ \t]*\r?\n)/g, "$1\n\n$2");
}
