/** Turn assistant timestamp references into links handled by WatchingContext. */
export function linkifyTimestampCitations(text: string): string {
  const mask = (value: string) => value.replace(/\[(\d{1,2}:\d{2}(?::\d{2})?)\](?!\()/g, (_match, raw: string) => {
    const parts = raw.split(":").map(Number);
    const seconds = parts.length === 3 ? parts[0] * 3600 + parts[1] * 60 + parts[2] : parts[0] * 60 + parts[1];
    return `[${raw}](#dt-time-${seconds})`;
  });
  return text.split(/(```[\s\S]*?```|`[^`]*`)/g).map((part, index) => index % 2 ? part : mask(part)).join("");
}
