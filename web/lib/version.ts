/** Normalize a version string into a ``vMAJOR.MINOR.PATCH`` tag form.
 *
 * Accepts PEP 440 / semver forms used in ``deeptutor/__version__.py`` and
 * GitHub release tags (``1.4.0``, ``v1.4.0``, ``1.4.0rc1``, ``v1.0.0-beta.4``)
 * while rejecting git-describe output like ``v1.2.3-5-gabc1234``.
 */
export function normalizeVersionTag(
  raw: string | null | undefined,
): string | null {
  const value = raw?.trim();
  if (!value) return null;
  const match = value.match(
    /^v?(\d+\.\d+\.\d+(?:(?:rc|a|b)\d+|\.dev\d+|\.post\d+|-[A-Za-z][0-9A-Za-z.-]*)?)$/,
  );
  return match ? `v${match[1]}` : null;
}

/** Client names, matching ``edition()`` in apps/desktop/src/platform.mjs.
 *
 * ``full`` (start screen, Settings): ``Astitvam for MacOS with Apple Silicon``.
 * ``short`` where space is tight: ``MacOS (Apple Silicon)``.
 */
export interface ClientEdition {
  full: string;
  short: string;
}

const WEB: ClientEdition = { full: "Astitvam Web", short: "Web" };
const EDITIONS: Record<string, ClientEdition> = {
  "macOS; arm64": {
    full: "Astitvam for MacOS with Apple Silicon",
    short: "MacOS (Apple Silicon)",
  },
  "macOS; x64": {
    full: "Astitvam for MacOS with Intel Silicon",
    short: "MacOS (Intel)",
  },
  "Windows; x64": { full: "Astitvam for Windows", short: "Windows" },
  // Shells from 1.7.0 sent no architecture.
  macOS: { full: "Astitvam for MacOS", short: "MacOS" },
  Windows: { full: "Astitvam for Windows", short: "Windows" },
};

/** Accept the current marker and older desktop builds during the transition. */
const DESKTOP_AGENT = /\b(?:AstitvamDesktop|OpenDeepTutor)\/\S+ \(([^)]+)\)/;

/** The client this page runs in: a desktop edition, or the web UI in a browser. */
export function clientEdition(userAgent?: string | null): ClientEdition {
  const agent =
    userAgent ?? (typeof navigator === "undefined" ? "" : navigator.userAgent);
  const platform = DESKTOP_AGENT.exec(agent)?.[1];
  return (platform && EDITIONS[platform]) || WEB;
}

/** ``Astitvam for MacOS with Apple Silicon v1.7.1`` / ``Astitvam Web v1.7.1``. */
export function clientEditionLabel(
  version: string | null | undefined,
  userAgent?: string | null,
  form: keyof ClientEdition = "full",
): string {
  const tag = normalizeVersionTag(version);
  return [clientEdition(userAgent)[form], tag].filter(Boolean).join(" ");
}
