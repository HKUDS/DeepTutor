/**
 * A learner decision the tutor wrote as prose instead of `ask_user`.
 *
 * Outline edits often end with "一件需要你拍板的事" and a bullet list. That
 * list is the choice, and the study screen lifts it into the decision dialog.
 * Teaching that merely mentions two approaches does not match: the cue has to
 * ask the learner to pick, and at least two options have to follow it.
 */
export interface ParsedOutlineDecision {
  prompt: string;
  options: string[];
}

const CUE =
  /拍板|你倾向哪种|你更倾向|which do you prefer|which would you rather/i;
const BULLET = /^\s*(?:[-*+•●·]|\d{1,2}[.)、])\s+(\S.*)$/;

export function parseOutlineDecision(
  text: string,
): ParsedOutlineDecision | null {
  const lines = (text || "").split(/\r?\n/);
  const cueAt = lines.findIndex((line) => CUE.test(line));
  if (cueAt < 0) return null;

  const options: string[] = [];
  let firstBullet = -1;
  for (let index = cueAt + 1; index < lines.length; index += 1) {
    const match = lines[index].match(BULLET);
    if (match) {
      if (firstBullet < 0) firstBullet = index;
      options.push(match[1].trim());
      continue;
    }
    if (!lines[index].trim()) continue;
    if (options.length) break;
  }
  if (options.length < 2 || firstBullet < 0) return null;

  const prompt = lines
    .slice(cueAt, firstBullet)
    .map((line) => line.trim())
    .filter(Boolean)
    .join("\n");
  if (!prompt) return null;
  return { prompt, options };
}

type TranscriptMessage = {
  role?: string;
  content?: string;
};

/** The decision on the latest unanswered assistant reply, if it wrote one. */
export function pendingProseDecision(
  messages: TranscriptMessage[],
): ParsedOutlineDecision | null {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message?.role === "user") return null;
    if (message?.role !== "assistant") continue;
    return parseOutlineDecision(message.content || "");
  }
  return null;
}
