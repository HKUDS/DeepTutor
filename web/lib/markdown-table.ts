/**
 * GFM table detection and separation for card-sized Markdown.
 *
 * Card stems are rendered through `InlineMarkdown`, which only switches to the
 * rich renderer for maths, emphasis, code and links. A stem whose only markup
 * is a table therefore used to reach the learner as raw `|` rows, pipes and
 * dashes included. These helpers let that renderer recognise and lay out a
 * table without turning every one-line stem into a block document.
 */

// The row GFM reads as a table header separator: cells of hyphens with
// optional alignment colons, at least one pipe somewhere on the line.
const TABLE_DELIMITER_ROW_REGEX =
  /^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*$/;

function isTableDelimiterRow(line: string): boolean {
  return (
    line.includes("|") &&
    line.includes("-") &&
    TABLE_DELIMITER_ROW_REGEX.test(line)
  );
}

/** Does this string contain a GFM table? */
export function hasMarkdownTable(content: string): boolean {
  if (!content || !content.includes("|")) return false;
  return String(content).split("\n").some(isTableDelimiterRow);
}

/**
 * Put a blank line after every table.
 *
 * GFM has no end marker for a table: it keeps consuming lines as rows until a
 * blank line or a new block starts. A tutor often writes the question right
 * under the table ("…如下：\n| a | b |\n|---|---|\n| 1 | 2 |\n下列说法…"), so that
 * closing sentence was parsed as one more single-cell row. Separating the
 * table restores it as the paragraph it was written as.
 */
export function separateMarkdownTables(content: string): string {
  if (!content || !content.includes("|")) return content;
  const lines = String(content).split("\n");
  const out: string[] = [];

  for (let i = 0; i < lines.length; i++) {
    out.push(lines[i]);
    if (!isTableDelimiterRow(lines[i]) || i === 0 || !lines[i - 1].includes("|"))
      continue;

    // Consume the body rows that visibly belong to this table.
    let row = i + 1;
    while (row < lines.length && lines[row].includes("|")) {
      out.push(lines[row]);
      row++;
    }
    if (row < lines.length && lines[row].trim() !== "") out.push("");
    i = row - 1;
  }

  return out.join("\n");
}
