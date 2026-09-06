import type { TFunction } from "i18next";

/**
 * What to tell the user about a material that could not be prepared.
 *
 * The server's `error_detail` is English prose written for a log, so a known
 * `error_code` is translated instead — and the codes worth translating are the
 * ones the user can act on. Anything unrecognised falls through to the detail,
 * which is still better than a bare "something went wrong".
 */
export function readingFailureMessage(
  material: { error_code?: string; error_detail?: string },
  t: TFunction,
): string {
  if (material.error_code === "stt_not_configured") {
    return t(
      "Audio and video need a speech-to-text model. Choose one in Settings → Voice, then retry.",
    );
  }
  if (material.error_code === "media_source_missing") {
    return t("The stored file is gone. Upload it again.");
  }
  return material.error_detail || "";
}
