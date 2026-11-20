/**
 * The product's visible identity.
 *
 * `DECISIONS.md` D-01 draws a hard line: the **displayed** name, title and
 * public metadata become «درسیار», while the Python package, distribution name,
 * CLI, runtime home, env prefix and every internal identifier stay `deeptutor`.
 * A user must never see "DeepTutor" in the product, and an operator must never
 * have to relearn a command because the brand changed.
 *
 * That is why this module exists as the single source for the visible side.
 * Anything a reader can see — the tab title, the empty-state label, the
 * wordmark's accessible name — reads from here, so the next brand change is one
 * edit rather than eighty-three. Anything a machine reads (import paths, CLI
 * verbs, `DEEPTUTOR_HOME`, `/api/...` routes) deliberately does not.
 *
 * The upstream attribution is not branding and does not belong here: it lives
 * in `THIRD_PARTY_NOTICES.md` and the README, where D-01 requires it to stay.
 */

/** Displayed product name, in the product's own language. */
export const PRODUCT_NAME_FA = "درسیار";

/** Displayed product name for Latin-script contexts (metadata, alt text). */
export const PRODUCT_NAME_LATIN = "Darsyar";

/**
 * Compact English tagline used where the product introduces itself in one line.
 * Kept in English because it accompanies the Latin name.
 */
export const PRODUCT_TAGLINE = "Agent-native learning companion";

/** Persian tagline for `lang="fa"` surfaces. */
export const PRODUCT_TAGLINE_FA = "همراه یادگیری عامل‌محور";

/**
 * The name to show for a given interface language. Persian gets the Persian
 * wordmark; every other locale gets the Latin one, which is how the product
 * presents itself outside Iran rather than transliterating the name twice.
 */
export function productName(language?: string): string {
  return language === "fa" ? PRODUCT_NAME_FA : PRODUCT_NAME_LATIN;
}
