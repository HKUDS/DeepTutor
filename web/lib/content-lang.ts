/**
 * Map a reply-language code onto the HTML ``lang`` value used for assistant
 * message content. Only CJK reply languages get an explicit tag: the shared
 * font stacks in ``tailwind.config.js`` deliberately lead with Simplified
 * Chinese faces, so a ``ja``/``ko``/``zh-tw`` reply rendered under them picks
 * up Simplified glyph forms (SimSun even answers for kana). Pinning the
 * script/region lets the ``:lang()`` stacks in ``globals.css`` put the
 * region-correct faces first while ``zh``/``en`` keep the default stacks.
 * Everything else returns ``undefined`` so the app shell's own ``lang``
 * keeps applying.
 */
export function contentLang(
  language: string | undefined,
): string | undefined {
  const code = language?.trim().toLowerCase().replaceAll("_", "-");
  if (!code) return undefined;
  if (code === "ja" || code === "jp" || code.startsWith("ja-")) return "ja";
  if (code === "ko" || code === "kr" || code.startsWith("ko-")) return "ko";
  if (
    code === "zh-tw" ||
    code === "zh-hant" ||
    code === "zh-hk" ||
    code === "zh-mo" ||
    code.startsWith("zh-hant-") ||
    code.startsWith("zh-tw-")
  ) {
    return "zh-Hant";
  }
  if (code === "zh" || code.startsWith("zh-")) return "zh-Hans";
  return undefined;
}
